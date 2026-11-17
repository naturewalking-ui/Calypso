# modules/image_generator.py

import json
import logging
import time
import threading
import urllib.request
import torch
import gc
from pathlib import Path
from PIL import Image
from diffusers import StableDiffusionXLPipeline
from modules.config import config
from modules.gpu_lock import gpu_vram_lock
# Import FaceSwapper component
try:
    from modules.face_swapper import FaceSwapper
    FACE_SWAPPER_AVAILABLE = True
except ImportError:
    FACE_SWAPPER_AVAILABLE = False

# Import Compel components
try:
    from compel import CompelForSDXL
    COMPEL_SDXL_AVAILABLE = True
except ImportError:
    COMPEL_SDXL_AVAILABLE = False
    try:
        from compel import Compel, ReturnedEmbeddingsType
        COMPEL_AVAILABLE = True
    except ImportError:
        COMPEL_AVAILABLE = False

logger = logging.getLogger("EmotionEngine.ImageGen")


class ImageGenerator:
    def __init__(self, output_dir=None, target_gpu: int = 1):
        self.output_dir = Path(output_dir) if output_dir else config.IMAGES_OUTPUT_DIR
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        if torch.cuda.is_available():
            if target_gpu >= torch.cuda.device_count():
                logger.warning(
                    f"[ImageGen] GPU index {target_gpu} not found ({torch.cuda.device_count()} available). Defaulting to cuda:0."
                )
                self.target_gpu = 0
            else:
                self.target_gpu = target_gpu
            self.device = f"cuda:{self.target_gpu}"
        else:
            self.target_gpu = -1
            self.device = "cpu"

        self._face_swapper = None

    def _resolve_model_path(self, model_filename: str = None) -> Path | None:
        """Resolves the SDXL checkpoint file chosen in Settings from diffusion_models/."""
        models_dir = getattr(config, "DIFFUSION_MODELS_DIR", config.BASE_DIR / "diffusion_models")
        models_dir.mkdir(parents=True, exist_ok=True)

        target = model_filename or getattr(config, "SD_MODEL", "sdxl.safetensors")

        candidate = models_dir / target
        if candidate.exists() and candidate.is_file():
            return candidate

        direct = Path(target)
        if direct.exists() and direct.is_file():
            return direct

        checkpoints = list(models_dir.glob("*.safetensors")) + list(models_dir.glob("*.ckpt"))
        if checkpoints:
            logger.warning(f"[ImageGen] Model '{target}' not found. Falling back to '{checkpoints[0].name}'.")
            return checkpoints[0]

        logger.error(f"[ImageGen] No diffusion models found in {models_dir}")
        return None

    def _resolve_swapper_model_path(self) -> Path | None:
        """Finds inswapper_128.onnx (or .onx) in diffusion_models/."""
        models_dir = getattr(config, "DIFFUSION_MODELS_DIR", config.BASE_DIR / "diffusion_models")
        for name in ["inswapper_128.onnx", "inswapper_128.onx", "inswapper.onnx"]:
            cand = models_dir / name
            if cand.is_file():
                return cand
        for pattern in ["*inswapper*.*", "*.onnx", "*.onx"]:
            matches = list(models_dir.glob(pattern))
            if matches:
                return matches[0]
        return None

    def _resolve_restorer_model_path(self) -> Path | None:
        """Finds GFPGAN (or CodeFormer) weights in diffusion_models/."""
        models_dir = getattr(config, "DIFFUSION_MODELS_DIR", config.BASE_DIR / "diffusion_models")
        
        # Check explicit setting
        custom = getattr(config, "RESTORER_MODEL", None)
        if custom:
            cand = models_dir / custom if not Path(custom).is_file() else Path(custom)
            if cand.is_file():
                return cand

        # Common model filenames
        common = ["GFPGANv1.4.pth", "GFPGANv1.3.pth", "GFPGAN.pth", "codeformer.pth"]
        for name in common:
            cand = models_dir / name
            if cand.is_file():
                return cand

        # Glob search for any pth file containing gfpgan or codeformer
        for pattern in ["*gfpgan*.pth", "*codeformer*.pth"]:
            matches = list(models_dir.glob(pattern))
            if matches:
                return matches[0]

        return None

    def _resolve_source_face_path(self, override_path: str | Path = None) -> Path | None:
        """Finds the cloning base image in diffusion_models/ or avatars/."""
        if override_path:
            p = Path(override_path)
            if p.is_file():
                return p

        cfg_image = getattr(config, "SOURCE_FACE_IMAGE", None) or getattr(config, "CLONE_FACE_IMAGE", None)
        if cfg_image:
            p = Path(cfg_image)
            if p.is_file():
                return p
            p = getattr(config, "DIFFUSION_MODELS_DIR", config.BASE_DIR / "diffusion_models") / cfg_image
            if p.is_file():
                return p

        models_dir = getattr(config, "DIFFUSION_MODELS_DIR", config.BASE_DIR / "diffusion_models")
        valid_exts = {".png", ".jpg", ".jpeg", ".webp"}

        for stem in ["clone", "base", "source", "face", "avatar", "persona", "reference"]:
            for ext in valid_exts:
                cand = models_dir / f"{stem}{ext}"
                if cand.is_file():
                    return cand

        if models_dir.exists():
            images = [f for f in models_dir.iterdir() if f.is_file() and f.suffix.lower() in valid_exts]
            if images:
                return images[0]

        avatars_dir = getattr(config, "AVATARS_DIR", None)
        if avatars_dir and avatars_dir.exists():
            avatars = [f for f in avatars_dir.iterdir() if f.is_file() and f.suffix.lower() in valid_exts]
            if avatars:
                return avatars[0]

        return None

    def _get_face_swapper(self) -> FaceSwapper | None:
        """Lazy-initializes FaceSwapper with GFPGAN support."""
        if not FACE_SWAPPER_AVAILABLE:
            logger.warning("[ImageGen] face_swapper module could not be imported.")
            return None

        if self._face_swapper is None:
            swapper_path = self._resolve_swapper_model_path()
            if not swapper_path:
                logger.warning("[ImageGen] inswapper ONNX file not found in diffusion_models/.")
                return None

            restorer_path = self._resolve_restorer_model_path()
            if restorer_path:
                logger.info(f"[ImageGen] Found face restoration weights: {restorer_path.name}")
            else:
                logger.info("[ImageGen] No GFPGAN weights found. Face swap will run without restoration.")

            try:
                gpu_id = self.target_gpu if torch.cuda.is_available() else -1
                self._face_swapper = FaceSwapper(
                    model_path=str(swapper_path),
                    target_gpu=gpu_id,
                    restorer_path=restorer_path
                )
            except Exception as e:
                logger.error(f"[ImageGen] Failed to initialize FaceSwapper: {e}", exc_info=True)
                return None

        return self._face_swapper

    def _apply_face_swap(self, image: Image.Image, source_face_path: str | Path = None) -> tuple[Image.Image, bool]:
        source_path = self._resolve_source_face_path(source_face_path)
        if not source_path:
            logger.warning("[ImageGen] Skipping face swap: Could not locate base cloning image.")
            return image, False

        swapper = self._get_face_swapper()
        if not swapper:
            return image, False

        try:
            logger.info(f"[ImageGen] Swapping face using reference '{source_path.name}'...")
            swapped_image = swapper.swap_face(
                target_image=image,
                source_image_path=source_path,
                restore=getattr(config, "RESTORE_FACE", True)
            )
            return swapped_image, True
        except Exception as e:
            logger.error(f"[ImageGen] Face swap failed: {e}. Keeping original image.", exc_info=True)
            return image, False

    # -------------------------------------------------------------------------
    # DYNAMIC VRAM ORCHESTRATION (Ollama Eviction & Pre-warming)
    # -------------------------------------------------------------------------
    def _unload_ollama(self) -> bool:
        logger.info("[ImageGen] Evicting LLM from VRAM via Ollama API...")
        try:
            base_url = str(config.OLLAMA_URL).rstrip("/")
            root_url = base_url.split("/api/")[0] if "/api/" in base_url else base_url
            generate_url = f"{root_url}/api/generate"

            payload = json.dumps({"model": config.MODEL_NAME, "keep_alive": 0}).encode("utf-8")
            req = urllib.request.Request(generate_url, data=payload, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=10):
                pass

            time.sleep(0.8)
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

            logger.info("[ImageGen] VRAM successfully cleared of LLM.")
            return True
        except Exception as e:
            logger.warning(f"[ImageGen] Could not evict Ollama (proceeding anyway): {e}")
            return False

    def _warmup_ollama_async(self):
        def _warm():
            try:
                logger.info("[ImageGen] Background pre-warming LLM into VRAM...")
                base_url = str(config.OLLAMA_URL).rstrip("/")
                root_url = base_url.split("/api/")[0] if "/api/" in base_url else base_url
                chat_url = f"{root_url}/api/chat"
                payload = json.dumps({
                    "model": config.MODEL_NAME,
                    "messages": [],
                    "keep_alive": "10m"
                }).encode("utf-8")
                
                req = urllib.request.Request(chat_url, data=payload, headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=30):
                    pass
                logger.info("[ImageGen] LLM successfully reloaded and warm in VRAM.")
            except Exception as e:
                logger.debug(f"[ImageGen] Background warmup notice: {e}")

        threading.Thread(target=_warm, daemon=True).start()

    def _log_generation(self, file_path: Path, prompt: str, negative_prompt: str = None, meta: dict = None):
        manifest_file = config.MEMORY_DIR / "gallery_history.json"
        entry = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "file_name": file_path.name,
            "file_path": str(file_path),
            "prompt": prompt,
            "negative_prompt": negative_prompt or "",
            "metadata": meta or {}
        }
        history = []
        if manifest_file.exists():
            try:
                with open(manifest_file, "r", encoding="utf-8") as f:
                    history = json.load(f)
            except Exception:
                history = []
        history.append(entry)
        tmp = manifest_file.with_suffix(".tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(history, f, indent=2)
            tmp.replace(manifest_file)
        except Exception as e:
            logger.warning(f"[ImageGen] Could not update gallery_history.json: {e}")

    def _encode_prompts(self, pipe, prompt: str, negative_prompt: str):
        neg = negative_prompt or ""

        if COMPEL_SDXL_AVAILABLE:
            compel = CompelForSDXL(pipe, device=self.device)
            conditioning = compel(prompt, negative_prompt=neg)
            del compel
            return (
                conditioning.embeds,
                conditioning.pooled_embeds,
                conditioning.negative_embeds,
                conditioning.negative_pooled_embeds
            )

        elif COMPEL_AVAILABLE:
            compel = Compel(
                tokenizer=[pipe.tokenizer, pipe.tokenizer_2],
                text_encoder=[pipe.text_encoder, pipe.text_encoder_2],
                returned_embeddings_type=ReturnedEmbeddingsType.PENULTIMATE_HIDDEN_STATES_NON_NORMALIZED,
                requires_pooled=[False, True],
                truncate_long_prompts=False,
                device=self.device
            )

            p_embeds, p_pooled = compel(prompt)
            n_embeds, n_pooled = compel(neg)

            if p_embeds.shape[1] != n_embeds.shape[1]:
                empty_embeds, _ = compel("")
                chunk_len = empty_embeds.shape[1]
                if p_embeds.shape[1] > n_embeds.shape[1]:
                    diff = p_embeds.shape[1] - n_embeds.shape[1]
                    pad = empty_embeds.repeat(1, diff // chunk_len, 1)
                    n_embeds = torch.cat([n_embeds, pad], dim=1)
                else:
                    diff = n_embeds.shape[1] - p_embeds.shape[1]
                    pad = empty_embeds.repeat(1, diff // chunk_len, 1)
                    p_embeds = torch.cat([p_embeds, pad], dim=1)

            del compel
            return p_embeds, p_pooled, n_embeds, n_pooled

        return None, None, None, None

    def generate(
        self,
        prompt: str,
        negative_prompt: str = None,
        target_dir=None,
        metadata: dict = None,
        enable_face_swap: bool = None,
        source_face_path: str | Path = None,
        width: int = None,
        height: int = None,
        num_inference_steps: int = None,
        guidance_scale: float = None
    ) -> str | None:
        model_path = self._resolve_model_path()
        if not model_path or not model_path.exists():
            logger.error("[ImageGen] SDXL checkpoint file not found.")
            return None

        # Resolve generation parameters from config if not explicitly passed
        target_width = width or getattr(config, "SD_WIDTH", 1024)
        target_height = height or getattr(config, "SD_HEIGHT", 1024)
        steps = num_inference_steps or getattr(config, "SD_STEPS", 25)
        scale = guidance_scale or getattr(config, "SD_GUIDANCE_SCALE", 6.0)
        should_swap = getattr(config, "ENABLE_FACE_SWAP", True) if enable_face_swap is None else enable_face_swap

        with gpu_vram_lock:
            pipe = None
            start_time = time.time()
            try:
                self._unload_ollama()

                logger.info(f"[ImageGen] Loading '{model_path.name}' on {self.device}...")

                pipe = StableDiffusionXLPipeline.from_single_file(
                    str(model_path),
                    torch_dtype=torch.float16,
                    use_safetensors=True,
                    local_files_only=True
                ).to(self.device)

                if hasattr(pipe, "enable_vae_tiling"):
                    pipe.enable_vae_tiling()

                # Dynamic parameters passed into SDXL pipeline
                gen_kwargs = {
                    "width": target_width,
                    "height": target_height,
                    "num_inference_steps": steps,
                    "guidance_scale": scale
                }

                if COMPEL_SDXL_AVAILABLE or COMPEL_AVAILABLE:
                    p_embeds, p_pooled, n_embeds, n_pooled = self._encode_prompts(
                        pipe=pipe,
                        prompt=prompt,
                        negative_prompt=negative_prompt
                    )
                    gen_kwargs.update({
                        "prompt_embeds": p_embeds,
                        "pooled_prompt_embeds": p_pooled,
                        "negative_prompt_embeds": n_embeds,
                        "negative_pooled_prompt_embeds": n_pooled
                    })
                else:
                    gen_kwargs.update({"prompt": prompt, "negative_prompt": negative_prompt})

                logger.info(f"[ImageGen] Generating scene ({target_width}x{target_height}, {steps} steps, CFG {scale}): '{prompt[:60]}...'")
                result = pipe(**gen_kwargs)
                image = result.images[0]

                # Clear SDXL from VRAM before face swap & GFPGAN
                del pipe
                pipe = None
                gc.collect()
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()

                # Swap & Restore
                swapped = False
                if should_swap:
                    image, swapped = self._apply_face_swap(image, source_face_path=source_face_path)

                save_dir = Path(target_dir) if target_dir else self.output_dir
                save_dir.mkdir(parents=True, exist_ok=True)

                timestamp = time.strftime("%Y%m%d-%H%M%S")
                prefix = "scene_swap" if swapped else "scene"
                file_path = save_dir / f"{prefix}_{timestamp}.png"
                image.save(file_path)

                meta = dict(metadata or {})
                meta["face_swapped"] = swapped
                meta["resolution"] = f"{target_width}x{target_height}"
                meta["steps"] = steps
                meta["cfg"] = scale
                self._log_generation(file_path, prompt, negative_prompt, meta=meta)

                logger.info(f"[ImageGen] Completed in {time.time() - start_time:.2f}s -> {file_path.name}")
                return str(file_path)

            except Exception as e:
                logger.error(f"[ImageGen] Generation failed: {e}", exc_info=True)
                return None

            finally:
                if pipe is not None:
                    del pipe
                gc.collect()
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()

                self._warmup_ollama_async()
