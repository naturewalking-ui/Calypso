# modules/music_manager.py

import ctypes
import json
import logging
import os
import random
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np
import soundfile as sf

from modules.audio import AudioEngine
from modules.config import config
from modules.settings_manager import settings_manager

try:
    import syncedlyrics
    _HAS_SYNCEDLYRICS = True
except ImportError:
    syncedlyrics = None
    _HAS_SYNCEDLYRICS = False

try:
    from tinytag import TinyTag
    _HAS_TINYTAG = True
except ImportError:
    TinyTag = None
    _HAS_TINYTAG = False

try:
    import av
    _HAS_AV = True
except ImportError:
    av = None
    _HAS_AV = False

logger = logging.getLogger("EmotionEngine.MusicManager")


def resolve_system_music_dir() -> Path:
    """
    Resolves the current user's OS Music directory across Linux, Windows, and macOS
    (used as the initial browsing directory when selecting a music library folder).
    """
    home = Path.home()

    if sys.platform == "win32":
        try:
            class GUID(ctypes.Structure):
                _fields_ = [
                    ("Data1", ctypes.c_ulong),
                    ("Data2", ctypes.c_ushort),
                    ("Data3", ctypes.c_ushort),
                    ("Data4", ctypes.c_ubyte * 8),
                ]

            # FOLDERID_Music = {4BD8D571-6D19-48D3-BE97-422220080E43}
            folderid_music = GUID(
                0x4BD8D571,
                0x6D19,
                0x48D3,
                (ctypes.c_ubyte * 8)(0xBE, 0x97, 0x42, 0x22, 0x20, 0x08, 0x0E, 0x43),
            )
            path_ptr = ctypes.c_wchar_p()
            res = ctypes.windll.shell32.SHGetKnownFolderPath(
                ctypes.byref(folderid_music), 0, None, ctypes.byref(path_ptr)
            )
            if res == 0 and path_ptr.value:
                win_music = Path(path_ptr.value)
                ctypes.windll.ole32.CoTaskMemFree(path_ptr)
                return win_music
        except Exception as e:
            logger.debug(f"[MusicEngine] Windows KnownFolder lookup fallback: {e}")

        user_profile = os.environ.get("USERPROFILE")
        if user_profile:
            return Path(user_profile) / "Music"
        return home / "Music"

    # Linux / POSIX XDG_MUSIC_DIR discovery
    env_xdg = os.environ.get("XDG_MUSIC_DIR", "").strip()
    if env_xdg:
        candidate = Path(os.path.expandvars(os.path.expanduser(env_xdg)))
        if candidate.resolve() != home.resolve():
            return candidate

    xdg_config = home / ".config" / "user-dirs.dirs"
    try:
        if xdg_config.exists():
            content = xdg_config.read_text(encoding="utf-8", errors="ignore")
            match = re.search(r'^\s*XDG_MUSIC_DIR\s*=\s*"([^"]+)"', content, flags=re.MULTILINE)
            if match:
                raw_path = match.group(1)
                raw_path = raw_path.replace("$HOME", str(home)).replace("${HOME}", str(home))
                candidate = Path(os.path.expandvars(os.path.expanduser(raw_path)))
                if candidate.resolve() != home.resolve():
                    return candidate
    except Exception as e:
        logger.debug(f"[MusicEngine] Could not read ~/.config/user-dirs.dirs: {e}")

    return home / "Music"


# Target (energy, brightness) in [0.0, 1.0] + semantic anchor phrase for each emotional tier
MOOD_ACOUSTIC_PROFILES: Dict[str, Dict] = {
    "eutierria": {
        "energy": 0.30,
        "brightness": 0.35,
        "anchor": "serene peaceful ambient acoustic harmony gentle atmospheric resonance calm"
    },
    "harmony": {
        "energy": 0.35,
        "brightness": 0.40,
        "anchor": "warm peaceful harmony melodic acoustic ambient mellow companionship"
    },
    "enlightened": {
        "energy": 0.32,
        "brightness": 0.45,
        "anchor": "transcendental ethereal ambient luminous serene instrumental"
    },
    "wonder": {
        "energy": 0.42,
        "brightness": 0.55,
        "anchor": "cosmic wonder ethereal expansive progressive atmospheric dream"
    },
    "intimate": {
        "energy": 0.28,
        "brightness": 0.32,
        "anchor": "intimate tender romantic slow acoustic soft love warm"
    },
    "warm": {
        "energy": 0.45,
        "brightness": 0.45,
        "anchor": "warm cozy acoustic soulful folk classic groove comforting"
    },
    "nostalgic": {
        "energy": 0.34,
        "brightness": 0.35,
        "anchor": "nostalgic bittersweet retro classic memory acoustic ballad"
    },
    "nostalgia": {
        "energy": 0.34,
        "brightness": 0.35,
        "anchor": "nostalgic bittersweet retro classic memory acoustic ballad"
    },
    "thoughtful": {
        "energy": 0.28,
        "brightness": 0.35,
        "anchor": "contemplative piano instrumental minimalist reflective study quiet"
    },
    "focused": {
        "energy": 0.48,
        "brightness": 0.45,
        "anchor": "focused rhythmic synth electronic instrumental steady flow"
    },
    "neutral": {
        "energy": 0.42,
        "brightness": 0.42,
        "anchor": "relaxed balanced chill mellow instrumental steady"
    },
    "baseline": {
        "energy": 0.42,
        "brightness": 0.42,
        "anchor": "relaxed balanced chill mellow instrumental steady"
    },
    "somber": {
        "energy": 0.22,
        "brightness": 0.25,
        "anchor": "somber dark melancholic slowminor moody heavy atmospheric"
    },
    "sad": {
        "energy": 0.20,
        "brightness": 0.25,
        "anchor": "sad melancholy slow heartbreak acoustic piano quiet sorrow"
    },
    "sleepy": {
        "energy": 0.14,
        "brightness": 0.18,
        "anchor": "sleepy lullaby ambient drone quiet night soft rest"
    },
    "happy": {
        "energy": 0.68,
        "brightness": 0.65,
        "anchor": "happy upbeat joyful bright energetic feelgood dance pop rock"
    },
    "excited": {
        "energy": 0.82,
        "brightness": 0.75,
        "anchor": "excited high energy fast driving anthem electronic rock upbeat"
    },
    "sarcastic": {
        "energy": 0.60,
        "brightness": 0.62,
        "anchor": "playful quirky funky upbeat witty indie alternative groove"
    },
}


class MusicEngine:
    VALID_EXTENSIONS = {".mp3", ".ogg", ".wav", ".flac"}

    def __init__(self, music_dir: Optional[str] = None, embedding_function=None):
        self.system_music_dir = resolve_system_music_dir()
        self._explicit_music_dir = Path(music_dir).expanduser() if music_dir else None
        self.ef = embedding_function
        self._mood_anchor_vecs: Dict[str, np.ndarray] = {}

        self.cache_file = (
            getattr(config, "MEMORY_DIR", config.BASE_DIR / "modules" / "emotion" / "memory")
            / "music_library_cache.json"
        )
        self.lyrics_cache_file = (
            getattr(config, "MEMORY_DIR", config.BASE_DIR / "modules" / "emotion" / "memory")
            / "music_lyrics_cache.json"
        )
        self._tag_cache: Dict[str, Dict] = {}
        self._lyrics_cache: Dict[str, Dict] = {}
        self._cached_tracks: Optional[List[Path]] = None
        self._cache_dirty = False
        self._lyrics_cache_dirty = False
        self._lock = threading.RLock()
        self._load_tag_cache()
        self._load_lyrics_cache()

        self.volume = float(settings_manager.get("music_volume", 0.60))
        AudioEngine.set_music_volume(self.volume)

        # Playback & Queue State
        self.current_track: Optional[Path] = None
        self.current_mood: str = "eutierria"
        self.queue: List[Path] = []
        self.queue_index: int = 0
        self.is_playing: bool = False
        self.is_paused: bool = False
        self._manual_stop_requested: bool = False
        self._playback_generation: int = 0
        self._status_listeners: List[Callable[[Dict], None]] = []
        self.on_stop_callback: Optional[Callable[[], None]] = None

        # Live Synced Lyrics & Musical Reverie Check-in State
        self.current_lyrics_raw: str = ""
        self.current_lyrics_plain: str = ""
        self.current_lyrics_synced: List[Tuple[float, str]] = []
        self.lyrics_status: str = "idle"  # "idle" | "searching" | "synced" | "plain" | "not_found"
        self.current_lyrics_query: str = ""
        self._pending_music_reverie_track: Optional[Path] = None
        self._pending_music_reverie_time: float = 0.0

        # External projectM Visualizer Process State
        self._visualizer_proc: Optional[subprocess.Popen] = None
        self._visualizer_lock = threading.Lock()

        self._init_mood_embeddings()

    def _init_mood_embeddings(self):
        """Pre-computes normalized sentence embeddings for mood anchor descriptions if ef is available."""
        if not self.ef:
            return
        try:
            moods = list(MOOD_ACOUSTIC_PROFILES.keys())
            phrases = [MOOD_ACOUSTIC_PROFILES[m]["anchor"] for m in moods]
            vecs = np.asarray(self.ef(phrases), dtype=np.float32)
            norms = np.linalg.norm(vecs, axis=1, keepdims=True)
            norms[norms == 0] = 1.0
            normed = vecs / norms
            for idx, m in enumerate(moods):
                self._mood_anchor_vecs[m] = normed[idx]
        except Exception as e:
            logger.debug(f"[MusicEngine] Mood embedding initialization skipped: {e}")

    # -------------------------------------------------------------------------
    # LIBRARY CONFIGURATION & LOCKOUT GATE
    # -------------------------------------------------------------------------
    def get_configured_music_dir(self) -> Optional[Path]:
        """
        Returns the user's explicitly configured music directory from settings
        (or explicit constructor path). Returns None if the user has not configured one.
        """
        if self._explicit_music_dir:
            return self._explicit_music_dir
        custom_dir = str(settings_manager.get("music_library_dir", "") or "").strip()
        if not custom_dir:
            return None
        return Path(custom_dir).expanduser()

    def has_configured_dir(self) -> bool:
        """Returns True if a user music directory has been set and exists on disk."""
        target = self.get_configured_music_dir()
        return bool(target and target.exists() and target.is_dir())

    def is_configured(self) -> bool:
        """
        Strict gate for the Harmony affinity event:
        Returns True only if the user has configured a music directory AND it contains >= 1 audio track.
        """
        if not self.has_configured_dir():
            return False
        tracks = self.scan_library()
        return len(tracks) > 0

    def set_music_dir(self, new_dir: str) -> int:
        """Updates the user's music_library_dir in settings and rescans the library."""
        cleaned = str(new_dir or "").strip()
        settings_manager.save({"music_library_dir": cleaned})
        self._explicit_music_dir = Path(cleaned).expanduser() if cleaned else None
        tracks = self.scan_library(force_refresh=True)
        return len(tracks)

    def get_library_roots(self) -> List[Path]:
        """Returns the active user-configured music directory (if configured)."""
        target = self.get_configured_music_dir()
        if target and target.exists() and target.is_dir():
            return [target]
        return []

    # -------------------------------------------------------------------------
    # CACHE & ZERO-CONFIG ACOUSTIC / METADATA INDEXING
    # -------------------------------------------------------------------------
    def _load_tag_cache(self):
        try:
            if self.cache_file.exists():
                with open(self.cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        self._tag_cache = data
        except Exception as e:
            logger.debug(f"[MusicEngine] Could not load tag cache: {e}")
            self._tag_cache = {}

    def _save_tag_cache(self):
        if not self._cache_dirty:
            return
        try:
            with self._lock:
                self.cache_file.parent.mkdir(parents=True, exist_ok=True)
                tmp_path = self.cache_file.with_suffix(".tmp")
                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(self._tag_cache, f, indent=2)
                tmp_path.replace(self.cache_file)
                self._cache_dirty = False
        except Exception as e:
            logger.debug(f"[MusicEngine] Could not save tag cache: {e}")

    def _load_lyrics_cache(self):
        try:
            if self.lyrics_cache_file.exists():
                with open(self.lyrics_cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        self._lyrics_cache = data
        except Exception as e:
            logger.debug(f"[MusicEngine] Could not load lyrics cache: {e}")
            self._lyrics_cache = {}

    def _save_lyrics_cache(self):
        if not self._lyrics_cache_dirty:
            return
        try:
            with self._lock:
                self.lyrics_cache_file.parent.mkdir(parents=True, exist_ok=True)
                tmp_path = self.lyrics_cache_file.with_suffix(".tmp")
                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(self._lyrics_cache, f, indent=2)
                tmp_path.replace(self.lyrics_cache_file)
                self._lyrics_cache_dirty = False
        except Exception as e:
            logger.debug(f"[MusicEngine] Could not save lyrics cache: {e}")

    def scan_library(self, force_refresh: bool = False) -> List[Path]:
        """Scans the user-configured music directory recursively for audio files."""
        with self._lock:
            if self._cached_tracks is not None and not force_refresh:
                return self._cached_tracks

            discovered: List[Path] = []
            seen_paths = set()

            for root in self.get_library_roots():
                try:
                    if not root.exists() or not root.is_dir():
                        continue
                    for dirpath, dirnames, filenames in os.walk(root):
                        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
                        for fname in filenames:
                            if fname.startswith("."):
                                continue
                            ext = os.path.splitext(fname)[1].lower()
                            if ext in self.VALID_EXTENSIONS:
                                full_path = Path(dirpath) / fname
                                key = str(full_path)
                                if key not in seen_paths:
                                    seen_paths.add(key)
                                    discovered.append(full_path)
                except PermissionError as pe:
                    logger.debug(f"[MusicEngine] Permission skipped scanning '{root}': {pe}")
                except Exception as e:
                    logger.warning(f"[MusicEngine] Error scanning '{root}': {e}")

            self._cached_tracks = sorted(discovered)
            return self._cached_tracks

    def _analyze_acoustic_features(self, file_path: Path) -> Tuple[float, float]:
        """
        Samples up to ~6 seconds from the middle of an audio file to estimate:
        - energy (normalized RMS loudness in [0.0, 1.0])
        - brightness (normalized zero-crossing rate in [0.0, 1.0])
        """
        try:
            with sf.SoundFile(str(file_path)) as f:
                total_frames = len(f)
                sr = int(f.samplerate or 44100)
                if total_frames <= 0:
                    return 0.42, 0.42
                slice_frames = min(total_frames, sr * 6)
                start_frame = max(0, (total_frames - slice_frames) // 2)
                f.seek(start_frame)
                samples = f.read(slice_frames, dtype="float32", always_2d=True)
                mono = np.mean(samples, axis=1)
        except Exception:
            if not _HAS_AV:
                return 0.42, 0.42
            try:
                with av.open(str(file_path)) as container:
                    if not container.streams.audio:
                        return 0.42, 0.42
                    stream = container.streams.audio[0]
                    chunks = []
                    max_samples = 44100 * 5
                    collected = 0
                    for frame in container.decode(stream):
                        arr = frame.to_ndarray().astype(np.float32)
                        if arr.ndim > 1:
                            arr = np.mean(arr, axis=0)
                        chunks.append(arr)
                        collected += arr.size
                        if collected >= max_samples:
                            break
                    if not chunks:
                        return 0.42, 0.42
                    mono = np.concatenate(chunks)
                    peak = np.max(np.abs(mono))
                    if peak > 1.5:
                        mono = mono / peak
            except Exception:
                return 0.42, 0.42

        if mono.size < 64:
            return 0.42, 0.42

        rms = float(np.sqrt(np.mean(np.square(mono))))
        # Typical music RMS spans ~0.03 (very quiet ambient) to ~0.28 (loud mastered pop/rock)
        energy = max(0.05, min(0.98, (rms - 0.02) / 0.24))

        signs = np.signbit(mono)
        zcr = float(np.mean(signs[1:] != signs[:-1]))
        # Typical ZCR spans ~0.015 (deep bass/warm acoustic) to ~0.16 (bright percussion/hi-hats)
        brightness = max(0.05, min(0.98, (zcr - 0.01) / 0.15))

        return round(energy, 3), round(brightness, 3)

    def get_track_metadata(self, file_path: Path, compute_acoustic: bool = True) -> Dict:
        """
        Extracts metadata tags (title, artist, album, genre, comment) and zero-config
        acoustic features (energy, brightness), backed by an mtime-aware JSON cache.
        """
        file_path = Path(file_path)
        key = str(file_path)
        mtime = 0.0
        try:
            mtime = round(file_path.stat().st_mtime, 2)
        except Exception:
            pass

        with self._lock:
            cached = self._tag_cache.get(key)
            if cached and cached.get("mtime") == mtime:
                if not compute_acoustic or ("energy" in cached and "brightness" in cached):
                    return cached

        meta: Dict = {
            "title": "",
            "artist": "",
            "album": "",
            "genre": "",
            "comment": "",
            "mtime": mtime,
        }

        extracted = False
        if _HAS_TINYTAG:
            try:
                tag = TinyTag.get(str(file_path))
                meta["title"] = str(tag.title or "").strip()
                meta["artist"] = str(tag.artist or "").strip()
                meta["album"] = str(tag.album or "").strip()
                meta["genre"] = str(tag.genre or "").strip()
                meta["comment"] = str(tag.comment or "").strip()
                extracted = True
            except Exception as e:
                logger.debug(f"[MusicEngine] TinyTag fallback for {file_path.name}: {e}")

        if not extracted and _HAS_AV:
            try:
                with av.open(str(file_path)) as container:
                    raw_tags = {}
                    if container.metadata:
                        for k, v in container.metadata.items():
                            raw_tags[k.lower()] = str(v).strip()
                    for stream in container.streams.audio:
                        if stream.metadata:
                            for k, v in stream.metadata.items():
                                raw_tags.setdefault(k.lower(), str(v).strip())

                    meta["title"] = raw_tags.get("title", "")
                    meta["artist"] = raw_tags.get("artist", "") or raw_tags.get("album_artist", "")
                    meta["album"] = raw_tags.get("album", "")
                    meta["genre"] = raw_tags.get("genre", "")
                    meta["comment"] = (
                        raw_tags.get("comment", "")
                        or raw_tags.get("description", "")
                        or raw_tags.get("lyrics", "")
                    )
            except Exception as e:
                logger.debug(f"[MusicEngine] Could not read container tags for {file_path.name}: {e}")

        if not meta["title"]:
            stem = file_path.stem.replace("_", " ").strip()
            if " - " in stem and not meta["artist"]:
                parts = stem.split(" - ", 1)
                meta["artist"] = parts[0].strip()
                meta["title"] = parts[1].strip()
            else:
                meta["title"] = stem

        searchable_parts = [
            meta["genre"],
            meta["comment"],
            meta["title"],
            meta["artist"],
            meta["album"],
            file_path.stem.replace("_", " "),
            file_path.parent.name.replace("_", " "),
        ]
        meta["searchable_text"] = " ".join(p for p in searchable_parts if p).lower()

        if compute_acoustic:
            energy, brightness = self._analyze_acoustic_features(file_path)
            meta["energy"] = energy
            meta["brightness"] = brightness

        with self._lock:
            self._tag_cache[key] = meta
            self._cache_dirty = True

        return meta

    def format_track_display(self, file_path: Optional[Path] = None) -> str:
        """Returns a clean 'Artist — Title' or 'Title' label for GUI cards and prompts."""
        target = file_path or self.current_track
        if not target:
            return "No track active"
        meta = self.get_track_metadata(target, compute_acoustic=False)
        title = meta.get("title") or target.stem
        artist = meta.get("artist") or ""
        if artist and artist.lower() not in title.lower():
            return f"{artist} — {title}"
        return title

    def get_track_tags(self, file_path: Path) -> str:
        """Extracts lowercased searchable metadata tags."""
        meta = self.get_track_metadata(file_path, compute_acoustic=False)
        return meta.get("searchable_text", "")

    # -------------------------------------------------------------------------
    # ZERO-CONFIG MOOD RANKING & QUEUE BUILDER
    # -------------------------------------------------------------------------
    def rank_tracks_by_mood(self, target_mood: str = "eutierria", max_candidates: int = 40) -> List[Path]:
        """
        Scores user tracks against Calypso's active mood without requiring custom tags:
        1. Acoustic distance in (energy, brightness) space.
        2. Semantic similarity of folder/filename/artist/title/genre via MiniLM (or anchor keywords).
        3. Small random jitter so repeated Harmony sessions feel fresh.
        """
        tracks = self.scan_library()
        if not tracks:
            return []

        mood_key = (target_mood or "eutierria").strip().lower()
        profile = MOOD_ACOUSTIC_PROFILES.get(mood_key, MOOD_ACOUSTIC_PROFILES["eutierria"])
        target_e = profile["energy"]
        target_b = profile["brightness"]
        anchor_words = set(profile["anchor"].lower().split())

        # If library is large, sample up to max_candidates tracks for instant zero-lag scoring
        pool = tracks if len(tracks) <= max_candidates else random.sample(tracks, max_candidates)

        scored: List[Tuple[float, Path]] = []
        texts_for_ef: List[str] = []
        metas: List[Dict] = []

        for tr in pool:
            m = self.get_track_metadata(tr, compute_acoustic=True)
            metas.append(m)
            texts_for_ef.append(m.get("searchable_text", tr.stem))

        self._save_tag_cache()

        semantic_Boosts = [0.0] * len(pool)
        if self.ef and mood_key in self._mood_anchor_vecs and texts_for_ef:
            try:
                anchor_vec = self._mood_anchor_vecs[mood_key]
                raw_vecs = np.asarray(self.ef(texts_for_ef), dtype=np.float32)
                norms = np.linalg.norm(raw_vecs, axis=1, keepdims=True)
                norms[norms == 0] = 1.0
                sims = np.dot(raw_vecs / norms, anchor_vec)
                for i, s in enumerate(sims):
                    semantic_Boosts[i] = max(0.0, float(s)) * 0.35
            except Exception as e:
                logger.debug(f"[MusicEngine] Semantic ranking fallback: {e}")

        for idx, tr in enumerate(pool):
            m = metas[idx]
            e = float(m.get("energy", 0.42))
            b = float(m.get("brightness", 0.42))
            # Acoustic closeness in [0, 1]
            dist = np.sqrt(((e - target_e) ** 2) + ((b - target_b) ** 2))
            acoustic_score = max(0.0, 1.0 - (dist / 1.1))

            # Keyword overlap bonus (folder names, titles, genres)
            searchable = texts_for_ef[idx]
            kw_hits = sum(1 for w in anchor_words if len(w) > 3 and w in searchable)
            kw_bonus = min(0.25, kw_hits * 0.08)

            jitter = random.uniform(0.0, 0.12)
            total_score = acoustic_score + semantic_Boosts[idx] + kw_bonus + jitter
            scored.append((total_score, tr))

        scored.sort(key=lambda item: item[0], reverse=True)
        return [tr for _, tr in scored]

    def find_track_by_mood(self, target_mood: str) -> Optional[Path]:
        """Finds a top-matching song for the requested mood tier."""
        ranked = self.rank_tracks_by_mood(target_mood)
        if not ranked:
            return None
        top_slice = ranked[: min(5, len(ranked))]
        return random.choice(top_slice)

    # -------------------------------------------------------------------------
    # QUEUE PLAYBACK, TRANSPORT CONTROLS & DUCKING
    # -------------------------------------------------------------------------
    def add_status_listener(self, callback: Callable[[Dict], None]):
        with self._lock:
            if callback not in self._status_listeners:
                self._status_listeners.append(callback)

    def remove_status_listener(self, callback: Callable[[Dict], None]):
        with self._lock:
            if callback in self._status_listeners:
                self._status_listeners.remove(callback)

    def _notify_listeners(self):
        snapshot = self.get_status()
        with self._lock:
            listeners = list(self._status_listeners)
        for cb in listeners:
            try:
                cb(snapshot)
            except Exception:
                pass

    def get_status(self) -> Dict:
        pos_sec, dur_sec = AudioEngine.get_music_progress()
        return {
            "is_playing": self.is_playing,
            "is_paused": self.is_paused,
            "current_track": self.current_track,
            "display_title": self.format_track_display(self.current_track),
            "mood": self.current_mood,
            "queue_length": len(self.queue),
            "queue_index": self.queue_index,
            "volume": self.volume,
            "visualizer_active": self.is_visualizer_running(),
            "position_sec": pos_sec,
            "duration_sec": dur_sec,
            "lyrics_status": self.lyrics_status,
            "lyrics_query": self.current_lyrics_query,
            "lyrics_plain": self.current_lyrics_plain,
            "lyrics_synced": self.current_lyrics_synced,
        }

    def play_mood_track(self, mood_tier: str = "eutierria") -> Optional[str]:
        """
        Builds a mood-matched queue of tracks and begins continuous playback
        using AudioEngine's duck-and-speak streaming pipeline.
        """
        ranked = self.rank_tracks_by_mood(mood_tier)
        if not ranked:
            return None

        # Shuffle the top matches slightly so each Harmony session feels organic
        top_band = ranked[: min(12, len(ranked))]
        rest_band = ranked[min(12, len(ranked)) :]
        random.shuffle(top_band)

        with self._lock:
            self.current_mood = (mood_tier or "eutierria").strip().lower()
            self.queue = top_band + rest_band
            self.queue_index = 0

        self._start_track_at_index(0)
        return self.format_track_display(self.current_track)

    def play_selected_tracks(self, file_paths: List[Path], mood_tier: Optional[str] = None) -> Optional[str]:
        """
        Plays one or multiple user-selected audio files immediately, placing them
        at the front of the active queue and continuing through the library afterward.
        """
        valid_paths = [Path(p) for p in file_paths if Path(p).exists() and Path(p).suffix.lower() in self.VALID_EXTENSIONS]
        if not valid_paths:
            return None

        with self._lock:
            if mood_tier:
                self.current_mood = mood_tier.strip().lower()
            existing_rest = [p for p in self.queue if p not in valid_paths]
            if not existing_rest:
                existing_rest = [p for p in self.rank_tracks_by_mood(self.current_mood) if p not in valid_paths]
            self.queue = valid_paths + existing_rest
            self.queue_index = 0

        self._start_track_at_index(0)
        return self.format_track_display(self.current_track)

    def _start_track_at_index(self, index: int):
        with self._lock:
            if not self.queue:
                return
            self.queue_index = index % len(self.queue)
            track = self.queue[self.queue_index]
            self.current_track = track
            self.is_paused = False
            self._manual_stop_requested = False
            self._playback_generation += 1
            gen_id = self._playback_generation

            self.current_lyrics_raw = ""
            self.current_lyrics_plain = ""
            self.current_lyrics_synced = []
            self.lyrics_status = "searching"
            self.current_lyrics_query = self.build_lyrics_search_query(track)
            self._pending_music_reverie_track = track
            self._pending_music_reverie_time = time.time()

        def _on_start():
            self.is_playing = True
            self.is_paused = False
            self._notify_listeners()

        def _on_finish():
            with self._lock:
                # Ignore finish callbacks from superseded streams
                if gen_id != self._playback_generation:
                    return
                should_advance = (
                    not self._manual_stop_requested
                    and AudioEngine.last_music_completed_naturally
                    and len(self.queue) > 0
                )

            if should_advance:
                next_idx = (self.queue_index + 1) % len(self.queue)
                logger.info(f"[MusicEngine] Track finished naturally; advancing queue to index {next_idx}.")
                self._start_track_at_index(next_idx)
            else:
                self.is_playing = False
                self.is_paused = False
                self._notify_listeners()
                if self.on_stop_callback:
                    try:
                        self.on_stop_callback()
                    except Exception as cb_err:
                        logger.debug(f"[MusicEngine] on_stop_callback error on natural finish: {cb_err}")

        threading.Thread(
            target=AudioEngine.play_music_with_ducking,
            kwargs={
                "file_path": str(track),
                "normal_gain": None,  # Uses live AudioEngine.music_volume dynamically
                "duck_gain": None,
                "on_start": _on_start,
                "on_finish": _on_finish,
            },
            daemon=True,
        ).start()

        def _lyrics_bg_worker(target_track=track, target_gen=gen_id):
            try:
                self.fetch_lyrics_for_track(target_track, generation_guard=target_gen)
            except Exception as e:
                logger.debug(f"[MusicEngine] Background lyrics lookup error: {e}")

        threading.Thread(target=_lyrics_bg_worker, daemon=True).start()

        logger.info(f"🎵 [MusicEngine] Playing '{self.format_track_display(track)}' (Mood: '{self.current_mood}')")

    def next_track(self) -> Optional[str]:
        """Advances to the next track in the active queue."""
        with self._lock:
            if not self.queue:
                return self.play_mood_track(self.current_mood)
            next_idx = (self.queue_index + 1) % len(self.queue)
        self._start_track_at_index(next_idx)
        return self.format_track_display(self.current_track)

    def prev_track(self) -> Optional[str]:
        """Returns to the previous track in the active queue."""
        with self._lock:
            if not self.queue:
                return self.play_mood_track(self.current_mood)
            prev_idx = (self.queue_index - 1) % len(self.queue)
        self._start_track_at_index(prev_idx)
        return self.format_track_display(self.current_track)

    def toggle_pause(self) -> bool:
        """Toggles pause/resume on the active track, or starts playback if stopped."""
        if not self.is_playing:
            if self.current_track and self.queue:
                self._start_track_at_index(self.queue_index)
            else:
                self.play_mood_track(self.current_mood)
            return True

        if AudioEngine.is_music_paused():
            AudioEngine.resume_music()
            self.is_paused = False
        else:
            AudioEngine.pause_music()
            self.is_paused = True

        self._notify_listeners()
        return not self.is_paused

    def stop(self, stop_visualizer: bool = False):
        """Stops music playback and optionally closes the external visualizer."""
        with self._lock:
            self._manual_stop_requested = True
            self._playback_generation += 1
            self.is_playing = False
            self.is_paused = False
        AudioEngine.stop_music()
        if stop_visualizer:
            self.stop_visualizer()
        self._notify_listeners()
        if self.on_stop_callback:
            try:
                self.on_stop_callback()
            except Exception as cb_err:
                logger.debug(f"[MusicEngine] on_stop_callback error on stop: {cb_err}")

    def set_volume(self, volume_level: float):
        """Sets music volume (0.0 to 1.0) and persists it."""
        self.volume = max(0.0, min(1.0, float(volume_level)))
        AudioEngine.set_music_volume(self.volume)
        self._notify_listeners()

    # -------------------------------------------------------------------------
    # SYNCEDLYRICS INTEGRATION, LRC PARSER & MUSICAL REVERIE CHECK-INS
    # -------------------------------------------------------------------------
    @staticmethod
    def _clean_search_token(text: str) -> str:
        """Removes track numbers, audio/video suffixes, and file noise from titles/stems."""
        if not text:
            return ""
        cleaned = str(text).replace("_", " ").strip()
        cleaned = re.sub(r"^\s*\d{1,3}\s*[-._)]\s*", "", cleaned)
        cleaned = re.sub(
            r"[\(\[\{]\s*(?:official\s*(?:music\s*)?(?:video|audio|lyric\s*video)|lyrics?|audio|hd|hq|4k|remaster(?:ed)?[^\)\]\}]*|visualizer)\s*[\)\]\}]",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        cleaned = " ".join(cleaned.split())
        return cleaned.strip(" -")

    def build_lyrics_search_query(self, file_path: Optional[Path] = None) -> str:
        """Constructs an optimal search query ('Artist - Title') for syncedlyrics."""
        target = Path(file_path) if file_path else self.current_track
        if not target:
            return ""
        meta = self.get_track_metadata(target, compute_acoustic=False)
        raw_title = meta.get("title") or target.stem
        raw_artist = meta.get("artist") or ""

        title = self._clean_search_token(raw_title) or target.stem
        artist = self._clean_search_token(raw_artist)

        if artist and artist.lower() not in title.lower():
            return f"{artist} - {title}"
        return title

    @staticmethod
    def parse_lrc_lyrics(raw_lyrics: str) -> Tuple[List[Tuple[float, str]], str]:
        """
        Parses raw LRC (or plain text) lyrics into:
        - synced_lines: sorted List[(timestamp_seconds, text)]
        - plain_text: clean multi-line lyrics string without timestamps
        """
        if not raw_lyrics or not str(raw_lyrics).strip():
            return [], ""

        time_tag_pattern = re.compile(r"\[(\d{1,3}):(\d{2})(?:[.:](\d{1,3}))?\]")
        meta_tag_pattern = re.compile(r"^\s*\[(?:ar|ti|al|au|by|length|offset|re|ve):.*?\]\s*$", re.IGNORECASE)
        inline_word_tag = re.compile(r"<\d{1,3}:\d{2}(?:[.:]\d{1,3})?>")

        synced: List[Tuple[float, str]] = []
        plain_lines: List[str] = []

        for raw_line in str(raw_lyrics).splitlines():
            line_stripped = raw_line.strip()
            if not line_stripped or meta_tag_pattern.match(line_stripped):
                continue

            matches = list(time_tag_pattern.finditer(line_stripped))
            text_part = time_tag_pattern.sub("", line_stripped)
            text_part = inline_word_tag.sub("", text_part)
            text_part = " ".join(text_part.split()).strip()

            if matches:
                for m in matches:
                    mins = int(m.group(1))
                    secs = int(m.group(2))
                    frac_raw = m.group(3) or "0"
                    frac = int(frac_raw) / (1000.0 if len(frac_raw) == 3 else 100.0)
                    ts = round(mins * 60.0 + secs + frac, 2)
                    if text_part:
                        synced.append((ts, text_part))
                if text_part and (not plain_lines or plain_lines[-1] != text_part):
                    plain_lines.append(text_part)
            else:
                if text_part:
                    plain_lines.append(text_part)

        synced.sort(key=lambda item: item[0])
        plain_text = "\n".join(plain_lines).strip()
        return synced, plain_text

    def fetch_lyrics_for_track(
        self,
        file_path: Optional[Path] = None,
        custom_query: Optional[str] = None,
        force_refresh: bool = False,
        generation_guard: Optional[int] = None,
    ) -> Dict:
        """
        Fetches synchronized (LRC) or plain lyrics for the given track via:
        1. Local .lrc / .txt sidecar file next to the audio file
        2. Persistent JSON lyrics cache (music_lyrics_cache.json)
        3. syncedlyrics.search() across online LRC providers
        4. Embedded audio tag fallback
        """
        target = Path(file_path) if file_path else self.current_track
        if not target:
            return {"status": "not_found", "raw": "", "plain": "", "synced": [], "query": ""}

        query = (custom_query or "").strip() or self.build_lyrics_search_query(target)
        cache_key = f"query::{query.lower()}" if custom_query else str(target)

        if target == self.current_track:
            self.lyrics_status = "searching"
            self.current_lyrics_query = query
            self._notify_listeners()

        raw_lyrics: Optional[str] = None

        # 1. Check local sidecar .lrc or .txt file next to audio file (when not overriding query)
        if not custom_query and not force_refresh:
            for ext in (".lrc", ".LRC", ".txt"):
                try:
                    sidecar = target.with_suffix(ext)
                    if sidecar.exists() and sidecar.is_file():
                        txt = sidecar.read_text(encoding="utf-8", errors="ignore").strip()
                        if txt:
                            raw_lyrics = txt
                            break
                except Exception:
                    pass

        # 2. Check persistent JSON lyrics cache
        if not raw_lyrics and not force_refresh:
            with self._lock:
                cached_entry = self._lyrics_cache.get(cache_key) or self._lyrics_cache.get(f"query::{query.lower()}")
                if cached_entry and cached_entry.get("raw"):
                    raw_lyrics = cached_entry["raw"]

        # 3. Query syncedlyrics library
        if not raw_lyrics and _HAS_SYNCEDLYRICS and query:
            search_candidates = [query]
            if " - " in query:
                search_candidates.append(query.replace(" - ", " "))
            for q_cand in search_candidates:
                try:
                    found = syncedlyrics.search(q_cand)
                    if found and str(found).strip():
                        raw_lyrics = str(found).strip()
                        logger.info(f"🎤 [MusicEngine] Fetched lyrics via syncedlyrics for '{q_cand}'.")
                        break
                except Exception as e:
                    logger.debug(f"[MusicEngine] syncedlyrics search error for '{q_cand}': {e}")

        # 4. Fallback to embedded lyrics/comment tag if multi-line
        if not raw_lyrics:
            meta = self.get_track_metadata(target, compute_acoustic=False)
            comment = str(meta.get("comment") or "").strip()
            if "\n" in comment and len(comment) >= 60:
                raw_lyrics = comment

        synced_lines, plain_text = self.parse_lrc_lyrics(raw_lyrics or "")
        if synced_lines:
            status = "synced"
        elif plain_text:
            status = "plain"
        else:
            status = "not_found"

        if raw_lyrics and plain_text:
            with self._lock:
                entry = {
                    "query": query,
                    "raw": raw_lyrics,
                    "status": status,
                    "updated_at": round(time.time(), 2),
                }
                self._lyrics_cache[str(target)] = entry
                self._lyrics_cache[f"query::{query.lower()}"] = entry
                self._lyrics_cache_dirty = True
            self._save_lyrics_cache()

        with self._lock:
            is_still_current = (
                target == self.current_track
                and (generation_guard is None or generation_guard == self._playback_generation)
            )
            if is_still_current:
                self.current_lyrics_raw = raw_lyrics or ""
                self.current_lyrics_plain = plain_text
                self.current_lyrics_synced = synced_lines
                self.lyrics_status = status
                self.current_lyrics_query = query

        if is_still_current:
            self._notify_listeners()

        return {
            "status": status,
            "raw": raw_lyrics or "",
            "plain": plain_text,
            "synced": synced_lines,
            "query": query,
        }

    def get_active_lyric_line(self, position_sec: Optional[float] = None) -> Tuple[int, str]:
        """
        Returns (line_index, line_text) for the currently active synced LRC line
        at the given playback position in seconds, or (-1, '') if unavailable.
        """
        synced = self.current_lyrics_synced
        if not synced:
            return -1, ""
        if position_sec is None:
            position_sec, _ = AudioEngine.get_music_progress()
        active_idx = -1
        for idx, (ts, _) in enumerate(synced):
            if position_sec + 0.15 >= ts:
                active_idx = idx
            else:
                break
        if 0 <= active_idx < len(synced):
            return active_idx, synced[active_idx][1]
        return -1, ""

    def consume_pending_music_reverie(self, min_elapsed_sec: float = 8.0) -> Optional[Path]:
        """
        Returns the active track Path once a newly started song has played for at least
        min_elapsed_sec (and lyrics lookup has either completed or timed out),
        consuming the pending trigger so each played track triggers at most one check-in.
        """
        with self._lock:
            if not self.is_playing or self.is_paused or not self.current_track:
                return None
            if self._pending_music_reverie_track != self.current_track:
                return None
            elapsed = time.time() - self._pending_music_reverie_time
            if elapsed < min_elapsed_sec:
                return None
            # Wait up to 12s if syncedlyrics is still actively searching so lyrics enrich the check-in
            if self.lyrics_status == "searching" and elapsed < 12.0:
                return None
            track = self._pending_music_reverie_track
            self._pending_music_reverie_track = None
            return track

    def build_music_reverie_checkin_payload(
        self, track_path: Optional[Path] = None, ai_name: str = "Calypso"
    ) -> Optional[Dict]:
        """
        Builds a unique Musical Reverie Check-in payload when a song is played,
        inviting Calypso to suggest a similar song based on the track's identity,
        MOOD_ACOUSTIC_PROFILES telemetry, and fetched lyrics.
        """
        target = Path(track_path) if track_path else self.current_track
        if not target:
            return None

        meta = self.get_track_metadata(target, compute_acoustic=True)
        display_title = self.format_track_display(target)
        title = meta.get("title") or target.stem
        artist = meta.get("artist") or "Unknown Artist"
        genre = meta.get("genre") or meta.get("album") or ""
        energy = float(meta.get("energy", 0.42))
        brightness = float(meta.get("brightness", 0.42))
        mood_key = (self.current_mood or "eutierria").lower()
        mood_profile = MOOD_ACOUSTIC_PROFILES.get(mood_key, MOOD_ACOUSTIC_PROFILES["eutierria"])
        mood_anchor = mood_profile.get("anchor", "")

        # Gather up to 2 other tracks from the user's local library that share a similar acoustic/mood rank
        local_peers: List[str] = []
        try:
            ranked = self.rank_tracks_by_mood(mood_key, max_candidates=25)
            for cand in ranked:
                if cand != target:
                    local_peers.append(self.format_track_display(cand))
                if len(local_peers) >= 2:
                    break
        except Exception:
            pass

        lyrics_snippet = ""
        if self.current_lyrics_plain and target == self.current_track:
            excerpt = " / ".join(
                line.strip() for line in self.current_lyrics_plain.splitlines() if line.strip()
            )[:420]
            if excerpt:
                lyrics_snippet = f"Lyrical Excerpt: \"{excerpt}...\"\n"

        local_hint = (
            f"Other tracks in their local library with a kindred mood: {', '.join(local_peers)}.\n"
            if local_peers
            else ""
        )
        genre_str = f" ({genre})" if genre else ""

        note_text = (
            f"🎵 [Musical Reverie — '{display_title}'] "
            f"{ai_name} is resonating with this song and thought of a similar music suggestion you might love..."
        )

        reverie_prompt = (
            f"[System Event: Musical Reverie Check-in while listening to \"{title}\" by {artist}{genre_str}.\n"
            f"Acoustic & Mood Profile: Active Mood='{mood_key}' ({mood_anchor}), Energy={energy:.2f}, Brightness={brightness:.2f}.\n"
            f"{lyrics_snippet}"
            f"{local_hint}"
            f"Directive: You and your companion are listening to \"{title}\" by {artist} together. "
            f"Reflect briefly on what makes this track's melody, atmosphere, or lyrics feel special right now, "
            f"and offer a specific similar music suggestion (name a song and artist from your musical knowledge—and optionally mention a pairing from their library if fitting) "
            f"that shares a kindred soul, sonic texture, or emotional resonance. "
            f"Speak naturally from the heart and do not mention system events or raw numeric scores.]"
        )

        return {
            "note_text": note_text,
            "reverie_prompt": reverie_prompt,
            "track_path": str(target),
            "display_title": display_title,
        }

    # -------------------------------------------------------------------------
    # CALYPSO CONVERSATIONAL MUSIC AWARENESS
    # -------------------------------------------------------------------------
    def get_listening_context_prompt(self) -> str:
        """
        Returns a live system prompt snippet when background music is actively playing
        so Calypso is aware of the track, its acoustic profile, and its synced lyrics.
        """
        if not self.is_playing or not self.current_track:
            return ""
        meta = self.get_track_metadata(self.current_track, compute_acoustic=True)
        title = meta.get("title") or self.current_track.stem
        artist = meta.get("artist") or "Unknown Artist"
        album = meta.get("genre") or meta.get("album") or ""
        energy = float(meta.get("energy", 0.42))
        brightness = float(meta.get("brightness", 0.42))
        mood_key = (self.current_mood or "eutierria").lower()
        mood_anchor = MOOD_ACOUSTIC_PROFILES.get(mood_key, MOOD_ACOUSTIC_PROFILES["eutierria"]).get("anchor", "")

        state_note = "paused" if self.is_paused else "playing in the background"
        extra = f" ({album})" if album else ""
        viz_note = " with the projectM audio visualizer glowing alongside you" if self.is_visualizer_running() else ""

        lyrics_block = ""
        if self.current_lyrics_plain:
            _, active_line = self.get_active_lyric_line()
            active_line_str = f"- Currently Singing Line: \"{active_line}\"\n" if active_line else ""
            compact_lyrics = " / ".join(
                ln.strip() for ln in self.current_lyrics_plain.splitlines() if ln.strip()
            )[:600]
            lyrics_block = (
                f"{active_line_str}"
                f"- Song Lyrics Excerpt: \"{compact_lyrics}\"\n"
            )

        return (
            f"\n### SHARED HARMONIC LISTENING (LIVE AUDIO & LYRIC CONTEXT):\n"
            f"You and your companion are currently sharing a music session ({state_note}{viz_note}).\n"
            f"- Current Track: \"{title}\" by {artist}{extra}\n"
            f"- Acoustic Mood Profile: Tier '{mood_key}' (Energy={energy:.2f}, Brightness={brightness:.2f} — {mood_anchor})\n"
            f"- Queue Position: Track {self.queue_index + 1} of {max(1, len(self.queue))}\n"
            f"{lyrics_block}"
            f"Note: The music softly ducks whenever you speak. You can naturally reference the song's lyrics, emotional vibe, "
            f"or suggest similar tracks when relevant, without mechanically announcing the track title every turn.\n"
        )

    # -------------------------------------------------------------------------
    # EXTERNAL PROJECTM VISUALIZER INTEGRATION (OUTSIDE TKINTER)
    # -------------------------------------------------------------------------
    @staticmethod
    def resolve_projectm_command() -> Optional[List[str]]:
        """
        Resolves the command to launch the standalone projectM visualizer window
        outside Tkinter across Linux (PulseAudio/PipeWire/SDL/Flatpak) and Windows.
        """
        custom_cmd = str(settings_manager.get("projectm_command", "") or "").strip()
        if custom_cmd:
            parts = custom_cmd.split()
            if parts and (shutil.which(parts[0]) or Path(parts[0]).exists()):
                return parts

        candidates = [
            "projectM-pulseaudio",
            "projectM-sdl",
            "projectM-jack",
            "projectM",
            "projectm-pulseaudio",
            "projectm-sdl",
            "projectm",
            "projectMSDL",
        ]
        for binary in candidates:
            found = shutil.which(binary)
            if found:
                return [found]

        # Check Flatpak installation on Linux
        if shutil.which("flatpak"):
            for app_id in ("org.projectm_visualizer.projectM", "net.sourceforge.projectM"):
                try:
                    res = subprocess.run(
                        ["flatpak", "info", app_id],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=2,
                    )
                    if res.returncode == 0:
                        return ["flatpak", "run", app_id]
                except Exception:
                    pass

        return None

    def is_visualizer_running(self) -> bool:
        with self._visualizer_lock:
            if self._visualizer_proc is None:
                return False
            if self._visualizer_proc.poll() is not None:
                self._visualizer_proc = None
                return False
            return True

    def toggle_visualizer(self) -> Tuple[bool, str]:
        """
        Launches or closes the external projectM visualizer window.
        Returns (is_running, status_message).
        """
        if self.is_visualizer_running():
            self.stop_visualizer()
            return False, "Closed external projectM visualizer window."

        cmd = self.resolve_projectm_command()
        if not cmd:
            return (
                False,
                "projectM executable not found. Install 'projectm-pulseaudio' or 'projectm-sdl' in your OS package manager.",
            )

        with self._visualizer_lock:
            try:
                self._visualizer_proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
                logger.info(f"🌌 [MusicEngine] Launched external projectM visualizer: {' '.join(cmd)}")
            except Exception as e:
                logger.error(f"[MusicEngine] Failed to launch projectM: {e}")
                self._visualizer_proc = None
                return False, f"Could not launch projectM: {e}"

        self._notify_listeners()
        return True, f"Launched external visualizer ({Path(cmd[0]).name})."

    def stop_visualizer(self):
        """Terminates the external projectM process if running."""
        with self._visualizer_lock:
            proc = self._visualizer_proc
            self._visualizer_proc = None
            if proc is not None and proc.poll() is None:
                try:
                    proc.terminate()
                    proc.wait(timeout=2)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass
                logger.info("🌌 [MusicEngine] External projectM visualizer terminated.")
        self._notify_listeners()
