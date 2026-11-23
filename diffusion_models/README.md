# Local Stable Diffusion & Identity Preservation Models Directory

Emotion Engine executes local image generation using Hugging Face `diffusers` (`StableDiffusionXLPipeline` in `float16` precision with VAE tiling and Compel prompt weighting), paired with an optional post-processing identity pipeline (`InsightFace` + `GFPGAN`) to maintain persona facial consistency.

To keep the repository lightweight and respect upstream model licenses, **no diffusion checkpoints or face restoration weights are bundled with Emotion Engine**. Place your preferred models directly inside this `diffusion_models/` directory.

---

## 1. Stable Diffusion XL (SDXL) Checkpoints (Required for Image Generation)

`ImageGenerator` loads single-file `.safetensors` (recommended) or `.ckpt` SDXL checkpoints directly from `diffusion_models/` with `local_files_only=True`.

### Official & Recommended Base Models

- **Stable Diffusion XL Base 1.0 (`sd_xl_base_1.0.safetensors` — ~6.94 GB `fp16`)**:
  - Repository: https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0
  - Direct File Page: https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0/blob/main/sd_xl_base_1.0.safetensors
- **Any Custom SDXL 1.0 Fine-Tune or SDXL Lightning/Turbo Single-File Checkpoint (`.safetensors`)**:
  - Place any SDXL-compatible `.safetensors` file in `diffusion_models/`.

### Selecting Your Checkpoint in Calypso
1. Copy your `.safetensors` file into `diffusion_models/` (e.g., `diffusion_models/sd_xl_base_1.0.safetensors`).
2. Open **Settings (⚙️) -> 🤖 LLM & Vision -> 🎨 Stable Diffusion & Image Generation**.
3. Click **🔄 Fetch** next to **Diffusion Checkpoint** and select your model from the dropdown.

---

## 2. Persona Reference Portrait (`calypso.png`)

- **`calypso.png`**: Serves two roles in Calypso's architecture:
  1. **Canonical Driver Portrait** for the real-time **FasterLivePortrait + JoyVASA** neural avatar engine (`modules/live_portrait_engine.py`).
  2. **Source Identity Reference** for `FaceSwapper` (`modules/face_swapper.py`) when **Enable Face Swap** is active during scene generation.
- If `calypso.png` is not present, `ImageGenerator` searches `diffusion_models/` for fallback reference images named `clone`, `base`, `source`, `face`, `avatar`, `persona`, or `reference` (`.png`, `.jpg`, `.jpeg`, `.webp`).

---

## 3. Optional Identity Preservation & Face Restoration Models

When **Enable Face Swap** and **Face Restoration (GFPGAN)** are checked in **Settings (⚙️) -> 🤖 LLM & Vision**, `ImageGenerator` looks for the following weights inside `diffusion_models/`:

### A. InsightFace Face Swapper (`inswapper_128.onnx`)
- **Required Filename**: `inswapper_128.onnx` (or `inswapper.onnx`, ~554 MB)
- **Official Source**: InsightFace Model Zoo (`inswapper_128.onnx`)
  - Mirror / Reference: https://huggingface.co/ezioruan/inswapper_128.onnx/tree/main
- **Note on Face Detection (`buffalo_l`)**: On first use, `insightface.app.FaceAnalysis(name='buffalo_l')` automatically loads or caches the `buffalo_l` detection pack under `~/.insightface/models/buffalo_l/`.

### B. GFPGAN Face Restoration (`GFPGANv1.4.pth`)
- **Supported Filenames**: `GFPGANv1.4.pth` (recommended, ~348 MB), `GFPGANv1.3.pth`, `GFPGAN.pth`, or `codeformer.pth`
- **Official Source**: TencentARC GFPGAN Releases
  - Release Page: https://github.com/TencentARC/GFPGAN/releases
  - Direct Weight Link (`GFPGANv1.4.pth`): https://github.com/TencentARC/GFPGAN/releases/download/v1.3.0/GFPGANv1.4.pth

---

## Summary of Expected Directory Layout

```text
diffusion_models/
├── README.md
├── calypso.png                  # Primary persona driver & face-swap source portrait
├── sd_xl_base_1.0.safetensors   # Primary SDXL checkpoint (or custom .safetensors)
├── inswapper_128.onnx           # (Optional) InsightFace 128x128 face swapper
└── GFPGANv1.4.pth               # (Optional) GFPGAN high-frequency face restorer
```
