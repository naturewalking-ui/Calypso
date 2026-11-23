# Local FasterLivePortrait + JoyVASA ONNX Models Directory

Emotion Engine animates Calypso's portrait (`diffusion_models/calypso.png`) in real time using the **FasterLivePortrait + JoyVASA** ONNX neural synthesis pipeline (`modules/live_portrait_engine.py`).

To keep the repository lightweight and respect upstream licensing, **no pre-trained ONNX weights are bundled with the Git repository**. You can install them with a single click inside the UI or place the 6 required ONNX files manually in this `liveportrait_models/` directory.

---

## Required ONNX Model Suite (6 Files, ~538 MB Total)

`LivePortraitEngine` requires the following 6 ONNX files directly inside `liveportrait_models/`:

1. **`appearance_feature_extractor.onnx`** (~3.35 MB)
   - Extracts and caches Calypso's 3D appearance feature volume (`[1, 32, 16, 64, 64]`) once at startup.
2. **`motion_extractor.onnx`** (~112.6 MB)
   - Extracts canonical 21-point 3D implicit keypoints, head pose (pitch, yaw, roll), scale, and expression offsets.
3. **`warping_spade-fix.onnx`** (~421.2 MB)
   - Volumetric 3D dense-motion network + SPADE generator executed in `float16` on CUDA (or ONNX Runtime).
   - *Compatibility Note*: Emotion Engine automatically upgrades legacy `GridSample3D` (`opset 16`) nodes in `warping_spade-fix.onnx` to standard ONNX `Opset 20 GridSample` on load.
4. **`stitching.onnx`** (~182 KB)
   - Neural boundary stitching network locking neck, shoulder, and hairline alignment.
5. **`stitching_eye.onnx`** (~581 KB)
   - Neural eyelid retargeting network driving stochastic blinking, double-blinks, emotional squints, and wide-eyed states.
6. **`stitching_lip.onnx`** (~151 KB)
   - Neural lip and jaw retargeting network driven by real-time acoustic formant/vowel FFT decomposition from `AudioEngine`.

---

## Official Model Repository

All 6 ONNX files originate from the `liveportrait_onnx/` folder of the **FasterLivePortrait** repository on Hugging Face:

- **Repository**: https://huggingface.co/warmshao/FasterLivePortrait
- **Files Directory**: https://huggingface.co/warmshao/FasterLivePortrait/tree/main/liveportrait_onnx

---

## Option 1: One-Click Automatic Download in Settings (Easiest)

1. Open **Settings (⚙️) -> 👤 Identity & Bond**.
2. Set **Avatar Visual Bay Mode** to **`FasterLivePortrait + JoyVASA (calypso.png — Real-Time ONNX Lip-Sync)`**.
3. In the **LivePortrait Primary Driver** status bar directly below the dropdown, click **`⬇️ Fetch ONNX Suite`**.
4. Calypso will download all 6 ONNX models from `warmshao/FasterLivePortrait`, place them directly in `liveportrait_models/`, and automatically patch `warping_spade-fix.onnx` for ONNX Opset 20 compatibility.

---

## Option 2: Manual Offline Placement in `liveportrait_models/`

If running strictly offline, download the 6 files from https://huggingface.co/warmshao/FasterLivePortrait/tree/main/liveportrait_onnx and place them directly in `liveportrait_models/`:

```text
liveportrait_models/
├── README.md
├── appearance_feature_extractor.onnx
├── motion_extractor.onnx
├── stitching.onnx
├── stitching_eye.onnx
├── stitching_lip.onnx
└── warping_spade-fix.onnx
```
