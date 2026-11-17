# modules/music_processor.py

import gc
import json
import logging
import re
import threading
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

import soundfile as sf
import torch

from modules.config import config
from modules.gpu_lock import gpu_vram_lock

logger = logging.getLogger("EmotionEngine.MusicProcessor")


class CalypsoMusicProcessor:
    """
    Autonomous and conversational acoustic generation engine for Calypso.
    Translates neurochemical states, relational affinity themes, and real-time
    cardiac telemetry (EKG BPM) into expressive solo acoustic compositions
    using Hugging Face MusicGen.
    
    Adheres strictly to the dynamic VRAM orchestration pattern (Ollama eviction,
    isolated GPU loading, aggressive cache clearing, and background LLM pre-warming).
    """

    def __init__(self, character_name: str = "Calypso"):
        self.character_name = character_name
        self.output_dir = getattr(config, "MUSIC_OUTPUT_DIR", config.OUTPUT_DIR / "music")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.models_dir = getattr(config, "AUDIOCRAFT_MODELS_DIR", config.BASE_DIR / "audiocraft_models")
        self.models_dir.mkdir(parents=True, exist_ok=True)

        self.parser_regex = re.compile(
            r'\[(?:MUSIC_PROMPT|MUSIC):\s*(.*?)(?:\]|$)', re.IGNORECASE | re.DOTALL
        )

        if torch.cuda.is_available():
            self.device = "cuda:0"
        else:
            self.device = "cpu"

        # Relational affinity & emotional tier acoustic texture mapping
        # Prioritizes organic solo instruments, rich room acoustics, and chamber intimacy
        # Relational affinity & emotional tier acoustic texture mapping
        # Grounded in Thomas Newman's iconic, gossamer, and percussive palette
        self.theme_texture_matrix = {
            "romance": "Minimalist film score, intimate solo felt piano playing slow repeating patterns, soft wooden pedal noise, warm close-mic room acoustics, melancholic, nostalgic",
            "sarcasm": "Quirky percussive cinematic score, syncopated marimba and staccato pizzicato strings, eccentric rhythm, dry room, subtle dark comedy undertone",
            "wonder": "Ethereal solo acoustic harp with shimmering ambient delays, crystalline acoustic space, delicate celestial harmonics, slow-building suspended chords",
            "abyss": "Mourful solo acoustic cello with heavy bow friction, hollow somber undertones, low processed acoustic drone, slow reflective pauses",
            "autonomy": "Hypnotic rhythmic ostinato, echoing metal bowls, light marimba accents, plucked acoustic instruments, low processed bass flute drone",
            "honesty": "Unadorned felted upright acoustic piano, soft hammer striking felt, fragile touching melody, raw intimate silence, spacious production",
            "annoyance": "Tense solo electric violin, frantic textured bowing, sharp urgent syncopation, dry close-mic tracking, minimalist friction",
            "conformity": "Distant mechanical music box lullaby, delicate antique chime, nostalgic bittersweet tone, slow fading notes, vintage warmth",
            "baseline": "Calm, contemplative solo classical acoustic guitar, warm natural timbre, gentle steady pace, spacious room reflections"
        }


        self.tier_fallback_matrix = {
            "intimate": "Intimate fingerstyle acoustic guitar, soft felted piano layers, warm close-mic room acoustics, tender yearning rubato, gossamer quality",
            "somber": "Slow mournful solo acoustic cello, deeply sorrowful bow friction, low resonant acoustic pedal drone, hollow somber undertones",
            "sad": "Sparse melancholy solo upright piano with felt dampers, slow reflective pauses, intimate wooden pedal noise",
            "thoughtful": "Minimalist solo felted upright acoustic piano, contemplative pace, soft ambient space, repeating hypnotic micro-melodies",
            "wonder": "Ethereal solo acoustic harp, shimmering delays, expansive celestial atmosphere, delicate acoustic space",
            "warm": "Warm fingerstyle acoustic guitar and soft wooden timbre, cozy close-mic presence, gentle harmonic foundation",
            "happy": "Uplifting syncopated marimba ostinato, light playful kalimba chimes, joyful lilting rhythm, crisp room acoustics",
            "excited": "Spirited acoustic guitar strumming with buoyant kinetic drive, bright melodic leaps, fast tuned percussion patterns",
            "eutierria": "Gentle acoustic singing bowls, ethereal acoustic harp, serene sustained resonance, breath-like stillness, spacious ambient reflections",
            "enlightened": "Transcendent solo acoustic harp, soft bowed string harmonics, lucid crystalline clarity, low resonant synth pedal bass",
            "focused": "Hypnotic percussive rhythmic ostinato, marimbas, echoing metal bowls, steady rhythmic focus, clear spatial panning",
            "furious": "High-tension solo electric violin, frantic textured bowing, raw overdrive harmonics, sharp urgent syncopation, dark cinematic drive",
            "sleepy": "Distant mechanical music box lullaby, delicate antique tone, soft fading notes, quiet ambient hiss",
            "baseline": "Calm, contemplative solo classical acoustic guitar, warm natural timbre, gentle steady pace"
        }

        # Dynamic Classifier-Free Guidance (CFG) per theme/tier:
        # Lower CFG (2.5-3.0) allows natural room decay, pedal noise, and bow friction.
        # Higher CFG (4.0-5.0) enforces tight rhythmic syncopation and ostinato lock.
        self.guidance_mapping = {
            "honesty": 2.5,     # Ultra-loose, highly organic felt piano
            "romance": 3.0,     # Room for delicate string/guitar decay
            "intimate": 3.0,
            "somber": 3.0,      # Allows cello bow friction artifacts
            "abyss": 3.0,
            "sad": 3.0,
            "sleepy": 3.0,
            "thoughtful": 3.2,
            "baseline": 3.5,    # Default safe zone
            "warm": 3.5,
            "wonder": 3.5,
            "eutierria": 3.5,
            "enlightened": 3.5,
            "conformity": 3.5,
            "sarcasm": 4.0,     # Crisp pizzicato and marimba articulation
            "autonomy": 4.0,    # Tight percussive tracking for ostinatos
            "focused": 4.0,
            "happy": 4.0,
            "excited": 4.2,
            "annoyance": 4.5,   # Focused tension
            "furious": 5.0      # Aggressive tracking to stay coherent
        }
        self._last_resolved_guidance: float = 3.5

    # -------------------------------------------------------------------------
    # PROMPT SYNTHESIS & TELEMETRY MAPPING
    # -------------------------------------------------------------------------
    def resolve_guidance_scale(self, current_tier: str = "baseline", active_theme: str = "") -> float:
        """Resolves the optimal CFG scale for the active relational theme or emotional tier."""
        theme_key = active_theme.strip().lower() if active_theme else ""
        tier_key = current_tier.strip().lower() if current_tier else "baseline"
        if theme_key in self.guidance_mapping:
            return self.guidance_mapping[theme_key]
        if tier_key in self.guidance_mapping:
            return self.guidance_mapping[tier_key]
        return float(getattr(config, "MUSICGEN_GUIDANCE_SCALE", 3.5))

    def parse_and_build_prompt(
        self,
        assistant_raw_text: str,
        current_tier: str = "baseline",
        active_theme: str = "",
        ekg_monitor=None,
        default_bpm: int = 72,
        include_intent_in_prompt: bool = False
    ) -> Tuple[str, Optional[str], int, str]:
        """
        Extracts conversational [MUSIC_PROMPT: ...] tags, samples real-time EKG telemetry,
        and constructs a clean acoustic MusicGen prompt aligned with her state.
        """
        match = self.parser_regex.search(assistant_raw_text)
        clean_text = self.parser_regex.sub('', assistant_raw_text).strip()

        if not match:
            return clean_text, None, default_bpm, ""

        raw_music_intent = match.group(1).strip()

        # Extract live cardiac pulse from EKG monitor
        bpm = default_bpm
        if ekg_monitor:
            if hasattr(ekg_monitor, 'current_bpm') and ekg_monitor.current_bpm:
                bpm = int(round(ekg_monitor.current_bpm))
            elif hasattr(ekg_monitor, 'target_bpm') and ekg_monitor.target_bpm:
                bpm = int(round(ekg_monitor.target_bpm))

        # Clamp BPM to musical range
        bpm = max(45, min(160, bpm))
        self._last_resolved_guidance = self.resolve_guidance_scale(current_tier, active_theme)

        # Select pure acoustic texture without narrative clutter
        style_desc = self._resolve_acoustic_style(current_tier, active_theme)
        if include_intent_in_prompt and raw_music_intent:
            final_prompt = f"{style_desc}, {bpm} BPM, {raw_music_intent}"
        else:
            final_prompt = f"{style_desc}, {bpm} BPM, instrumental only, high fidelity acoustic recording"

        return clean_text, final_prompt, bpm, style_desc

    def construct_prompt(
        self,
        title: str,
        intent_description: str,
        current_tier: str,
        active_theme: str = "",
        bpm: int = 72,
        include_intent_in_prompt: bool = False
    ) -> Tuple[str, str]:
        """
        Builds a structured prompt for autonomous tasks or direct elicitation.
        By default, keeps the MusicGen T5 prompt strictly technical/acoustic (omitting
        poetic titles and emotional prose that degrade MusicGen's audio quality),
        while preserving them for UI cards and memory logs.
        """
        bpm = max(45, min(160, bpm))
        self._last_resolved_guidance = self.resolve_guidance_scale(current_tier, active_theme)
        style_desc = self._resolve_acoustic_style(current_tier, active_theme)
        if include_intent_in_prompt and intent_description:
            final_prompt = f"{style_desc}, {bpm} BPM, {intent_description}"
        else:
            final_prompt = f"{style_desc}, {bpm} BPM, instrumental only, high fidelity acoustic recording"
        return final_prompt, style_desc

    def _resolve_acoustic_style(self, current_tier: str, active_theme: str = "") -> str:
        theme_key = active_theme.strip().lower() if active_theme else ""
        tier_key = current_tier.strip().lower() if current_tier else "baseline"

        if theme_key in self.theme_texture_matrix:
            return self.theme_texture_matrix[theme_key]
        if tier_key in self.tier_fallback_matrix:
            return self.tier_fallback_matrix[tier_key]
        return self.theme_texture_matrix["baseline"]

    # -------------------------------------------------------------------------
    # DYNAMIC VRAM ORCHESTRATION (OLLAMA EVICTION & RESTORATION)
    # -------------------------------------------------------------------------
    def _unload_ollama(self) -> bool:
        """Evicts Ollama LLM from VRAM via keep_alive: 0 payload."""
        logger.info("[MusicGen] Evicting LLM from VRAM via Ollama API...")
        try:
            base_url = str(config.OLLAMA_URL).rstrip("/")
            root_url = base_url.split("/api/")[0] if "/api/" in base_url else base_url
            generate_url = f"{root_url}/api/generate"

            payload = json.dumps({"model": config.MODEL_NAME, "keep_alive": 0}).encode("utf-8")
            req = urllib.request.Request(
                generate_url, data=payload, headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=10):
                pass

            time.sleep(0.8)
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

            logger.info("[MusicGen] VRAM successfully cleared of LLM.")
            return True
        except Exception as e:
            logger.warning(f"[MusicGen] Could not evict Ollama (proceeding anyway): {e}")
            return False

    def _warmup_ollama_async(self):
        """Pre-warms Ollama LLM back into VRAM in the background."""
        def _warm():
            try:
                logger.info("[MusicGen] Background pre-warming LLM into VRAM...")
                base_url = str(config.OLLAMA_URL).rstrip("/")
                root_url = base_url.split("/api/")[0] if "/api/" in base_url else base_url
                chat_url = f"{root_url}/api/chat"
                payload = json.dumps({
                    "model": config.MODEL_NAME,
                    "messages": [],
                    "keep_alive": "10m"
                }).encode("utf-8")

                req = urllib.request.Request(
                    chat_url, data=payload, headers={"Content-Type": "application/json"}
                )
                with urllib.request.urlopen(req, timeout=30):
                    pass
                logger.info("[MusicGen] LLM successfully reloaded and warm in VRAM.")
            except Exception as e:
                logger.debug(f"[MusicGen] Background warmup notice: {e}")

        threading.Thread(target=_warm, daemon=True).start()

    # -------------------------------------------------------------------------
    # MODEL RESOLUTION & READINESS (AUDIOCRAFT / MUSICGEN)
    # -------------------------------------------------------------------------
    @staticmethod
    def _is_valid_hf_model_dir(directory: Path) -> bool:
        """Checks whether a directory contains the required Hugging Face MusicGen config and processor files."""
        return (
            directory.is_dir()
            and (directory / "config.json").exists()
            and (directory / "preprocessor_config.json").exists()
        )

    def _resolve_model_path(self, model_name: Optional[str] = None) -> Optional[str]:
        """
        Resolves the user-selected AudioCraft / MusicGen model from audiocraft_models/
        or a user-configured path/Hugging Face repository ID.
        Does NOT default to downloading licensed models unless explicitly configured by the user.
        """
        if not getattr(config, "AUDIOCRAFT_ENABLED", True):
            return None

        self.models_dir = getattr(config, "AUDIOCRAFT_MODELS_DIR", config.BASE_DIR / "audiocraft_models")
        self.models_dir.mkdir(parents=True, exist_ok=True)

        target = str(model_name or getattr(config, "MUSICGEN_MODEL", "")).strip()
        if target and target.lower() != "none":
            candidate = self.models_dir / target
            if candidate.exists():
                # If the user selected a weight file (e.g. model.safetensors), resolve to its parent directory
                if candidate.is_file():
                    return str(candidate.parent)
                return str(candidate)
            direct = Path(target)
            if direct.exists():
                if direct.is_file():
                    return str(direct.parent)
                return str(direct)
            # User explicitly specified a Hugging Face repo ID (e.g. facebook/musicgen-medium)
            return target

        # If no explicit model name is set:
        # 1. Check if audiocraft_models/ root directory itself is a complete HF model folder
        if self._is_valid_hf_model_dir(self.models_dir):
            logger.info(f"[AudioCraft] Auto-detected local model in '{self.models_dir.name}/'")
            return str(self.models_dir)

        # 2. Look for a local AudioCraft model subfolder inside audiocraft_models/
        for sub in sorted(self.models_dir.iterdir()):
            if self._is_valid_hf_model_dir(sub):
                logger.info(f"[AudioCraft] Auto-detected local model directory: '{sub.name}'")
                return str(sub)

        return None

    def is_ready(self) -> bool:
        """Returns True if AudioCraft is enabled and a valid model is configured or present locally."""
        return bool(self._resolve_model_path())

    # -------------------------------------------------------------------------
    # AUDIO TRACK GENERATION (AUDIOCRAFT / MUSICGEN)
    # -------------------------------------------------------------------------
    def generate_isolated_track(
        self,
        prompt_text: str,
        bpm: int = 72,
        duration: Optional[int] = None,
        model_name: Optional[str] = None,
        guidance_scale: Optional[float] = None
    ) -> Optional[Path]:
        """
        Executes a memory-safe, isolated AudioCraft / MusicGen inference lifecycle.
        Guarded by gpu_vram_lock to avoid concurrent execution with SDXL.
        Strictly offline by default unless AUDIOCRAFT_ALLOW_ONLINE is explicitly enabled.
        """
        from transformers import AutoProcessor, MusicgenForConditionalGeneration

        if not getattr(config, "AUDIOCRAFT_ENABLED", True):
            logger.info("[AudioCraft] Pipeline is disabled in settings. Skipping track generation.")
            return None

        target_model = self._resolve_model_path(model_name) or "facebook/musicgen-medium"
        if not target_model:
            logger.warning(
                "[AudioCraft] No model configured or found in audiocraft_models/. "
                "Please place a complete MusicGen model folder in audiocraft_models/ or select one in Settings."
            )
            return None

        allow_online = bool(getattr(config, "AUDIOCRAFT_ALLOW_ONLINE", False))
        local_only = not allow_online

        # Pre-flight validation when target_model is a local directory path
        target_path = Path(target_model)
        if target_path.exists() and target_path.is_dir():
            if not self._is_valid_hf_model_dir(target_path):
                logger.error(
                    f"[AudioCraft] Local directory '{target_path}' is missing required Hugging Face "
                    "configuration/tokenizer files (config.json, preprocessor_config.json, spiece.model, etc.). "
                    "A standalone .safetensors file requires its companion JSON/tokenizer files in the same folder."
                )
                return None

        duration_sec = int(duration if duration is not None else getattr(config, "MUSICGEN_DURATION", 30))
        if guidance_scale is not None:
            resolved_cfg = float(guidance_scale)
        elif hasattr(self, "_last_resolved_guidance") and self._last_resolved_guidance:
            resolved_cfg = float(self._last_resolved_guidance)
        else:
            resolved_cfg = 3.5

        # Hardcoded studio-calibrated MusicGen sampling parameters:
        # Prevents user preference drift from corrupting the 4-codebook RVQ delay pattern.
        guidance_scale = resolved_cfg
        top_k = 250
        temperature = 1.0

        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_seed = int(time.time() * 1000) % 10000
        filename = f"resonance_{bpm}bpm_{timestamp_str}_{safe_seed}.wav"
        target_file = self.output_dir / filename

        # 50 audio frames per second
        max_tokens = max(100, int(duration_sec * 50))

        logger.info(
            f"🎶 [AudioCraft] Preparing {duration_sec}s composition at {bpm} BPM with '{target_model}' "
            f"(dtype=float32, CFG={guidance_scale}, Top-K={top_k}, Temp={temperature}, Offline={local_only})..."
        )

        with gpu_vram_lock:
            model = None
            processor = None
            start_time = time.time()
            try:
                # 1. Clear LLM from VRAM
                self._unload_ollama()

                logger.info(
                    f"[AudioCraft] Loading '{target_model}' on {self.device} in float32 "
                    f"(local_files_only={local_only})..."
                )
                processor = AutoProcessor.from_pretrained(
                    target_model,
                    local_files_only=local_only
                )
                # Full float32 precision (~8.3 GB VRAM on 16 GB GPU) prevents fp16 rounding drift
                # across the 48-layer decoder and 4 delayed EnCodec RVQ codebooks.
                model = MusicgenForConditionalGeneration.from_pretrained(
                    target_model,
                    torch_dtype=torch.float32,
                    low_cpu_mem_usage=True,
                    local_files_only=local_only
                ).to(self.device)

                logger.info(f"[AudioCraft] Generating audio: \"{prompt_text}\"")
                inputs = processor(
                    text=[prompt_text],
                    padding=True,
                    return_tensors="pt"
                ).to(self.device)

                gen_kwargs = {
                    "max_new_tokens": max_tokens,
                    "do_sample": True,
                    "guidance_scale": guidance_scale,
                    "top_k": top_k,
                    "temperature": temperature,
                }

                with torch.inference_mode():
                    audio_values = model.generate(
                        **inputs,
                        **gen_kwargs
                    )

                # Audio shape: (batch_size, num_channels, sequence_length)
                sampling_rate = model.config.audio_encoder.sampling_rate
                audio_data = audio_values[0, 0].cpu().to(torch.float32).numpy()
                del audio_values, inputs

                # Clean NaN/Inf and normalize hot peaks so 16-bit PCM never clips
                import numpy as np
                audio_data = np.nan_to_num(audio_data, nan=0.0, posinf=0.0, neginf=0.0)
                peak = float(np.max(np.abs(audio_data))) if audio_data.size > 0 else 0.0
                if peak > 0.95:
                    audio_data = audio_data * (0.95 / peak)

                # Write out 32kHz WAV file
                sf.write(str(target_file), audio_data, sampling_rate, subtype="PCM_16")
                logger.info(f"✨ [MusicGen] Successfully rendered track: {target_file.name} ({time.time() - start_time:.2f}s)")
                return target_file

            except Exception as e:
                logger.error(f"[MusicGen] Audio pipeline generation failed: {e}", exc_info=True)
                return None

            finally:
                if model is not None:
                    del model
                if processor is not None:
                    del processor
                gc.collect()
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()

                logger.info("[MusicGen] Active eviction complete. VRAM handed back to conversational layers.")
                self._warmup_ollama_async()


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    parser = argparse.ArgumentParser(
        description="Standalone CLI harness for testing CalypsoMusicProcessor prompts and CFG settings."
    )
    parser.add_argument("--theme", type=str, default="", help="Relational theme (e.g. romance, sarcasm, wonder, autonomy, honesty)")
    parser.add_argument("--tier", type=str, default="baseline", help="Emotional tier fallback (e.g. intimate, somber, thoughtful)")
    parser.add_argument("--bpm", type=int, default=72, help="Target tempo in BPM (45-160)")
    parser.add_argument("--duration", type=int, default=15, help="Track duration in seconds (default: 15s for fast auditioning)")
    parser.add_argument("--cfg", type=float, default=None, help="Override guidance_scale (CFG)")
    parser.add_argument("--prompt", type=str, default=None, help="Raw custom prompt override (bypasses theme/tier matrix)")
    parser.add_argument("--dry-run", action="store_true", help="Print the resolved MusicGen prompt and CFG without rendering audio")
    args = parser.parse_args()

    proc = CalypsoMusicProcessor()
    if args.prompt:
        final_prompt = args.prompt
        resolved_cfg = args.cfg if args.cfg is not None else 3.5
    else:
        final_prompt, style_desc = proc.construct_prompt(
            title="Test Audition",
            intent_description="",
            current_tier=args.tier,
            active_theme=args.theme,
            bpm=args.bpm
        )
        resolved_cfg = args.cfg if args.cfg is not None else proc._last_resolved_guidance

    print(f"\n--- MusicGen Prompt Audition ---")
    print(f"Theme / Tier : {args.theme or '(none)'} / {args.tier}")
    print(f"BPM          : {args.bpm}")
    print(f"Guidance CFG : {resolved_cfg}")
    print(f"Final Prompt : \"{final_prompt}\"\n")

    if not args.dry_run:
        out = proc.generate_isolated_track(
            prompt_text=final_prompt,
            bpm=args.bpm,
            duration=args.duration,
            guidance_scale=resolved_cfg
        )
        print(f"Rendered File: {out}")

