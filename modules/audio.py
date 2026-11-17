# modules/audio.py

import logging
import queue
import re
import threading
import time
import numpy as np
import sounddevice as sd
import speech_recognition as sr
import tempfile
import soundfile as sf
import torch
from pathlib import Path
from modules.config import config
from modules.gpu_lock import gpu_vram_lock
from modules.settings_manager import settings_manager

logger = logging.getLogger("EmotionEngine.Audio")


class AudioEngine:
    # Class-level ducking and voice state shared across AudioEngine and GUI Music Cards
    is_speaking_event = threading.Event()
    tts_synthesis_done_event = threading.Event()
    tts_playback_done_event = threading.Event()
    _music_stop_event = threading.Event()
    _music_pause_event = threading.Event()
    _music_lock = threading.Lock()
    last_music_completed_naturally = False
    _sfx_cache = {}
    _sfx_last_played = {}
    _sfx_cache_lock = threading.Lock()
    sfx_enabled = True
    sfx_volume = 0.75
    music_volume = 0.60
    _music_position_sec = 0.0
    _music_duration_sec = 0.0

    # Real-time audio visualization tap (zero-device-contention feed for Spectrum Analyzer)
    _vis_lock = threading.Lock()
    _vis_samples = np.zeros(1024, dtype=np.float32)
    _vis_samplerate = 24000
    _vis_timestamp = 0.0
    _vis_source = "idle"

    def __init__(self, tts_pipeline, whisper_model, voice_name="af_heart"):
        self.tts_pipeline = tts_pipeline        
        self.whisper_model = whisper_model
        self.voice_name = settings_manager.get("kokoro_voice", voice_name)
        self.master_volume = float(settings_manager.get("master_volume", 0.8))
        AudioEngine.sfx_enabled = bool(settings_manager.get("sfx_enabled", True))
        AudioEngine.sfx_volume = float(settings_manager.get("sfx_volume", 0.75))
        self.recognizer = sr.Recognizer()
        self.microphone = sr.Microphone()
        self.samplerate = 16000
        self._playback_lock = threading.Lock()
        self._voice_stop_event = threading.Event()
        self._speech_queue = queue.Queue()
        self._speech_worker_thread = threading.Thread(target=self._speech_queue_loop, daemon=True)
        self._speech_worker_thread.start()
        AudioEngine.tts_synthesis_done_event.set()
        AudioEngine.tts_playback_done_event.set()
        self._preload_sfx()

    def set_voice(self, voice_code):
        if voice_code:
            self.voice_name = voice_code

    def set_volume(self, volume: float):
        if volume is not None:
            self.master_volume = max(0.0, min(1.0, float(volume)))

    @classmethod
    def set_sfx_enabled(cls, enabled: bool):
        cls.sfx_enabled = bool(enabled)

    @classmethod
    def set_sfx_volume(cls, volume: float):
        if volume is not None:
            cls.sfx_volume = max(0.0, min(1.0, float(volume)))

    @classmethod
    def push_vis_samples(cls, chunk: np.ndarray, samplerate: int = 24000, source: str = "voice"):
        """Pushes the active playback audio slice into the real-time visualization buffer."""
        try:
            arr = np.asarray(chunk, dtype=np.float32)
            if arr.ndim == 2:
                mono = arr.mean(axis=1) if arr.shape[1] > 1 else arr[:, 0]
            else:
                mono = arr.ravel()
            n = mono.size
            if n == 0:
                return
            with cls._vis_lock:
                if n >= 1024:
                    cls._vis_samples = mono[:1024].copy()
                else:
                    buf = np.zeros(1024, dtype=np.float32)
                    buf[:n] = mono
                    cls._vis_samples = buf
                cls._vis_samplerate = int(samplerate or 24000)
                cls._vis_timestamp = time.time()
                cls._vis_source = source
        except Exception:
            pass

    @classmethod
    def clear_vis_samples(cls):
        """Resets the real-time visualization buffer to silence."""
        with cls._vis_lock:
            cls._vis_samples = np.zeros(1024, dtype=np.float32)
            cls._vis_timestamp = 0.0
            cls._vis_source = "idle"

    @classmethod
    def get_vis_snapshot(cls):
        """Returns (mono_1024_float32, samplerate, timestamp, source) for real-time spectrum analysis."""
        with cls._vis_lock:
            return (
                cls._vis_samples.copy(),
                cls._vis_samplerate,
                cls._vis_timestamp,
                cls._vis_source
            )

    @classmethod
    def _preload_sfx(cls):
        """Pre-loads all .wav files from the sfx/ directory into RAM for zero-latency playback."""
        sfx_dir = getattr(config, "SFX_DIR", config.BASE_DIR / "sfx")
        if not sfx_dir.exists():
            return
        with cls._sfx_cache_lock:
            for wav_path in sfx_dir.glob("*.wav"):
                key = wav_path.stem.lower()
                if key not in cls._sfx_cache:
                    try:
                        data, fs = sf.read(str(wav_path), dtype="float32")
                        if data.ndim == 1:
                            data = data[:, np.newaxis]
                        cls._sfx_cache[key] = (data, int(fs))
                    except Exception as e:
                        logger.warning(f"[AudioEngine] Could not preload SFX '{wav_path.name}': {e}")

    @classmethod
    def play_sfx(cls, sfx_name: str):
        """
        Plays an interface sound effect asynchronously on a dedicated OutputStream
        so it mixes cleanly without interrupting TTS voice or background music.
        """
        if not cls.sfx_enabled or cls.sfx_volume <= 0.01 or not sfx_name:
            return

        key = Path(sfx_name).stem.lower().strip()
        now = time.time()

        with cls._sfx_cache_lock:
            last_t = cls._sfx_last_played.get(key, 0.0)
            if now - last_t < 0.08:
                return
            cls._sfx_last_played[key] = now

            cached = cls._sfx_cache.get(key)
            if cached is None:
                sfx_dir = getattr(config, "SFX_DIR", config.BASE_DIR / "sfx")
                wav_path = sfx_dir / f"{key}.wav"
                if wav_path.exists():
                    try:
                        data, fs = sf.read(str(wav_path), dtype="float32")
                        if data.ndim == 1:
                            data = data[:, np.newaxis]
                        cached = (data, int(fs))
                        cls._sfx_cache[key] = cached
                    except Exception as e:
                        logger.debug(f"[AudioEngine] Error loading SFX '{key}': {e}")
                        return
                else:
                    return

        data, fs = cached
        gain = cls.sfx_volume

        def _sfx_worker():
            try:
                scaled = (data * gain).astype(np.float32)
                channels = scaled.shape[1]
                total_frames = scaled.shape[0]
                block_size = 2048
                with sd.OutputStream(samplerate=fs, channels=channels, dtype="float32") as stream:
                    idx = 0
                    while idx < total_frames:
                        stream.write(scaled[idx:idx + block_size])
                        idx += block_size
            except Exception as e:
                logger.debug(f"[AudioEngine] SFX playback notice ({key}): {e}")

        threading.Thread(target=_sfx_worker, daemon=True).start()

    def stop_playback(self):
        """Stops active TTS voice playback and clears any queued utterances without killing background music cards."""
        while not self._speech_queue.empty():
            try:
                self._speech_queue.get_nowait()
                self._speech_queue.task_done()
            except Exception:
                break
        self._voice_stop_event.set()
        AudioEngine.tts_synthesis_done_event.set()
        AudioEngine.tts_playback_done_event.set()

    @classmethod
    def stop_music(cls):
        """Stops any active background music stream."""
        cls._music_pause_event.clear()
        cls._music_stop_event.set()

    @classmethod
    def pause_music(cls):
        """Pauses active background music stream in-place."""
        cls._music_pause_event.set()

    @classmethod
    def resume_music(cls):
        """Resumes a paused background music stream."""
        cls._music_pause_event.clear()

    @classmethod
    def is_music_paused(cls) -> bool:
        return cls._music_pause_event.is_set()

    @classmethod
    def set_music_volume(cls, volume: float):
        """Sets active background music normal gain (0.0 to 1.0)."""
        if volume is not None:
            cls.music_volume = max(0.0, min(1.0, float(volume)))

    @classmethod
    def get_music_progress(cls):
        """Returns (position_sec, duration_sec) for the active background music stream."""
        return float(cls._music_position_sec), float(cls._music_duration_sec)

    @classmethod
    def _decode_audio_file(cls, file_path: str):
        """Decodes an audio file into (float32 2D numpy array, sample_rate), with PyAV fallback."""
        try:
            data, fs = sf.read(str(file_path), dtype="float32")
            if data.ndim == 1:
                data = data[:, np.newaxis]
            return data, int(fs)
        except Exception as sf_err:
            try:
                import av
                with av.open(str(file_path)) as container:
                    if not container.streams.audio:
                        raise sf_err
                    stream = container.streams.audio[0]
                    target_rate = int(stream.rate or 44100)
                    resampler = av.AudioResampler(format="fltp", layout="stereo", rate=target_rate)
                    chunks = []
                    for frame in container.decode(stream):
                        for resampled in resampler.resample(frame):
                            arr = resampled.to_ndarray()  # shape: (channels, samples)
                            chunks.append(arr.T)
                    if not chunks:
                        raise sf_err
                    data = np.concatenate(chunks, axis=0).astype(np.float32)
                    return data, target_rate
            except Exception:
                raise sf_err

    @classmethod
    def play_music_with_ducking(
        cls,
        file_path: str,
        duck_gain: float = None,
        normal_gain: float = None,
        on_start=None,
        on_finish=None
    ):
        """
        Streams a music track through a dedicated OutputStream so it can play
        simultaneously with Calypso's TTS voice, smoothly ducking volume when she speaks.
        """
        cls._music_stop_event.set()
        cls._music_pause_event.clear()
        with cls._music_lock:
            cls._music_stop_event.clear()
            cls._music_pause_event.clear()
            cls.last_music_completed_naturally = False
            cls._music_position_sec = 0.0
            cls._music_duration_sec = 0.0
            try:
                data, fs = cls._decode_audio_file(str(file_path))
                channels = data.shape[1]
                total_frames = data.shape[0]
                cls._music_duration_sec = total_frames / float(fs) if fs > 0 else 0.0

                if on_start:
                    on_start()

                block_size = 1024
                eff_normal = float(normal_gain) if normal_gain is not None else cls.music_volume
                eff_duck = float(duck_gain) if duck_gain is not None else min(0.18, eff_normal * 0.25)
                current_gain = eff_duck if cls.is_speaking_event.is_set() else eff_normal

                with sd.OutputStream(samplerate=int(fs), channels=channels, dtype="float32") as stream:
                    idx = 0
                    while idx < total_frames and not cls._music_stop_event.is_set():
                        if cls._music_pause_event.is_set():
                            time.sleep(0.05)
                            continue

                        cls._music_position_sec = idx / float(fs) if fs > 0 else 0.0
                        eff_normal = float(normal_gain) if normal_gain is not None else cls.music_volume
                        eff_duck = float(duck_gain) if duck_gain is not None else min(0.18, eff_normal * 0.25)
                        target_gain = eff_duck if cls.is_speaking_event.is_set() else eff_normal
                        # Smooth envelope transition (attack/release) to avoid clicks
                        if abs(current_gain - target_gain) > 0.005:
                            step = 0.04 if target_gain < current_gain else 0.015
                            if target_gain < current_gain:
                                current_gain = max(target_gain, current_gain - step)
                            else:
                                current_gain = min(target_gain, current_gain + step)
                        else:
                            current_gain = target_gain

                        chunk = data[idx:idx + block_size] * current_gain
                        if not cls.is_speaking_event.is_set():
                            cls.push_vis_samples(chunk, samplerate=int(fs), source="music")
                        stream.write(chunk)
                        idx += block_size

                    if idx >= total_frames and not cls._music_stop_event.is_set():
                        cls.last_music_completed_naturally = True
            except Exception as e:
                logger.error(f"[AudioEngine] Music stream playback error: {e}")
            finally:
                if not cls.is_speaking_event.is_set():
                    cls.clear_vis_samples()
                if on_finish:
                    on_finish()

    def calibrate(self):
        with self.microphone as source:
            print("[AudioEngine] Calibrating microphone...")
            self.recognizer.adjust_for_ambient_noise(source, duration=1)
            print("[AudioEngine] Calibration complete.")

    def listen_and_record(self, threshold=500, silence_limit=2.0, timeout=5):
        with self.microphone as source:
            self.recognizer.energy_threshold = threshold
            self.recognizer.pause_threshold = silence_limit
            try:
                return self.recognizer.listen(source, timeout=timeout, phrase_time_limit=10)
            except Exception:
                return None

    def clean_text_for_speech(self, text: str) -> str:
        """Strips markdown, brackets, and asterisk actions (*smiles warmly*) before TTS synthesis."""
        cleaned = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
        cleaned = re.sub(r'\[[A-Z_]+(?::.*?)?\]', '', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r'\*.*?\*', '', cleaned)
        cleaned = re.sub(r'[_~`#]', '', cleaned)
        cleaned = " ".join(cleaned.split())
        return cleaned.strip()

    def speak(self, text, emotion="Neutral", voice_override: str = None, speed: float = 1.0, enqueue: bool = False):
        """
        Performs non-blocking Kokoro synthesis (guarded by gpu_vram_lock) and dedicated stream playback.
        When enqueue=True (e.g., Guest Philosopher speaking right after Calypso), waits for the current
        speech item to finish rather than interrupting it.
        """
        speech_text = self.clean_text_for_speech(text)
        if not speech_text:
            if self._speech_queue.empty():
                AudioEngine.tts_synthesis_done_event.set()
                AudioEngine.tts_playback_done_event.set()
            return

        if not enqueue:
            self.stop_playback()

        AudioEngine.tts_synthesis_done_event.clear()
        AudioEngine.tts_playback_done_event.clear()
        self._speech_queue.put((speech_text, voice_override, float(speed or 1.0)))

    def _resolve_kokoro_voice(self, requested_voice: str = None) -> str:
        """Resolves requested voice or falls back cleanly to a cached local voice if offline."""
        target = (requested_voice or self.voice_name or "af_heart").strip()
        try:
            self.tts_pipeline.load_voice(target)
            return target
        except Exception as e:
            logger.debug(f"[AudioEngine] Voice '{target}' unavailable offline ({e}); falling back.")
            for fallback in ("bf_isabella", "af_bella", self.voice_name, "af_heart"):
                if fallback:
                    try:
                        self.tts_pipeline.load_voice(fallback)
                        return fallback
                    except Exception:
                        continue
            return self.voice_name

    def _speech_queue_loop(self):
        """Processes queued TTS items sequentially so multi-speaker turns never cut each other off."""
        while True:
            try:
                speech_text, voice_override, speed = self._speech_queue.get()
            except Exception:
                continue

            with self._playback_lock:
                self._voice_stop_event.clear()
                full_audio = None
                try:
                    active_voice = self._resolve_kokoro_voice(voice_override)
                    # 1. GPU synthesis phase (guarded by gpu_vram_lock so it never collides with MusicGen/SDXL)
                    with gpu_vram_lock:
                        with torch.inference_mode():
                            audio_chunks = [
                                np.asarray(audio, dtype=np.float32)
                                for _, _, audio in self.tts_pipeline(speech_text, voice=active_voice, speed=speed)
                            ]
                        if audio_chunks:
                            full_audio = np.concatenate(audio_chunks)
                except Exception as e:
                    logger.error(f"[AudioEngine] TTS Synthesis exception: {e}")
                finally:
                    if self._speech_queue.empty():
                        AudioEngine.tts_synthesis_done_event.set()

                # 2. Dedicated OutputStream playback phase (ducks background music instead of killing it)
                if full_audio is not None and full_audio.size > 0 and not self._voice_stop_event.is_set():
                    try:
                        AudioEngine.is_speaking_event.set()
                        attenuated = (full_audio * self.master_volume).astype(np.float32)
                        if attenuated.ndim == 1:
                            attenuated = attenuated[:, np.newaxis]

                        block_size = 1024
                        total_frames = attenuated.shape[0]
                        with sd.OutputStream(samplerate=24000, channels=1, dtype="float32") as stream:
                            idx = 0
                            while idx < total_frames and not self._voice_stop_event.is_set():
                                chunk = attenuated[idx:idx + block_size]
                                AudioEngine.push_vis_samples(chunk, samplerate=24000, source="voice")
                                stream.write(chunk)
                                idx += block_size
                    except Exception as e:
                        logger.error(f"[AudioEngine] TTS Playback exception: {e}")
                    finally:
                        AudioEngine.clear_vis_samples()
                        if self._speech_queue.empty():
                            AudioEngine.is_speaking_event.clear()
                            AudioEngine.tts_playback_done_event.set()
                else:
                    AudioEngine.clear_vis_samples()
                    if self._speech_queue.empty():
                        AudioEngine.is_speaking_event.clear()
                        AudioEngine.tts_playback_done_event.set()

            try:
                self._speech_queue.task_done()
            except Exception:
                pass

    def transcribe(self, audio_data):
        import uuid
        workspace = getattr(config, 'WORKSPACE_DIR', config.BASE_DIR)
        temp_filename = workspace / f"temp_transcribe_{uuid.uuid4().hex}.wav"
        try:
            with open(temp_filename, "wb") as f:
                f.write(audio_data.get_wav_data())
            with gpu_vram_lock:
                segments, _ = self.whisper_model.transcribe(str(temp_filename), beam_size=5)
                return " ".join([s.text for s in segments])
        finally:
            if temp_filename.exists():
                try:
                    temp_filename.unlink()
                except Exception:
                    pass

