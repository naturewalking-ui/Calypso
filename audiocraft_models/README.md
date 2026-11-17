# Local AudioCraft / MusicGen Models Directory

Emotion Engine executes MusicGen inference using Hugging Face `transformers` (`Apache-2.0` license) in full `float32` precision for studio-grade acoustic fidelity.

To respect model licensing (Meta's pre-trained MusicGen weights are released under **CC-BY-NC 4.0**), **no model weights are bundled with Emotion Engine**. You bring your own model weights locally or opt in to automatic Hugging Face download.

## Official Model Links (Recommended)

Always use the official Meta MusicGen repositories on Hugging Face (do **not** use 4 GB `fp16` third-party exports, as 16-bit weight quantization corrupts the 48-layer RVQ decoder and EnCodec filterbanks):

- **`facebook/musicgen-medium` (Recommended — 1.5B parameters, ~8.04 GB `float32`)**:
  - Repository: https://huggingface.co/facebook/musicgen-medium
  - Files page: https://huggingface.co/facebook/musicgen-medium/tree/main
- **`facebook/musicgen-small` (Lightweight — 300M parameters, ~2.4 GB `float32`)**:
  - Repository: https://huggingface.co/facebook/musicgen-small
  - Files page: https://huggingface.co/facebook/musicgen-small/tree/main
- **`facebook/musicgen-large` (3.3B parameters, ~13.1 GB `float32`)**:
  - Repository: https://huggingface.co/facebook/musicgen-large
  - Files page: https://huggingface.co/facebook/musicgen-large/tree/main

## Option 1: Opt-In Automatic Download (Easiest)

Open **Settings (⚙️) -> AudioCraft & Acoustic Generation**, select **`facebook/musicgen-medium`** in the dropdown, and check **"Allow Online Hugging Face Model Download"**. Hugging Face `transformers` will automatically download and verify the full-precision snapshot into your local cache (`~/.cache/huggingface/hub/`).

## Option 2: Manual Offline Placement in `audiocraft_models/`

If running strictly offline without Hugging Face cache, download all files from https://huggingface.co/facebook/musicgen-medium/tree/main and place them together inside `audiocraft_models/` (or `audiocraft_models/musicgen-medium/`):

- `model.safetensors` (**8.04 GB** full `float32` official file)
- `config.json`
- `generation_config.json`
- `preprocessor_config.json`
- `spiece.model`
- `tokenizer.json`
- `tokenizer_config.json`
- `special_tokens_map.json`

