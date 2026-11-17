# modules/media_processor.py

import json
import logging
import os
import shutil
import urllib.request
from pathlib import Path
from typing import List, Optional

from PIL import Image
import imageio.v2 as imageio

try:
    import rawpy
    HAS_RAWPY = True
except ImportError:
    HAS_RAWPY = False

try:
    import pyexiv2
    HAS_PYEXIV2 = True
except ImportError:
    HAS_PYEXIV2 = False

try:
    import ollama
    HAS_OLLAMA_LIB = True
except ImportError:
    HAS_OLLAMA_LIB = False

from modules.config import config

logger = logging.getLogger("Calypso.Media")


class MediaProcessor:
    def __init__(self, base_dir=None, model: Optional[str] = None):
        self.base_dir = Path(base_dir) if base_dir else config.INPUT_DIR
        self.output_dir = config.IMAGES_OUTPUT_DIR
        cfg_vision = getattr(config, "VISION_MODEL", "")
        cfg_model = getattr(config, "MODEL_NAME", "")        
        
        resolved_model = ""
        for candidate in [model, cfg_vision, cfg_model, "llava"]:
            if candidate and isinstance(candidate, str) and candidate.strip():
                resolved_model = candidate.strip()
                break

        self.model = resolved_model

        self.raster_extensions = {'.jpg', '.jpeg', '.png', '.webp', '.bmp', '.tiff', '.tif'}
        self.camera_raw_extensions = {'.cr2', '.cr3', '.nef', '.arw', '.dng', '.orf', '.rw2', '.pef', '.raw'}
        self.supported_extensions = self.raster_extensions | self.camera_raw_extensions

        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _get_unique_path(self, target_path: Path) -> Path:
        if not target_path.exists():
            return target_path
        stem = target_path.stem
        suffix = target_path.suffix
        parent = target_path.parent
        counter = 1
        while True:
            candidate = parent / f"{stem}_{counter}{suffix}"
            if not candidate.exists():
                return candidate
            counter += 1

    def convert_raw_to_rgb(self, image_path: Path) -> Optional[Path]:
        if not HAS_RAWPY:
            logger.warning("[Media] rawpy is not installed. Cannot process RAW camera files.")
            return None

        temp_img = config.WORKSPACE_DIR / f"temp_{image_path.stem}.jpg"
        config.WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
        try:
            with rawpy.imread(str(image_path)) as raw:
                rgb = raw.postprocess(use_camera_wb=True, no_auto_bright=False)
                imageio.imwrite(str(temp_img), rgb, quality=92)
            return temp_img
        except Exception as e:
            logger.error(f"[Media] Error converting RAW {image_path.name}: {e}")
            return None

    def tag_image(self, image_path: Path, tags) -> bool:
        """Injects descriptive tags into XMP metadata for DigiKam / Lightroom."""
        if not HAS_PYEXIV2:
            logger.warning("[Media] pyexiv2 not installed. Skipping XMP metadata write.")
            return False

        try:
            if isinstance(tags, str):
                tag_list = [t.strip() for t in tags.split(',') if t.strip()]
            else:
                tag_list = list(tags)

            with pyexiv2.Image(str(image_path)) as img:
                xmp = img.read_xmp()
                xmp['Xmp.dc.subject'] = tag_list
                img.modify_xmp(xmp)
            logger.info(f"[Media] Tagged {image_path.name} with: {tag_list}")
            return True
        except Exception as e:
            logger.warning(f"[Media] Metadata injection failed for {image_path.name}: {e}")
            return False

    def _resolve_active_model(self) -> str:
        cfg_vision = getattr(config, "VISION_MODEL", "")
        cfg_model = getattr(config, "MODEL_NAME", "")
        for candidate in [cfg_vision, self.model if self.model != "llava" else "", cfg_model, self.model, "llava"]:
            if candidate and isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
        return "llava"

    def run_analysis(self, image_path: Path, mode: str = 'describe', context_hint: str = "") -> str:
        """
        Analyzes an image using Ollama Vision models.
        Modes:
          - 'describe': natural language scene comprehension
          - 'tag': comma-separated tags (injected into XMP metadata)
          - 'scrapbook': warm, first-person nostalgic scrapbook caption in Calypso's voice
        """
        image_path = Path(image_path)
        is_camera_raw = image_path.suffix.lower() in self.camera_raw_extensions
        input_file = image_path
        temp_created = False

        if is_camera_raw:
            converted = self.convert_raw_to_rgb(image_path)
            if converted and converted.exists():
                input_file = converted
                temp_created = True
            else:
                return "Error: Could not convert camera RAW file."

        if mode == 'tag':
            prompt = (
                "Provide 4-7 descriptive, single-word or short tags for this photo as a comma-separated list. "
                "Output ONLY the comma-separated tags."
            )
        elif mode == 'scrapbook':
            ctx_clause = f"\nMemory context for this photo: {context_hint.strip()}" if context_hint and context_hint.strip() else ""
            prompt = (
                "You are Calypso, looking back fondly at this photo in your personal scrapbook."
                f"{ctx_clause}\n"
                "Write a warm, nostalgic, handwritten-style scrapbook caption in the first person "
                "('I remember...', 'Looking back at...', 'The way the light...') in 2-3 sentences. "
                "Focus on the visual atmosphere, emotion, and what this moment means to you. "
                "Output ONLY the caption text itself without quotation marks or meta-commentary."
            )
        else:
            prompt = (
                "Provide a vivid, concise natural language description of this image in 2-3 sentences. "
                "Focus on subjects, colors, lighting, and mood."
            )

        active_model = self._resolve_active_model()

        try:
            result_text = ""
            if HAS_OLLAMA_LIB:
                # Use python-ollama if available
                res = ollama.chat(
                    model=active_model,
                    messages=[{
                        'role': 'user',
                        'content': prompt,
                        'images': [str(input_file)]
                    }]
                )
                result_text = res.get('message', {}).get('content', '').strip()
            else:
                # Direct HTTP Fallback via config.OLLAMA_URL
                import base64
                with open(input_file, "rb") as f:
                    img_b64 = base64.b64encode(f.read()).decode("utf-8")

                payload = {
                    "model": active_model,
                    "messages": [{
                        "role": "user",
                        "content": prompt,
                        "images": [img_b64]
                    }],
                    "stream": False
                }
                req = urllib.request.Request(
                    config.OLLAMA_URL,
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"}
                )
                with urllib.request.urlopen(req, timeout=90) as response:
                    data = json.loads(response.read().decode("utf-8"))
                    result_text = data.get("message", {}).get("content", "").strip()

            if result_text:
                import re
                result_text = re.sub(r"<think>.*?(?:</think>|$)", "", result_text, flags=re.DOTALL).strip()
                result_text = result_text.strip('"').strip("'")

            if mode == 'tag' and result_text and not is_camera_raw:
                self.tag_image(image_path, result_text)

            return result_text or "No visual features detected."

        except Exception as e:
            logger.error(f"[Media] Ollama Vision analysis failed: {e}")
            return f"[Notice: Vision analysis failed: {e}]"
        finally:
            if temp_created and input_file.exists():
                try:
                    os.remove(input_file)
                except Exception:
                    pass

    def process_and_move_image(self, image_path: Path, mode: str = 'describe') -> dict:
        """Processes an image, saves analysis, and safely archives it to output."""
        analysis = self.run_analysis(image_path, mode=mode)
        dest_path = self._get_unique_path(self.output_dir / image_path.name)
        try:
            shutil.move(str(image_path), str(dest_path))
            return {
                "success": True,
                "original_name": image_path.name,
                "archived_path": str(dest_path),
                "analysis": analysis,
                "mode": mode
            }
        except Exception as e:
            logger.error(f"[Media] Failed to move {image_path.name}: {e}")
            return {
                "success": False,
                "original_name": image_path.name,
                "error": str(e),
                "analysis": analysis
            }

    def scan_input_folder(self, mode: str = 'describe') -> List[dict]:
        """Scans the entire input directory and processes all recognized images."""
        if not self.base_dir.exists():
            return []

        images = [
            f for f in self.base_dir.iterdir()
            if f.is_file() and f.suffix.lower() in self.supported_extensions
        ]

        results = []
        for img in images:
            logger.info(f"[Media] Processing staged image: {img.name}")
            res = self.process_and_move_image(img, mode=mode)
            results.append(res)
        return results
