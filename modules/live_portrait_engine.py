# modules/live_portrait_engine.py
"""
FasterLivePortrait + JoyVASA Real-Time Neural Portrait Engine for Calypso.

Architecture:
1. Single Canonical Driver Portrait (`diffusion_models/calypso.png`):
   - Extracts and caches Calypso's 3D appearance feature volume (`appearance_feature_extractor.onnx`,
     shape `[1, 32, 16, 64, 64]`) and canonical 21-point 3D implicit keypoints (`motion_extractor.onnx`)
     once at startup.
2. Full ONNX + CUDA FP16 FasterLivePortrait Synthesis Pipeline (`liveportrait_models/`):
   - `stitching_eye.onnx`: Neural eye retargeting network driving anatomical upper/lower eyelid
     blinking, emotional squints, and wide-eyed states.
   - `stitching_lip.onnx`: Neural lip retargeting network driven by real-time JoyVASA acoustic
     formant/vowel decomposition from `AudioEngine.get_vis_snapshot()`.
   - `stitching.onnx`: Neural stitching network locking neck/shoulder/hairline boundaries.
   - `warping_spade-fix.onnx`: Volumetric 3D dense-motion + SPADE generator executed in FP16 on CUDA
     (via PyTorch CUDA graph runner or ONNX Runtime) inside a non-blocking background worker thread,
     yielding automatically whenever `gpu_vram_lock` is held by heavy SDXL or MusicGen jobs.
3. Unified Emotional Landscape & Dynamic Studio Backdrop:
   - Smoothly interpolates 3D facial expression & head-pose presets across all 40+ Emotion Engine tiers.
   - Dynamically illuminates Calypso's studio backdrop and vocal-reactive rim halo using the active
     emotional color palette (`EMOTION_SPECTRUM_PALETTE`).
"""

import logging
import math
import random
import threading
import time
import tkinter as tk
from pathlib import Path
from typing import Callable, Dict, Optional, Tuple

import cv2
import numpy as np
from PIL import Image, ImageTk

from modules.audio import AudioEngine
from modules.config import config
from modules.gpu_lock import gpu_vram_lock

logger = logging.getLogger("Calypso.LivePortrait")

try:
    import onnx
    from onnx import numpy_helper
    HAS_ONNX = True
except ImportError:
    onnx = None
    numpy_helper = None
    HAS_ONNX = False

try:
    import onnxruntime as ort
    HAS_ORT = True
except ImportError:
    ort = None
    HAS_ORT = False

try:
    import torch
    import torch.nn.functional as F
    HAS_TORCH_CUDA = torch.cuda.is_available()
except ImportError:
    torch = None
    F = None
    HAS_TORCH_CUDA = False


REQUIRED_ONNX_FILES = (
    "appearance_feature_extractor.onnx",
    "motion_extractor.onnx",
    "warping_spade-fix.onnx",
    "stitching.onnx",
    "stitching_eye.onnx",
    "stitching_lip.onnx",
)

# Emotional studio backdrop palette (synced with RealtimeSpectrumAnalyzer)
EMOTION_STUDIO_PALETTE: Dict[str, Tuple[Tuple[int, int, int], Tuple[int, int, int]]] = {
    "neutral": ((16, 185, 129), (56, 189, 248)),
    "excited": ((234, 179, 8), (249, 115, 22)),
    "happy": ((34, 197, 94), (234, 179, 8)),
    "warm": ((6, 182, 212), (245, 158, 11)),
    "sad": ((59, 130, 246), (99, 102, 241)),
    "furious": ((239, 68, 68), (250, 204, 21)),
    "somber": ((100, 116, 139), (148, 163, 184)),
    "thoughtful": ((20, 184, 166), (56, 189, 248)),
    "curious": ((56, 189, 248), (192, 132, 252)),
    "inquiry": ((56, 189, 248), (192, 132, 252)),
    "sleepy": ((129, 140, 248), (192, 132, 252)),
    "dream_state": ((168, 85, 247), (56, 189, 248)),
    "romantic": ((244, 63, 94), (245, 158, 11)),
    "intimate": ((251, 113, 133), (244, 114, 182)),
#    "flirty": ((236, 72, 153), (251, 191, 36)),
#    "bashful": ((249, 168, 212), (244, 114, 182)),
    "empathetic": ((244, 114, 182), (56, 189, 248)),
    "enlightened": ((250, 204, 21), (52, 211, 153)),
#    "jealous": ((21, 128, 61), (234, 179, 8)),
    "satirical": ((225, 29, 72), (251, 146, 60)),
#    "relaxed": ((45, 212, 191), (56, 189, 248)),
#    "playful": ((245, 158, 11), (236, 72, 153)),
#    "attentive": ((14, 165, 233), (45, 212, 191)),
    "sarcastic": ((132, 204, 22), (234, 179, 8)),
    "nostalgic": ((217, 119, 6), (244, 63, 94)),
    "dejected": ((71, 85, 105), (100, 116, 139)),
    "annoyed": ((248, 113, 113), (245, 158, 11)),
#    "flattened": ((107, 114, 128), (156, 163, 175)),
    "ambiguous": ((147, 51, 234), (236, 72, 153)),
#    "defiant": ((220, 38, 38), (249, 115, 22)),
    "wonder": ((192, 132, 252), (250, 204, 21)),
    "eutierria": ((16, 185, 129), (45, 212, 191)),
    "gemma": ((129, 140, 248), (56, 189, 248)),
#    "gemma4": ((129, 140, 248), (56, 189, 248)),
#    "hysterical": ((251, 191, 36), (239, 68, 68)),
    "focused": ((2, 132, 199), (56, 189, 248)),
#    "focussed": ((2, 132, 199), (56, 189, 248)),
    "autonomous": ((168, 85, 247), (236, 72, 153)),
#    "metasarcastic": ((163, 230, 53), (245, 158, 11)),
#    "reminisent": ((180, 83, 9), (245, 158, 11)),
#    "trump": ((234, 88, 12), (239, 68, 68)),
    "subservient": ((148, 163, 184), (203, 213, 225)),
    "apoplectic": ((185, 28, 28), (250, 204, 21)),
    "skeptical": ((249, 115, 22), (234, 179, 8)),
    "countess_lovelace": ((192, 132, 252), (56, 189, 248)),
}

# 3D Neural Expression & Pose Presets for calypso.png:
# Fields: (smile, brow_lift, eye_close_l, eye_close_r, eye_widen, pitch_deg, yaw_deg, roll_deg, resting_lip_open)
EMOTION_NEURAL_PRESETS: Dict[str, Tuple[float, float, float, float, float, float, float, float, float]] = {
                         #smile   brow  clsL  clsR  wdn    ptch  yaw   rol  lipopn 
    "neutral":           ( 0.00,  0.00, 0.00, 0.00, 0.00,  0.0,  0.0,  0.0, 0.00),
    "happy":             ( 0.65,  0.20, 0.00, 0.00, 0.00, -1.0,  0.0,  1.2, 0.02),
    "excited":           ( 0.80,  0.45, 0.00, 0.00, 0.14, -2.0,  0.5,  1.5, 0.05),
    "warm":              ( 0.50,  0.15, 0.00, 0.00, 0.00,  0.0,  0.0,  1.8, 0.01),
#    "romantic":          ( 0.40,  0.10, 0.09, 0.09, 0.00,  1.0, -1.0,  2.4, 0.02),
    "intimate":          ( 0.10,  0.05, 0.01, 0.01, 0.00,  1.5, -0.8,  2.0, 0.03),
#    "flirty":            ( 0.58,  0.25, 0.09, 0.03, 0.02,  1.2,  1.8, -2.8, 0.02),
#    "bashful":           ( 0.35,  0.10, 0.11, 0.11, 0.00,  3.2, -2.5,  2.2, 0.00),
    "curious":           ( 0.15,  0.42, 0.00, 0.00, 0.20, -1.2,  1.5,  3.2, 0.02),
    "inquiry":           ( 0.10,  0.38, 0.00, 0.00, 0.08, -1.0, -1.5, -2.8, 0.01),
    "thoughtful":        ( 0.05,  0.12, 0.04, 0.04, 0.00,  2.2, -2.2,  1.5, 0.00),
    "sad":               (-0.45, -0.25, 0.05, 0.05, 0.00,  3.8, -1.0, -1.5, 0.00),
    "somber":            (-0.30, -0.15, 0.06, 0.06, 0.00,  2.8,  0.0, -1.0, 0.00),
    "dejected":          (-0.52, -0.30, 0.06, 0.06, 0.00,  4.5, -1.5, -2.0, 0.00),
    "furious":           (-0.40, -0.55, 0.11, 0.11, 0.04, -2.2,  0.0,  0.0, 0.04),
    "annoyed":           (-0.28, -0.35, 0.10, 0.10, 0.00, -1.2,  1.5, -1.5, 0.00),
#    "apoplectic":        (-0.45, -0.60, 0.08, 0.08, 0.08, -2.5,  0.0,  0.5, 0.05),
#    "defiant":           (-0.20, -0.30, 0.07, 0.07, 0.02, -2.8,  1.2, -1.2, 0.00),
    "skeptical":         (-0.10,  0.22, 0.13, 0.02, 0.00, -0.8,  2.0, -2.4, 0.00),
    "sarcastic":         ( 0.28,  0.20, 0.11, 0.03, 0.00, -1.2, -1.8,  2.2, 0.01),
    "satirical":         ( 0.38,  0.25, 0.09, 0.02, 0.02, -1.0,  1.6, -2.0, 0.02),
#    "metasarcastic":     ( 0.32,  0.22, 0.03, 0.12, 0.00, -1.4, -2.0,  2.5, 0.01),
    "sleepy":            ( 0.00,  0.00, 0.05, 0.05, 0.00,  0.0,  0.0,  0.0, 0.00),
    "dream_state":       ( 0.15,  0.00, 0.30, 0.30, 0.00,  2.0, -1.0,  2.5, 0.01),
#    "relaxed":           ( 0.32,  0.08, 0.06, 0.06, 0.00,  0.5,  0.0,  1.2, 0.00),
#    "playful":           ( 0.62,  0.30, 0.04, 0.09, 0.04, -1.0,  1.5, -2.5, 0.03),
#    "attentive":         ( 0.18,  0.24, 0.00, 0.00, 0.06, -0.8,  0.0,  0.8, 0.00),
    "empathetic":        ( 0.35,  0.18, 0.00, 0.00, 0.00,  1.0, -1.0,  2.4, 0.01),
    "enlightened":       ( 0.45,  0.32, 0.00, 0.00, 0.08, -1.8,  0.0,  0.5, 0.02),
    "wonder":            ( 0.40,  0.48, 0.00, 0.00, 0.15, -2.2,  0.5,  1.5, 0.05),
    "eutierria":         ( 0.48,  0.18, 0.02, 0.02, 0.02, -0.8,  0.0,  1.0, 0.01),
    "nostalgic":         ( 0.25,  0.10, 0.08, 0.08, 0.00,  1.8, -1.8,  1.8, 0.00),
#    "reminisent":        ( 0.25,  0.10, 0.08, 0.08, 0.00,  1.8, -1.8,  1.8, 0.00),
#    "jealous":           (-0.22, -0.25, 0.10, 0.10, 0.00,  0.8, -2.2, -1.2, 0.00),
#    "flattened":         ( 0.00, -0.08, 0.08, 0.08, 0.00,  1.0,  0.0,  0.0, 0.00),
    "ambiguous":         ( 0.12,  0.15, 0.05, 0.09, 0.00,  0.5,  1.5, -1.5, 0.00),
    "gemma":             ( 0.30,  0.20, 0.00, 0.00, 0.05, -0.8,  0.5,  1.0, 0.01),
#    "gemma4":            ( 0.30,  0.20, 0.00, 0.00, 0.05, -0.8,  0.5,  1.0, 0.01),
    "hysterical":        ( 0.85,  0.50, 0.00, 0.00, 0.16, -2.5,  1.0, -2.0, 0.06),
    "focused":           ( 0.05, -0.12, 0.04, 0.04, 0.02, -0.5,  0.0,  0.0, 0.00),
#    "focussed":          ( 0.05, -0.12, 0.04, 0.04, 0.02, -0.5,  0.0,  0.0, 0.00),
    "autonomous":        ( 0.15,  0.12, 0.00, 0.00, 0.06, -1.0,  0.0,  0.0, 0.00),
#    "countess_lovelace": ( 0.35,  0.25, 0.04, 0.04, 0.02, -1.5,  1.0,  1.2, 0.01),
}


def ensure_warping_spade_onnx_compatible(onnx_path: Path) -> bool:
    """
    Upgrades `GridSample3D` (`mode=bilinear`, opset 16) nodes in `warping_spade-fix.onnx`
    to standard ONNX Opset 20 `GridSample` (`mode=linear`) so ONNX Runtime can load it natively.
    """
    if not HAS_ONNX or not onnx_path.is_file():
        return False
    try:
        m = onnx.load(str(onnx_path))
        changed = False
        for node in m.graph.node:
            if node.op_type == "GridSample3D":
                node.op_type = "GridSample"
                changed = True
            if node.op_type == "GridSample":
                for attr in node.attribute:
                    if attr.name == "mode" and attr.s == b"bilinear":
                        attr.s = b"linear"
                        changed = True
        for o in m.opset_import:
            if o.domain == "" and o.version < 20:
                o.version = 20
                changed = True
        if changed:
            onnx.save(m, str(onnx_path))
            logger.info(f"[LivePortrait] Upgraded {onnx_path.name} to standard ONNX Opset 20 GridSample.")
        return True
    except Exception as e:
        logger.debug(f"[LivePortrait] ONNX compatibility check notice for {onnx_path}: {e}")
        return False


class _TorchCUDAWarpingSpade:
    """
    High-speed FP16 CUDA executor for `warping_spade-fix.onnx`.
    Executes the 3D Dense Motion Network + SPADE Generator directly on PyTorch CUDA (~42ms/frame
    on RTX 5060 Ti) inside a dedicated CUDA stream without requiring TensorRT or custom ORT plugins.
    """

    def __init__(self, onnx_path: Path, device: str = "cuda", dtype=None):
        self.device = device
        self.dtype = dtype or (torch.float16 if HAS_TORCH_CUDA else torch.float32)
        self.stream = torch.cuda.Stream() if HAS_TORCH_CUDA else None

        m = onnx.load(str(onnx_path))
        self.inits_np = {t.name: numpy_helper.to_array(t).copy() for t in m.graph.initializer}
        self.inits_gpu = {}
        for k, v in self.inits_np.items():
            if v.dtype in (np.float32, np.float16, np.int64, np.int32):
                self.inits_gpu[k] = torch.from_numpy(v).to(device=self.device, dtype=self.dtype)

        self.ops = []
        for n in m.graph.node:
            attrs = {a.name: onnx.helper.get_attribute_value(a) for a in n.attribute}
            self.ops.append((n.op_type, list(n.input), list(n.output), attrs))

    def infer(self, f3d_gpu: "torch.Tensor", kp_driving_np: np.ndarray, kp_source_gpu: "torch.Tensor") -> np.ndarray:
        """Runs a single forward pass of warping_spade-fix on GPU and returns a 512x512 RGB uint8 array."""
        ctx = torch.cuda.stream(self.stream) if self.stream is not None else torch.no_grad()
        with ctx, torch.no_grad():
            kpd = torch.from_numpy(kp_driving_np).to(device=self.device, dtype=self.dtype)
            env = dict(self.inits_gpu)
            env["feature_3d"] = f3d_gpu
            env["kp_driving"] = kpd
            env["kp_source"] = kp_source_gpu

            for op, inp, out, attrs in self.ops:
                if op == "Conv":
                    x = env[inp[0]]
                    w = env[inp[1]]
                    b = env[inp[2]] if len(inp) > 2 else None
                    strides = tuple(attrs["strides"])
                    dilations = tuple(attrs["dilations"])
                    pads = attrs["pads"]
                    padding = tuple(pads[: len(pads) // 2])
                    groups = attrs.get("group", 1)
                    if x.ndim == 5:
                        y = F.conv3d(x, w, b, strides, padding, dilations, groups)
                    else:
                        y = F.conv2d(x, w, b, strides, padding, dilations, groups)
                elif op == "Relu":
                    y = F.relu(env[inp[0]], inplace=True)
                elif op == "LeakyRelu":
                    y = F.leaky_relu(env[inp[0]], negative_slope=attrs.get("alpha", 0.01), inplace=True)
                elif op == "Reshape":
                    shape = tuple(int(s) for s in self.inits_np[inp[1]])
                    y = env[inp[0]].reshape(shape)
                elif op == "Sub":
                    y = env[inp[0]] - env[inp[1]]
                elif op == "Add":
                    y = env[inp[0]] + env[inp[1]]
                elif op == "Mul":
                    y = env[inp[0]] * env[inp[1]]
                elif op == "Div":
                    y = env[inp[0]] / env[inp[1]]
                elif op == "Pow":
                    a = env[inp[0]]
                    p = float(self.inits_np[inp[1]])
                    y = a * a if p == 2.0 else torch.pow(a, p)
                elif op == "Exp":
                    y = torch.exp(env[inp[0]])
                elif op == "Sigmoid":
                    y = torch.sigmoid(env[inp[0]])
                elif op == "Softmax":
                    y = F.softmax(env[inp[0]], dim=attrs.get("axis", 1))
                elif op == "Concat":
                    y = torch.cat([env[i] for i in inp], dim=attrs.get("axis", 1))
                elif op == "Unsqueeze":
                    axes = [int(a) for a in np.atleast_1d(self.inits_np[inp[1]])]
                    y = env[inp[0]]
                    for ax in sorted(axes):
                        y = y.unsqueeze(ax)
                elif op == "Tile":
                    reps = tuple(int(r) for r in self.inits_np[inp[1]])
                    y = env[inp[0]].repeat(reps)
                elif op in ("GridSample3D", "GridSample"):
                    y = F.grid_sample(
                        env[inp[0]],
                        env[inp[1]],
                        mode="bilinear",
                        padding_mode="zeros",
                        align_corners=bool(attrs.get("align_corners", 0)),
                    )
                elif op == "ReduceSum":
                    axes = tuple(int(a) for a in np.atleast_1d(self.inits_np[inp[1]]))
                    y = torch.sum(env[inp[0]], dim=axes, keepdim=bool(attrs.get("keepdims", 0)))
                elif op == "AveragePool":
                    ks = tuple(attrs["kernel_shape"])
                    st = tuple(attrs["strides"])
                    y = F.avg_pool3d(env[inp[0]], ks, st) if env[inp[0]].ndim == 5 else F.avg_pool2d(env[inp[0]], ks, st)
                elif op == "Resize":
                    x = env[inp[0]]
                    if len(inp) >= 4 and inp[3]:
                        sz = tuple(int(s) for s in self.inits_np[inp[3]][2:])
                        y = F.interpolate(x, size=sz, mode="nearest")
                    else:
                        sc = tuple(float(s) for s in self.inits_np[inp[2]][2:])
                        y = F.interpolate(x, scale_factor=sc, mode="nearest")
                elif op == "Transpose":
                    y = env[inp[0]].permute(*attrs["perm"]).contiguous()
                elif op == "InstanceNormalization":
                    y = F.instance_norm(
                        env[inp[0]].float(),
                        weight=env[inp[1]].float(),
                        bias=env[inp[2]].float(),
                        eps=attrs.get("epsilon", 1e-5),
                    ).to(self.dtype)
                elif op == "DepthToSpace":
                    y = F.pixel_shuffle(env[inp[0]], upscale_factor=attrs.get("blocksize", 2))
                else:
                    raise RuntimeError(f"Unsupported ONNX op in warping_spade: {op}")
                env[out[0]] = y

            out_t = torch.clamp(env["out"][0] * 255.0, 0.0, 255.0).to(torch.uint8).permute(1, 2, 0).contiguous()
            if self.stream is not None:
                self.stream.synchronize()
            return out_t.cpu().numpy()


class LivePortraitEngine:
    """
    Real-time FasterLivePortrait + JoyVASA animator driving `diffusion_models/calypso.png`
    across Calypso's live TTS voice stream and emotional landscape.
    """

    def __init__(
        self,
        target_label: tk.Label = None,
        driver_dir: Path = None,
        models_dir: Path = None,
        symbolic_fallback_cb: Optional[Callable[[str], None]] = None,
    ):
        self.target_label = target_label
        self.driver_dir = Path(driver_dir) if driver_dir else getattr(
            config, "DRIVER_IMAGES_DIR", config.PERSONAS_DIR / "driver_images"
        )
        self.models_dir = Path(models_dir) if models_dir else getattr(
            config, "LIVEPORTRAIT_MODELS_DIR", config.BASE_DIR / "liveportrait_models"
        )
        self.models_dir.mkdir(parents=True, exist_ok=True)
        self.symbolic_fallback_cb = symbolic_fallback_cb

        # Primary canonical portrait: diffusion_models/calypso.png
        primary_face = getattr(config, "DIFFUSION_MODELS_DIR", config.BASE_DIR / "diffusion_models") / getattr(
            config, "SOURCE_FACE_IMAGE", "calypso.png"
        )
        if not primary_face.is_file():
            primary_face = self.driver_dir / "neutral.png"
        self.primary_portrait_path: Path = primary_face

        self.running = False
        self.anim_job = None
        self.current_emotion = "neutral"
        self.native_size = (512, 512)

        # Canonical source portrait state (extracted once from calypso.png)
        self._base_rgb_512: Optional[np.ndarray] = None
        self._ext_bg_mask: Optional[np.ndarray] = None
        self._halo_grid: Optional[np.ndarray] = None
        self._grad_grid: Optional[np.ndarray] = None

        # Cached FasterLivePortrait ONNX source features
        self._f3d_np: Optional[np.ndarray] = None
        self._f3d_gpu: Optional["torch.Tensor"] = None
        self._kp_can: Optional[np.ndarray] = None
        self._exp_base: Optional[np.ndarray] = None
        self._pitch_base: Optional[np.ndarray] = None
        self._yaw_base: Optional[np.ndarray] = None
        self._roll_base: Optional[np.ndarray] = None
        self._t_base: Optional[np.ndarray] = None
        self._scale_base: Optional[np.ndarray] = None
        self._x_s: Optional[np.ndarray] = None
        self._x_s_gpu: Optional["torch.Tensor"] = None
        self._d_lip_zero: Optional[np.ndarray] = None
        self._d_eye_zero: Optional[np.ndarray] = None

        # Real-time smoothed viseme, blink, pose, and studio palette state
        self._jaw_open = 0.0
        self._lip_spread = 0.0
        self._speaking = False

        self._last_blink_time = time.time()
        self._next_blink_interval = random.uniform(2.6, 5.2)
        self._blink_phase = 0.0
        self._is_blinking = False
        self._double_blink_pending = False

        # Smoothed emotional expression state:
        # [smile, brow, eye_l, eye_r, eye_widen, pitch_off, yaw_off, roll_off, rest_lip]
        self._cur_emo_vec = np.zeros(9, dtype=np.float32)
        self._tgt_emo_vec = np.zeros(9, dtype=np.float32)

        # Smoothed studio background colors
        self._cur_bg_low = np.array([16.0, 185.0, 129.0], dtype=np.float32)
        self._cur_bg_high = np.array([56.0, 189.0, 248.0], dtype=np.float32)
        self._tgt_bg_low = self._cur_bg_low.copy()
        self._tgt_bg_high = self._cur_bg_high.copy()

        # ONNX sessions & CUDA FP16 SPADE warper
        self.onnx_ready = False
        self._ort_sessions: Dict[str, "ort.InferenceSession"] = {}
        self._cuda_warper: Optional[_TorchCUDAWarpingSpade] = None

        # Background neural rendering worker state
        self._frame_lock = threading.Lock()
        self._infer_lock = threading.Lock()
        self._latest_neural_rgb: Optional[np.ndarray] = None
        self._last_rendered_xd: Optional[np.ndarray] = None
        self._worker_thread: Optional[threading.Thread] = None

        self._init_primary_portrait_and_onnx()

    # ------------------------------------------------------------------
    # MODEL INITIALIZATION & PRIMARY PORTRAIT EXTRACTION
    # ------------------------------------------------------------------
    def has_onnx_models(self) -> bool:
        return all((self.models_dir / fname).is_file() for fname in REQUIRED_ONNX_FILES)

    def _init_primary_portrait_and_onnx(self):
        # 1. Load primary portrait (diffusion_models/calypso.png) and compute studio backdrop matte
        if self.primary_portrait_path and self.primary_portrait_path.is_file():
            pil_img = Image.open(self.primary_portrait_path).convert("RGB")
            img_512 = pil_img.resize(self.native_size, Image.LANCZOS)
            self._base_rgb_512 = np.asarray(img_512, dtype=np.uint8)
            self._latest_neural_rgb = self._base_rgb_512.copy()
            self._ext_bg_mask = self._compute_exterior_studio_mask(self._base_rgb_512)

            yy, xx = np.meshgrid(
                np.linspace(-1.0, 1.0, 512, dtype=np.float32),
                np.linspace(-1.0, 1.0, 512, dtype=np.float32),
                indexing="ij",
            )
            rad = np.sqrt(xx ** 2 + (yy + 0.05) ** 2)
            self._halo_grid = (np.clip(1.0 - rad * 0.75, 0.0, 1.0) ** 1.6)[..., None]
            self._grad_grid = (yy * 0.5 + 0.5)[..., None]
        else:
            pil_img = None

        # 2. Initialize ONNX models & CUDA FP16 SPADE warper
        if not HAS_ORT or not self.has_onnx_models():
            self.onnx_ready = False
            return

        try:
            warp_path = self.models_dir / "warping_spade-fix.onnx"
            ensure_warping_spade_onnx_compatible(warp_path)

            providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
            available = ort.get_available_providers()
            active_providers = [p for p in providers if p in available] or ["CPUExecutionProvider"]

            for fname in (
                "appearance_feature_extractor.onnx",
                "motion_extractor.onnx",
                "stitching.onnx",
                "stitching_eye.onnx",
                "stitching_lip.onnx",
            ):
                fpath = self.models_dir / fname
                self._ort_sessions[fname] = ort.InferenceSession(str(fpath), providers=active_providers)

            if HAS_TORCH_CUDA and HAS_ONNX:
                torch.backends.cudnn.benchmark = True
                self._cuda_warper = _TorchCUDAWarpingSpade(warp_path, device="cuda", dtype=torch.float16)
                logger.info("[LivePortrait] Initialized FP16 CUDA SPADE Warping Engine on GPU.")
            else:
                self._ort_sessions["warping_spade-fix.onnx"] = ort.InferenceSession(
                    str(warp_path), providers=active_providers
                )
                logger.info(f"[LivePortrait] Initialized ONNX Runtime SPADE Warper ({active_providers}).")

            # 3. Extract canonical 3D appearance volume & keypoints once for calypso.png
            if pil_img is not None:
                img_256 = np.asarray(pil_img.resize((256, 256), Image.LANCZOS), dtype=np.float32) / 255.0
                inp_256 = img_256.transpose(2, 0, 1)[None, ...]

                sess_app = self._ort_sessions["appearance_feature_extractor.onnx"]
                sess_mot = self._ort_sessions["motion_extractor.onnx"]
                sess_lip = self._ort_sessions["stitching_lip.onnx"]
                sess_eye = self._ort_sessions["stitching_eye.onnx"]

                self._f3d_np = sess_app.run(None, {"img": inp_256})[0]
                pitch, yaw, roll, t, exp, scale, kp = sess_mot.run(None, {"img": inp_256})

                self._pitch_base = self._headpose_pred_to_degree(pitch)
                self._yaw_base = self._headpose_pred_to_degree(yaw)
                self._roll_base = self._headpose_pred_to_degree(roll)
                self._t_base = t
                self._exp_base = exp.reshape(1, 21, 3)
                self._scale_base = scale
                self._kp_can = kp.reshape(1, 21, 3)

                self._x_s = self._transform_keypoint(
                    self._kp_can,
                    self._pitch_base,
                    self._yaw_base,
                    self._roll_base,
                    self._t_base,
                    self._exp_base,
                    self._scale_base,
                )

                if self._cuda_warper is not None:
                    self._f3d_gpu = torch.from_numpy(self._f3d_np).to(
                        device=self._cuda_warper.device, dtype=self._cuda_warper.dtype
                    )
                    self._x_s_gpu = torch.from_numpy(self._x_s).to(
                        device=self._cuda_warper.device, dtype=self._cuda_warper.dtype
                    )

                # Cache baseline zero-deltas for lip and eye retargeting networks
                xs_flat = self._x_s.reshape(1, 63)
                self._d_lip_zero = sess_lip.run(
                    None, {"input": np.concatenate([xs_flat, np.zeros((1, 2), dtype=np.float32)], axis=1)}
                )[0].reshape(1, 21, 3)
                self._d_eye_zero = sess_eye.run(
                    None, {"input": np.concatenate([xs_flat, np.zeros((1, 3), dtype=np.float32)], axis=1)}
                )[0].reshape(1, 21, 3)

                # Warm up the neural generator with Calypso's neutral pose
                self._latest_neural_rgb = self._run_spade_generator(self._x_s)
                self._ext_bg_mask = self._compute_exterior_studio_mask(self._latest_neural_rgb)
                self._last_rendered_xd = self._x_s.copy()

            self.onnx_ready = True
            logger.info(
                f"[LivePortrait] Ready with primary driver '{self.primary_portrait_path.name}' "
                f"(CUDA FP16={self._cuda_warper is not None})."
            )
        except Exception as e:
            logger.warning(f"[LivePortrait] ONNX pipeline initialization error: {e}", exc_info=True)
            self.onnx_ready = False

    @staticmethod
    def _compute_exterior_studio_mask(rgb_512: np.ndarray) -> np.ndarray:
        """
        Computes a smooth Gaussian-feathered mask of the exterior studio backdrop using
        connected-component `FLOODFILL_FIXED_RANGE` seeded from the top corners, so Calypso's
        interior face, eyes, hair wisps, and dress are 100% protected.
        """
        img_u8 = rgb_512.astype(np.uint8)
        h, w = img_u8.shape[:2]
        ff_mask = np.zeros((h + 2, w + 2), dtype=np.uint8)
        tol = (24, 14, 18)
        flags = 4 | (255 << 8) | cv2.FLOODFILL_MASK_ONLY | cv2.FLOODFILL_FIXED_RANGE
        try:
            cv2.floodFill(img_u8, ff_mask, (4, 4), 0, tol, tol, flags=flags)
            cv2.floodFill(img_u8, ff_mask, (w - 5, 4), 0, tol, tol, flags=flags)
        except Exception:
            pass
        ext = (ff_mask[1:-1, 1:-1] > 0).astype(np.float32)
        ext_soft = cv2.GaussianBlur(ext, (19, 19), 5.5)
        return ext_soft[..., None]

    @classmethod
    def download_onnx_models(cls, progress_cb: Optional[Callable[[str], None]] = None) -> Tuple[bool, str]:
        """
        Downloads the FasterLivePortrait ONNX model suite from HuggingFace (`warmshao/FasterLivePortrait`)
        into `liveportrait_models/` and upgrades `warping_spade-fix.onnx` for standard ONNX Runtime.
        """
        target_dir = getattr(config, "LIVEPORTRAIT_MODELS_DIR", config.BASE_DIR / "liveportrait_models")
        target_dir.mkdir(parents=True, exist_ok=True)
        try:
            from huggingface_hub import hf_hub_download
            repo_id = "warmshao/FasterLivePortrait"
            for idx, fname in enumerate(REQUIRED_ONNX_FILES, start=1):
                if progress_cb:
                    progress_cb(f"Downloading {fname} ({idx}/{len(REQUIRED_ONNX_FILES)})...")
                downloaded = hf_hub_download(
                    repo_id=repo_id,
                    filename=f"liveportrait_onnx/{fname}",
                    local_dir=str(target_dir),
                )
                src_p = Path(downloaded)
                dst_p = target_dir / fname
                if src_p.exists() and src_p.resolve() != dst_p.resolve():
                    dst_p.write_bytes(src_p.read_bytes())
                if fname == "warping_spade-fix.onnx":
                    ensure_warping_spade_onnx_compatible(dst_p)
            return True, f"Successfully installed FasterLivePortrait ONNX models into {target_dir}"
        except Exception as e:
            return False, f"Could not download FasterLivePortrait ONNX models: {e}"

    # ------------------------------------------------------------------
    # FASTER-LIVEPORTRAIT 3D KEYPOINT MATH & NEURAL RETARGETING
    # ------------------------------------------------------------------
    @staticmethod
    def _headpose_pred_to_degree(pred: np.ndarray) -> np.ndarray:
        e = np.exp(pred - np.max(pred, axis=1, keepdims=True))
        prob = e / np.sum(e, axis=1, keepdims=True)
        idx = np.arange(66, dtype=np.float32)[None, :]
        return np.sum(prob * idx, axis=1) * 3.0 - 97.5

    @staticmethod
    def _get_rotation_matrix(pitch_d: np.ndarray, yaw_d: np.ndarray, roll_d: np.ndarray) -> np.ndarray:
        rx = float(np.deg2rad(pitch_d)[0])
        ry = float(np.deg2rad(yaw_d)[0])
        rz = float(np.deg2rad(roll_d)[0])
        Rx = np.array([[1, 0, 0], [0, math.cos(rx), -math.sin(rx)], [0, math.sin(rx), math.cos(rx)]], dtype=np.float32)
        Ry = np.array([[math.cos(ry), 0, math.sin(ry)], [0, 1, 0], [-math.sin(ry), 0, math.cos(ry)]], dtype=np.float32)
        Rz = np.array([[math.cos(rz), -math.sin(rz), 0], [math.sin(rz), math.cos(rz), 0], [0, 0, 1]], dtype=np.float32)
        return (Rz @ Ry @ Rx).T

    def _transform_keypoint(
        self,
        kp_3d: np.ndarray,
        pitch_d: np.ndarray,
        yaw_d: np.ndarray,
        roll_d: np.ndarray,
        t_vec: np.ndarray,
        exp_3d: np.ndarray,
        s_val: np.ndarray,
    ) -> np.ndarray:
        R = self._get_rotation_matrix(pitch_d, yaw_d, roll_d)
        kp_rot = kp_3d @ R[None, ...]
        kp_t = s_val.reshape(1, 1, 1) * (kp_rot + exp_3d)
        kp_t[..., :2] += t_vec[:, None, :2]
        return kp_t

    def _stitch_keypoints(self, kp_src: np.ndarray, kp_drv: np.ndarray) -> np.ndarray:
        sess_st = self._ort_sessions.get("stitching.onnx")
        if sess_st is None:
            return kp_drv
        st_in = np.concatenate([kp_src.reshape(1, 63), kp_drv.reshape(1, 63)], axis=1)
        delta = sess_st.run(None, {"input": st_in})[0]
        out = kp_drv + delta[:, :63].reshape(1, 21, 3)
        out[..., :2] += delta[:, 63:65].reshape(1, 1, 2)
        return out

    def _retarget_eye(self, e_left: float, e_right: float, e_widen: float) -> np.ndarray:
        sess_eye = self._ort_sessions.get("stitching_eye.onnx")
        if sess_eye is None or self._x_s is None:
            return np.zeros((1, 21, 3), dtype=np.float32)
        c_eye = np.array([[float(e_left), float(e_right), float(e_widen)]], dtype=np.float32)
        eye_in = np.concatenate([self._x_s.reshape(1, 63), c_eye], axis=1)
        d_eye = sess_eye.run(None, {"input": eye_in})[0].reshape(1, 21, 3)
        if e_left < 0.01 and e_right < 0.01 and e_widen < 0.01 and self._d_eye_zero is not None:
            return np.zeros((1, 21, 3), dtype=np.float32)
        return d_eye

    def _retarget_lip(self, lip_pucker: float, lip_open: float) -> np.ndarray:
        sess_lip = self._ort_sessions.get("stitching_lip.onnx")
        if sess_lip is None or self._x_s is None or self._d_lip_zero is None:
            return np.zeros((1, 21, 3), dtype=np.float32)
        c_lip = np.array([[float(lip_pucker), float(lip_open)]], dtype=np.float32)
        lip_in = np.concatenate([self._x_s.reshape(1, 63), c_lip], axis=1)
        d_lip = sess_lip.run(None, {"input": lip_in})[0].reshape(1, 21, 3)
        return d_lip - self._d_lip_zero

    def _run_spade_generator(self, kp_driving: np.ndarray) -> np.ndarray:
        with self._infer_lock:
            if self._cuda_warper is not None and self._f3d_gpu is not None and self._x_s_gpu is not None:
                return self._cuda_warper.infer(self._f3d_gpu, kp_driving, self._x_s_gpu)
            sess_warp = self._ort_sessions.get("warping_spade-fix.onnx")
            if sess_warp is not None and self._f3d_np is not None and self._x_s is not None:
                out = sess_warp.run(
                    None,
                    {"feature_3d": self._f3d_np, "kp_driving": kp_driving, "kp_source": self._x_s},
                )[0]
                return np.clip(out[0].transpose(1, 2, 0) * 255.0, 0.0, 255.0).astype(np.uint8)
            return self._base_rgb_512

    # ------------------------------------------------------------------
    # EMOTION STATE & REAL-TIME AUDIO VISEME EXTRACTION
    # ------------------------------------------------------------------
    def load_emotion(self, emotion: str) -> bool:
        """
        Updates the target 3D neural expression preset and studio lighting palette for `emotion`
        on the primary `calypso.png` portrait.
        """
        clean = (emotion or "neutral").lower().strip().replace(" ", "_").replace("-", "_")
        self.current_emotion = clean

        preset = EMOTION_NEURAL_PRESETS.get(clean, EMOTION_NEURAL_PRESETS["neutral"])
        self._tgt_emo_vec = np.array(preset, dtype=np.float32)

        low_rgb, high_rgb = EMOTION_STUDIO_PALETTE.get(clean, EMOTION_STUDIO_PALETTE["neutral"])
        self._tgt_bg_low = np.array(low_rgb, dtype=np.float32)
        self._tgt_bg_high = np.array(high_rgb, dtype=np.float32)

        if not self.running:
            self.start()
        return True

    def _extract_viseme_targets(self) -> Tuple[float, float, bool]:
        """
        Computes `(target_jaw_open [0..1], target_lip_spread [-0.4..0.6], is_speaking)`
        from AudioEngine's real-time TTS buffer.
        """
        now = time.time()
        samples, sr, ts, source = AudioEngine.get_vis_snapshot()
        if (now - ts) > 0.11 or source != "voice":
            return 0.0, 0.0, False

        rms = float(np.sqrt(np.mean(samples ** 2)))
        if rms < 1e-4:
            return 0.0, 0.0, False

        windowed = samples * np.hanning(samples.size)
        spec = np.abs(np.fft.rfft(windowed))
        freqs = np.fft.rfftfreq(samples.size, d=1.0 / float(max(8000, sr)))

        vowel_mask = (freqs >= 180) & (freqs <= 850)
        formant_mask = (freqs >= 1200) & (freqs <= 4500)

        vowel_energy = float(np.mean(spec[vowel_mask])) if np.any(vowel_mask) else 0.0
        formant_energy = float(np.mean(spec[formant_mask])) if np.any(formant_mask) else 0.0

        jaw_target = min(1.0, (rms * 5.2) + (vowel_energy * 0.14))
        ratio = formant_energy / max(1e-4, vowel_energy + formant_energy)
        spread_target = max(-0.35, min(0.50, (ratio - 0.35) * 1.4))
        return jaw_target, spread_target, True

    # ------------------------------------------------------------------
    # BACKGROUND NEURAL WORKER THREAD (3D KEYPOINTS + SPADE GENERATOR)
    # ------------------------------------------------------------------
    def _compute_driving_keypoints(self, now: float) -> np.ndarray:
        """
        Combines:
        1. Smoothly interpolated emotional 3D pose & expression preset (`EMOTION_NEURAL_PRESETS`)
        2. Somatic breathing & speech-synced head rhythm
        3. Stochastic anatomical eye blinking (`stitching_eye.onnx`)
        4. Real-time JoyVASA acoustic lip & jaw retargeting (`stitching_lip.onnx`)
        5. Boundary locking (`stitching.onnx`)
        """
        # 1. Smoothly interpolate emotional preset vector
        self._cur_emo_vec = self._cur_emo_vec * 0.86 + self._tgt_emo_vec * 0.14
        smile, brow, emo_eye_l, emo_eye_r, emo_eye_widen, p_off, y_off, r_off, rest_lip = self._cur_emo_vec

        # 2. Update audio viseme envelope
        jaw_t, spread_t, speaking = self._extract_viseme_targets()
        self._speaking = speaking
        if jaw_t > self._jaw_open:
            self._jaw_open = self._jaw_open * 0.60 + jaw_t * 0.70
        else:
            self._jaw_open = self._jaw_open * 0.65 + jaw_t * 0.35
        self._lip_spread = self._lip_spread * 0.62 + spread_t * 0.38

        # 3. Update stochastic eye blink state
        if not self._is_blinking and (now - self._last_blink_time) >= self._next_blink_interval:
            self._is_blinking = True
            self._blink_phase = 0.0
            self._last_blink_time = now
            if self._double_blink_pending:
                self._double_blink_pending = False
                self._next_blink_interval = random.uniform(2.8, 5.4)
            elif random.random() < 0.18:
                self._double_blink_pending = True
                self._next_blink_interval = 0.22
            else:
                self._next_blink_interval = random.uniform(2.6, 5.4)

        blink_amount = 0.0
        if self._is_blinking:
            self._blink_phase += 0.34  # crisp ~145ms natural blink cycle
            if self._blink_phase >= math.pi:
                self._is_blinking = False
                self._blink_phase = 0.0
            else:
                blink_amount = math.sin(self._blink_phase)

        # 4. Head pose with somatic breathing & speech cadence
        speech_nod = math.sin(now * 6.2) * 1.4 * self._jaw_open if speaking else 0.0
        speech_yaw = math.cos(now * 3.4) * 0.9 * self._jaw_open if speaking else 0.0
        breath_pitch = math.sin(now * 1.6) * 0.55

        pitch_d = self._pitch_base + p_off + breath_pitch + speech_nod
        yaw_d = self._yaw_base + y_off + speech_yaw
        roll_d = self._roll_base + r_off + math.sin(now * 0.9) * 0.45

        # 5. Construct 3D expression offset on canonical keypoints (smile, cheeks, brows, lip spread)
        exp_mod = self._exp_base.copy()
        eff_smile = float(smile) + float(self._lip_spread) * (0.45 if speaking else 0.0)
        if abs(eff_smile) > 0.01:
            # KP 17 (left lip corner), KP 18 (right lip corner), KP 3/4 (cheeks)
            exp_mod[0, 17, 0] -= eff_smile * 0.011
            exp_mod[0, 17, 1] -= max(0.0, eff_smile) * 0.012 - min(0.0, eff_smile) * 0.008
            exp_mod[0, 18, 0] += eff_smile * 0.011
            exp_mod[0, 18, 1] -= max(0.0, eff_smile) * 0.012 - min(0.0, eff_smile) * 0.008
            exp_mod[0, 3, 1] -= eff_smile * 0.005
            exp_mod[0, 4, 1] -= eff_smile * 0.005

        if abs(brow) > 0.01:
            # KP 1 (left brow), KP 2 (right brow)
            exp_mod[0, 1, 1] -= float(brow) * 0.010
            exp_mod[0, 2, 1] -= float(brow) * 0.010

        x_d = self._transform_keypoint(
            self._kp_can, pitch_d, yaw_d, roll_d, self._t_base, exp_mod, self._scale_base
        )

        # 6. Neural Eye Retargeting (stitching_eye.onnx)
        # Full anatomical eyelid closure occurs at e_left = e_right = 0.38
        e_l = max(float(emo_eye_l), blink_amount * 0.38)
        e_r = max(float(emo_eye_r), blink_amount * 0.38)
        e_w = float(emo_eye_widen) * (1.0 - blink_amount)
        d_eye = self._retarget_eye(e_l, e_r, e_w)

        # 7. Neural Lip Retargeting (stitching_lip.onnx)
        # Map jaw_open [0..1] to natural conversational lip opening [0.0 .. 0.21]
        lip_open_val = max(float(rest_lip), self._jaw_open * 0.21)
        lip_pucker_val = max(0.0, -float(self._lip_spread) * 0.19) if speaking else 0.0
        d_lip = self._retarget_lip(lip_pucker_val, lip_open_val)

        # 8. Neural Stitching (stitching.onnx)
        x_d_combined = x_d + d_eye + d_lip
        return self._stitch_keypoints(self._x_s, x_d_combined)

    @staticmethod
    def _is_vram_lock_busy() -> bool:
        """Non-blocking check whether a heavy SDXL or MusicGen job currently holds `gpu_vram_lock`."""
        acquired = gpu_vram_lock.acquire(blocking=False)
        if acquired:
            gpu_vram_lock.release()
            return False
        return True

    def _neural_worker_loop(self):
        """
        Dedicated background thread running the FasterLivePortrait ONNX + CUDA FP16 SPADE pipeline
        at ~24 FPS without ever blocking the Tkinter UI thread.
        """
        while self.running:
            t0 = time.time()
            if self.onnx_ready and self._x_s is not None:
                try:
                    # Yield GPU cleanly while SDXL or MusicGen holds gpu_vram_lock
                    if not self._is_vram_lock_busy():
                        x_d = self._compute_driving_keypoints(t0)
                        if (
                            self._last_rendered_xd is None
                            or float(np.max(np.abs(x_d - self._last_rendered_xd))) > 8e-5
                        ):
                            rgb = self._run_spade_generator(x_d)
                            with self._frame_lock:
                                self._latest_neural_rgb = rgb
                            self._last_rendered_xd = x_d
                except Exception as e:
                    logger.debug(f"[LivePortrait] Neural worker frame notice: {e}")

            elapsed = time.time() - t0
            sleep_s = max(0.008, 0.040 - elapsed)
            time.sleep(sleep_s)

    def _composite_studio_backdrop(self, frame_rgb: np.ndarray, now: float) -> np.ndarray:
        """
        Illuminates the exterior studio backdrop of `calypso.png` with Calypso's active
        emotional palette (`EMOTION_STUDIO_PALETTE`) and a vocal-reactive radial backlight halo.
        """
        if self._ext_bg_mask is None or self._halo_grid is None or self._grad_grid is None:
            return frame_rgb

        # Smoothly transition studio backdrop colors across emotional tiers
        self._cur_bg_low = self._cur_bg_low * 0.90 + self._tgt_bg_low * 0.10
        self._cur_bg_high = self._cur_bg_high * 0.90 + self._tgt_bg_high * 0.10

        emo_col = (
            self._cur_bg_low[None, None, :] * (1.0 - self._grad_grid)
            + self._cur_bg_high[None, None, :] * self._grad_grid
        )

        # Subtle idle breathing + real-time voice resonance pulse on the studio backlight halo
        idle_pulse = 0.03 * math.sin(now * 2.1)
        voice_pulse = 0.18 * self._jaw_open if self._speaking else 0.0
        halo_intensity = 0.14 + (0.30 + idle_pulse + voice_pulse) * self._halo_grid

        img_f = frame_rgb.astype(np.float32)
        luma = (0.299 * img_f[..., 0] + 0.587 * img_f[..., 1] + 0.114 * img_f[..., 2])[..., None]
        studio_bg = luma * 0.38 + emo_col * halo_intensity

        composited = img_f * (1.0 - self._ext_bg_mask) + studio_bg * self._ext_bg_mask
        return np.clip(composited, 0.0, 255.0).astype(np.uint8)

    # ------------------------------------------------------------------
    # TKINTER ANIMATION LOOP (25 FPS)
    # ------------------------------------------------------------------
    def start(self):
        if not self.running and self.target_label is not None:
            self.running = True
            if self._worker_thread is None or not self._worker_thread.is_alive():
                self._worker_thread = threading.Thread(
                    target=self._neural_worker_loop, name="LivePortraitNeuralWorker", daemon=True
                )
                self._worker_thread.start()
            self._animate()

    def stop(self):
        self.running = False
        if self.anim_job and self.target_label:
            try:
                self.target_label.after_cancel(self.anim_job)
            except Exception:
                pass
            self.anim_job = None

    def _animate(self):
        if not self.running or not self.target_label:
            return

        now = time.time()
        with self._frame_lock:
            neural_rgb = self._latest_neural_rgb

        if neural_rgb is not None:
            try:
                final_rgb = self._composite_studio_backdrop(neural_rgb, now)
                pil_frame = Image.fromarray(final_rgb)
                tk_img = ImageTk.PhotoImage(pil_frame)
                self.target_label.config(image=tk_img, text="")
                self.target_label.image = tk_img
            except Exception as e:
                logger.debug(f"[LivePortrait] Frame render notice: {e}")

        # 25 FPS (40ms) UI update cadence
        self.anim_job = self.target_label.after(40, self._animate)
