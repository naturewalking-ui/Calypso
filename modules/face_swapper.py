# modules/face_swapper.py
import sys
import logging
from pathlib import Path
import cv2
import numpy as np
from PIL import Image
import torch
import insightface
from insightface.app import FaceAnalysis

# Compatibility fix: torchvision >= 0.15 removed functional_tensor which breaks basicsr/gfpgan
try:
    import torchvision.transforms.functional_tensor
except ImportError:
    try:
        import torchvision.transforms.functional as F
        import types
        _mod = types.ModuleType("torchvision.transforms.functional_tensor")
        _mod.rgb_to_grayscale = F.rgb_to_grayscale
        sys.modules["torchvision.transforms.functional_tensor"] = _mod
    except Exception:
        pass

# Import GFPGAN
try:
    from gfpgan import GFPGANer
    GFPGAN_AVAILABLE = True
except ImportError:
    GFPGAN_AVAILABLE = False

logger = logging.getLogger("Calypso.FaceSwapper")


class FaceSwapper:
    def __init__(self, model_path: str, target_gpu: int = 0, restorer_path: str | Path = None):
        self.model_path = str(model_path)
        self.ctx_id = target_gpu if target_gpu >= 0 else -1
        self.device = torch.device(f"cuda:{self.ctx_id}" if self.ctx_id >= 0 and torch.cuda.is_available() else "cpu")
        
        # 1. Detection & Recognition App (Buffalo_l)
        logger.info(f"[FaceSwapper] Initializing Buffalo_l on GPU {self.ctx_id}...")
        self.app = FaceAnalysis(name='buffalo_l', providers=['CUDAExecutionProvider', 'CPUExecutionProvider'])
        self.app.prepare(ctx_id=self.ctx_id, det_size=(640, 640))
        
        # 2. Inswapper Model
        logger.info(f"[FaceSwapper] Loading Inswapper from {self.model_path}...")
        self.swapper = insightface.model_zoo.get_model(
            self.model_path,
            download=False,
            providers=['CUDAExecutionProvider', 'CPUExecutionProvider']
        )
        self._source_face_cache = {}

        # 3. Optional Face Restoration (GFPGAN)
        self.restorer = None
        if restorer_path and Path(restorer_path).is_file():
            self._init_restorer(restorer_path)

    def _init_restorer(self, restorer_path: str | Path):
        if not GFPGAN_AVAILABLE:
            logger.warning("[FaceSwapper] gfpgan library not installed. Run 'pip install gfpgan facexlib'.")
            return

        try:
            logger.info(f"[FaceSwapper] Initializing GFPGAN face restoration ({Path(restorer_path).name})...")
            # upscale=1 ensures the canvas resolution is preserved while enhancing the face to 512x512
            try:
                self.restorer = GFPGANer(
                    model_path=str(restorer_path),
                    upscale=1,
                    arch='clean',
                    channel_multiplier=2,
                    bg_upsampler=None,
                    device=self.device
                )
            except TypeError:
                # Older GFPGANer versions without explicit device argument
                self.restorer = GFPGANer(
                    model_path=str(restorer_path),
                    upscale=1,
                    arch='clean',
                    channel_multiplier=2,
                    bg_upsampler=None
                )
            logger.info("[FaceSwapper] GFPGAN ready.")
        except Exception as e:
            logger.error(f"[FaceSwapper] Failed to load GFPGAN: {e}", exc_info=True)
            self.restorer = None

    def get_face(self, bgr_img):
        faces = self.app.get(bgr_img)
        if not faces:
            return None
        # Return the largest face detected
        return sorted(faces, key=lambda x: (x.bbox[2]-x.bbox[0]) * (x.bbox[3]-x.bbox[1]), reverse=True)[0]

    def swap_face(
        self,
        target_image: Image.Image,
        source_image_path: str | Path,
        restore: bool = True
    ) -> Image.Image:
        source_path = str(source_image_path)
        
        # 1. Load and cache source face embedding
        if source_path not in self._source_face_cache:
            src_bgr = cv2.imread(source_path)
            if src_bgr is None:
                raise ValueError(f"Could not read source face image at {source_path}")
            src_face = self.get_face(src_bgr)
            if not src_face:
                raise ValueError(f"No face detected in source reference {source_path}")
            self._source_face_cache[source_path] = src_face
        
        source_face = self._source_face_cache[source_path]

        # 2. Detect face in target image
        target_bgr = cv2.cvtColor(np.array(target_image), cv2.COLOR_RGB2BGR)
        target_faces = self.app.get(target_bgr)

        if not target_faces:
            logger.info("[FaceSwapper] No face detected in generated image. Returning original.")
            return target_image

        # 3. Apply Inswapper
        for face in target_faces:
            target_bgr = self.swapper.get(target_bgr, face, source_face, paste_back=True)

        # 4. Apply GFPGAN Face Restoration (Upscale & reconstruct high-frequency details)
        if restore and self.restorer is not None:
            try:
                logger.info("[FaceSwapper] Applying GFPGAN face restoration pass...")
                # cropped_faces, restored_faces, restored_img
                _, _, restored_bgr = self.restorer.enhance(
                    target_bgr,
                    has_aligned=False,
                    only_center_face=False,
                    paste_back=True
                )
                target_bgr = restored_bgr
            except Exception as e:
                logger.warning(f"[FaceSwapper] Face restoration pass failed ({e}), using raw swap.")

        # Convert back to PIL
        result_rgb = cv2.cvtColor(target_bgr, cv2.COLOR_BGR2RGB)
        return Image.fromarray(result_rgb)
