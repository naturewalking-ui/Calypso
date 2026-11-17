# modules/settings_manager.py

import json
import logging
import urllib.request
import re
from pathlib import Path
from typing import Any, Dict, List
from modules.config import config
from modules.hardware_sentinel import hardware_sentinel

logger = logging.getLogger("Calypso.Settings")

SETTINGS_FILE = config.MEMORY_DIR / "user_preferences.json"

DEFAULT_SETTINGS: Dict[str, Any] = {
    # 0. Lifecycle & Onboarding State
    "onboarding_completed": False,
    "emergent_behavior_warning_acknowledged": False,

    # 1. Identity & Bond
    "companion_name": "Companion",
    "companion_nickname": "",
    "ai_name": "Calypso",
    
    # 2. Model & Inference (Gemma 4 Series Only)
    "ollama_url": "http://localhost:11434",
    "model_name": config.MODEL_NAME,
    "vision_model": config.VISION_MODEL,
    "temperature": 0.8,
    "cognitive_profile": "balanced",
    "num_ctx": 16384,
    "num_predict": 4096,

    # Stable Diffusion Image Generation
    "sd_url": config.SD_URL,
    "sd_model": config.SD_MODEL,
    "sd_steps": 25,                             
    "sd_guidance_scale": 6.0,
    "sd_resolution": "1024 x 1024 (1:1 Square)",
    "sd_enable_face_swap": True,
    "sd_restore_face": True,

    # AudioCraft & Music Generation (Off by default unless >= 16GB VRAM)
    "audiocraft_enabled": False,
    "audiocraft_allow_online": False,
    "audiocraft_model": config.MUSICGEN_MODEL,
    "audiocraft_duration": 30,
    "audiocraft_guidance_scale": 3.0,
    "audiocraft_top_k": 250,
    "audiocraft_top_p": 0.0,
    "audiocraft_temperature": 1.0,
    
    # 3. Reverie & Autonomous Agency (Offline by Default)
    "reverie_idle_timeout_min": 60,
    "epistolary_idle_timeout_min": 60,
    "email_check_idle_timeout_sec": 120,
    "circadian_sleep_enabled": True,
    "circadian_sleep_start": 23,
    "circadian_sleep_end": 7,
    "autonomous_art_enabled": True,
    "autonomous_poetry_enabled": True,
    "autonomous_music_enabled": False,
    "autonomous_research_enabled": False,
    "autonomous_research_cooldown_min": 60,
    "autonomous_research_topic": "", 
    # 4. Email & Mailbox (Offline by Default — Opt-In)
    "email_enabled": False,
    "gmail_address": "",
    "gmail_app_password": "",
    "user_email": "",
    "gmail_auto_send": False,

    # 5. Audio & Voice
    "kokoro_voice": "af_heart",
    "master_volume": 0.8,
    "sfx_enabled": True,
    "sfx_volume": 0.75,
    "music_library_dir": "",
    "avatar_mode": "spectrum",
    "spectrum_color_mode": "emotion"
}


class SettingsManager:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(SettingsManager, cls).__new__(cls)
            cls._instance.settings = {}
            cls._instance.load()
        return cls._instance

    def load(self) -> Dict[str, Any]:
        """Loads user preferences from /modules/emotion/memory/user_preferences.json."""
        self.settings = DEFAULT_SETTINGS.copy()
        if SETTINGS_FILE.exists():
            try:
                with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                    self.settings.update(saved)
            except Exception as e:
                logger.error(f"[Settings] Error loading {SETTINGS_FILE}: {e}")
        else:
            self.save()
        self._apply_to_runtime()
        return self.settings

    def is_first_run(self) -> bool:
        """Determines if the application requires initial onboarding calibration."""
        return not bool(self.settings.get("onboarding_completed", False))

    def save(self, new_settings: Dict[str, Any] = None) -> bool:
        """Persists settings and applies them across global config references."""
        if new_settings:
            self.settings.update(new_settings)

        try:
            config.MEMORY_DIR.mkdir(parents=True, exist_ok=True)
            tmp_path = SETTINGS_FILE.with_suffix(".tmp")
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(self.settings, f, indent=4)
            tmp_path.replace(SETTINGS_FILE)
            self._apply_to_runtime()
            logger.info("[Settings] Saved successfully to memory directory.")
            return True
        except Exception as e:
            logger.error(f"[Settings] Failed saving settings: {e}")
            return False

    def _apply_to_runtime(self):
        """Syncs settings with runtime properties in `config` (enforcing Gemma 4 series LLM)."""
        raw_model = str(self.settings.get("model_name") or config.MODEL_NAME or "gemma4:12b").strip()
        if not hardware_sentinel.is_gemma4_model(raw_model):
            fallback_model = hardware_sentinel.recommend_gemma4_model().get("recommended_model", "gemma4:12b")
            logger.warning(
                f"[Settings] Model '{raw_model}' is not in the supported Gemma 4 series. "
                f"Falling back to '{fallback_model}'."
            )
            raw_model = fallback_model
            self.settings["model_name"] = raw_model

        config.MODEL_NAME = raw_model
        vision = str(self.settings.get("vision_model") or "").strip()
        if not vision or not hardware_sentinel.is_gemma4_model(vision):
            vision = config.MODEL_NAME
        config.VISION_MODEL = vision
        
        config.OLLAMA_OPTIONS["temperature"] = float(self.settings.get("temperature", 0.8))

        config.OLLAMA_OPTIONS["num_ctx"] = int(self.settings.get("num_ctx", 16384))
        config.OLLAMA_OPTIONS["num_predict"] = int(self.settings.get("num_predict", 4096))
        base_url = str(self.settings.get("ollama_url", "http://localhost:11434")).rstrip("/")
        if base_url.endswith("/api/chat"):
            config.OLLAMA_URL = base_url
        else:
            config.OLLAMA_URL = f"{base_url}/api/chat"
        
        # Stable Diffusion runtime sync
        config.SD_URL = self.settings.get("sd_url", config.SD_URL)
        config.SD_MODEL = self.settings.get("sd_model", config.SD_MODEL)
        config.SD_STEPS = int(self.settings.get("sd_steps", getattr(config, "SD_STEPS", 25)))
        config.SD_GUIDANCE_SCALE = float(self.settings.get("sd_guidance_scale", getattr(config, "SD_GUIDANCE_SCALE", 6.0)))
        config.ENABLE_FACE_SWAP = bool(self.settings.get("sd_enable_face_swap", getattr(config, "ENABLE_FACE_SWAP", True)))
        config.RESTORE_FACE = bool(self.settings.get("sd_restore_face", getattr(config, "RESTORE_FACE", True)))

        # Parse Resolution (e.g. "896 x 1152 (3:4 Portrait)") -> SD_WIDTH & SD_HEIGHT
        res_str = str(self.settings.get("sd_resolution", "1024 x 1024"))
        match = re.search(r'(\d+)\s*[xX]\s*(\d+)', res_str)
        if match:
            config.SD_WIDTH = int(match.group(1))
            config.SD_HEIGHT = int(match.group(2))
        else:
            config.SD_WIDTH = 1024
            config.SD_HEIGHT = 1024

        # AudioCraft / MusicGen runtime sync
        config.AUDIOCRAFT_ENABLED = bool(self.settings.get("audiocraft_enabled", getattr(config, "AUDIOCRAFT_ENABLED", False)))
        config.AUDIOCRAFT_ALLOW_ONLINE = bool(self.settings.get("audiocraft_allow_online", getattr(config, "AUDIOCRAFT_ALLOW_ONLINE", False)))
        config.MUSICGEN_MODEL = str(self.settings.get("audiocraft_model", getattr(config, "MUSICGEN_MODEL", ""))).strip()
        config.MUSICGEN_DURATION = int(self.settings.get("audiocraft_duration", getattr(config, "MUSICGEN_DURATION", 30)))
        config.MUSICGEN_GUIDANCE_SCALE = float(self.settings.get("audiocraft_guidance_scale", getattr(config, "MUSICGEN_GUIDANCE_SCALE", 3.0)))
        config.MUSICGEN_TOP_K = int(self.settings.get("audiocraft_top_k", getattr(config, "MUSICGEN_TOP_K", 250)))
        config.MUSICGEN_TOP_P = float(self.settings.get("audiocraft_top_p", getattr(config, "MUSICGEN_TOP_P", 0.0)))
        config.MUSICGEN_TEMPERATURE = float(self.settings.get("audiocraft_temperature", getattr(config, "MUSICGEN_TEMPERATURE", 1.0)))

        # Email & Online opt-in runtime sync
        config.EMAIL_ENABLED = bool(self.settings.get("email_enabled", False))
        config.AUTONOMOUS_RESEARCH_ENABLED = bool(self.settings.get("autonomous_research_enabled", False))
        config.GMAIL_ADDRESS = self.settings.get("gmail_address", "")
        config.GMAIL_APP_PASSWORD = self.settings.get("gmail_app_password", "")
        config.USER_EMAIL = self.settings.get("user_email", "")
        config.GMAIL_AUTO_SEND = bool(self.settings.get("gmail_auto_send", False))

    def get(self, key: str, default: Any = None) -> Any:
        return self.settings.get(key, default)

    def fetch_installed_ollama_models(self, gemma4_only: bool = True) -> List[str]:
        """
        Queries local Ollama instance for currently installed models.
        By default, restricts returned models strictly to the supported Gemma 4 series,
        appending the official Gemma 4 catalog tags so users can see all supported options.
        """
        base_url = str(self.settings.get("ollama_url", "http://localhost:11434")).rstrip("/")
        tags_url = f"{base_url}/api/tags"
        discovered: List[str] = []
        try:
            req = urllib.request.Request(tags_url, headers={"User-Agent": "EmotionCore-Client"})
            with urllib.request.urlopen(req, timeout=4) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                models = [m.get("name") for m in data.get("models", []) if m.get("name")]
                if gemma4_only:
                    discovered = hardware_sentinel.filter_supported_gemma4_models(models)
                else:
                    discovered = models
        except Exception as e:
            logger.warning(f"[Settings] Could not query Ollama models: {e}")

        # Ensure the currently saved Gemma 4 model is included if valid
        current = str(self.settings.get("model_name", config.MODEL_NAME) or "").strip()
        if current and hardware_sentinel.is_gemma4_model(current) and current not in discovered:
            discovered.insert(0, current)

        # Append standard Gemma 4 catalog tags so users always see supported Gemma 4 tiers
        for entry in hardware_sentinel.GEMMA4_CATALOG:
            tag = entry["tag"]
            if tag not in discovered:
                discovered.append(tag)

        return discovered

    def fetch_installed_sd_models(self) -> List[str]:
        """Scans local /diffusion_models/ directory for installed checkpoints."""
        models_dir = getattr(config, "DIFFUSION_MODELS_DIR", config.BASE_DIR / "diffusion_models")
        if models_dir.exists():
            files = [f.name for f in models_dir.glob("*.safetensors")] + [f.name for f in models_dir.glob("*.ckpt")]
            if files:
                return sorted(files)
        return [self.settings.get("sd_model", "sdxl.safetensors")]

    def fetch_installed_audiocraft_models(self) -> List[str]:
        """Scans local /audiocraft_models/ directory (and local HF cache) for installed AudioCraft / MusicGen models."""
        models_dir = getattr(config, "AUDIOCRAFT_MODELS_DIR", config.BASE_DIR / "audiocraft_models")
        models_dir.mkdir(parents=True, exist_ok=True)
        discovered: List[str] = []

        if models_dir.exists():
            # 1. Check subdirectories inside audiocraft_models/ (standard HuggingFace / AudioCraft folder layout)
            for sub in sorted(models_dir.iterdir()):
                if sub.is_dir() and not sub.name.startswith("."):
                    has_weights = (
                        (sub / "config.json").exists()
                        or any(sub.glob("*.safetensors"))
                        or any(sub.glob("*.bin"))
                        or any(sub.glob("*.pt"))
                        or any(sub.glob("*.pth"))
                    )
                    if has_weights:
                        discovered.append(sub.name)

            # 2. Check standalone weight files directly inside audiocraft_models/
            valid_exts = {".safetensors", ".bin", ".pt", ".pth", ".ckpt"}
            for item in sorted(models_dir.iterdir()):
                if item.is_file() and item.suffix.lower() in valid_exts:
                    discovered.append(item.name)

        # 3. Also inspect local Hugging Face cache if accessible for cached musicgen/audiocraft repos
        try:
            hf_cache = Path.home() / ".cache" / "huggingface" / "hub"
            if hf_cache.exists():
                for repo_dir in sorted(hf_cache.glob("models--*")):
                    if repo_dir.is_dir() and any(k in repo_dir.name.lower() for k in ("musicgen", "audiocraft", "audiogen")):
                        parts = repo_dir.name.split("--")
                        if len(parts) >= 3:
                            repo_id = f"{parts[1]}/{'--'.join(parts[2:])}"
                            if repo_id not in discovered:
                                discovered.append(repo_id)
        except Exception:
            pass

        # 4. Always list the official Meta MusicGen repository IDs so opt-in users have exact model links
        official_repos = [
            "facebook/musicgen-medium",
            "facebook/musicgen-small",
            "facebook/musicgen-large",
        ]
        for repo_id in official_repos:
            if repo_id not in discovered:
                discovered.append(repo_id)

        return discovered



settings_manager = SettingsManager()
