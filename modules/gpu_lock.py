# modules/gpu_lock.py
import threading
import logging

logger = logging.getLogger("EmotionEngine.GPULock")

# Global re-entrant lock for GPU-heavy neural pipelines (SDXL, MusicGen, Kokoro TTS, and Ollama VRAM).
# Guarantees that SDXL, MusicGen, and background Ollama/TTS tasks never collide in VRAM simultaneously.
gpu_vram_lock = threading.RLock()

