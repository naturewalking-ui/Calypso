# modules/config.py
from pathlib import Path
import sys
import os

class config:
    BASE_DIR = Path(__file__).resolve().parent.parent

    # Emotion directories
    EMOTION_DIR = BASE_DIR / "modules" / "emotion"
    PERSONAS_DIR = EMOTION_DIR / "personas"
    AVATARS_DIR = PERSONAS_DIR / "avatars"
    DRIVER_IMAGES_DIR = PERSONAS_DIR / "driver_images"
    MEMORY_DIR = EMOTION_DIR / "memory"

    # Completely separate ChromaDB for reference material
    LIBRARY_CHROMA_DIR = MEMORY_DIR / "library_chroma_db"

    # Workspace & Model directories
    WORKSPACE_DIR = BASE_DIR / "workspace"
    SFX_DIR = BASE_DIR / "sfx"
    INPUT_DIR = WORKSPACE_DIR / "input"
    OUTPUT_DIR = WORKSPACE_DIR / "output"
    DIFFUSION_MODELS_DIR = BASE_DIR / "diffusion_models"
    AUDIOCRAFT_MODELS_DIR = BASE_DIR / "audiocraft_models"
    LIVEPORTRAIT_MODELS_DIR = BASE_DIR / "liveportrait_models"

    # Categorized Output Directories
    DOCS_OUTPUT_DIR = OUTPUT_DIR / "documents"
    IMAGES_OUTPUT_DIR = OUTPUT_DIR / "images"
    CODE_OUTPUT_DIR = OUTPUT_DIR / "code"
    POETRY_OUTPUT_DIR = OUTPUT_DIR / "poetry"
    PARCHMENT_IMAGE_PATH = WORKSPACE_DIR / "parchment.jpeg"
    MUSIC_OUTPUT_DIR = OUTPUT_DIR / "music"

    # AudioCraft / Music Generation Configuration
    AUDIOCRAFT_ENABLED = False
    AUDIOCRAFT_ALLOW_ONLINE = False
    MUSICGEN_MODEL = ""
    MUSICGEN_DURATION = 30
    MUSICGEN_GUIDANCE_SCALE = 3.5
    MUSICGEN_TOP_K = 250
    MUSICGEN_TOP_P = 0.0
    MUSICGEN_TEMPERATURE = 1.0

    # Stable Diffusion Checkpoint Selection
    SD_MODEL = ""
    INSWAPPER_MODEL = "inswapper_128.onnx"
    SOURCE_FACE_IMAGE = "calypso.png" 
    LOG_FILE = BASE_DIR / "logs" / "emotion_engine.log"
    SD_URL = "http://127.0.0.1:7860"
    SD_STEPS = 25
    SD_GUIDANCE_SCALE = 6.0
    SD_WIDTH = 1024
    SD_HEIGHT = 1024
    ENABLE_FACE_SWAP = True
    RESTORE_FACE = True
    
    # LLM Configuration (Ollama — Gemma 4 Series Only)
    OLLAMA_URL = "http://localhost:11434/api/chat"
    MODEL_NAME = "gemma4:12b"
    VISION_MODEL = MODEL_NAME
    OLLAMA_OPTIONS = {
        "num_ctx": 32768,
        "temperature": 0.8,
        "repeat_penalty": 1.15,
        "num_predict": 8192
    }
    
    # Audio Settings
    KOKORO_REPO = "hexgrad/Kokoro-82M"
    WHISPER_MODEL_SIZE = "base"
    
    # Gmail & Online Features (Offline by Default)
    EMAIL_ENABLED = False
    AUTONOMOUS_RESEARCH_ENABLED = False
    GMAIL_ADDRESS = ""
    GMAIL_APP_PASSWORD = ""
    USER_EMAIL = ""
    GMAIL_AUTO_SEND = False
  
Config = config
