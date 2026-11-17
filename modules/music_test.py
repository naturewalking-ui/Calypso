
import torch
import transformers
import soundfile as sf

from transformers import (
    AutoProcessor,
    MusicgenForConditionalGeneration,
)

MODEL = "facebook/musicgen-medium"


def main():
    print("PyTorch:", torch.__version__)
    print("Transformers:", transformers.__version__)
    print("CUDA:", torch.version.cuda)

    device = "cuda" if torch.cuda.is_available() else "cpu"

    processor = AutoProcessor.from_pretrained(MODEL)
    model = MusicgenForConditionalGeneration.from_pretrained(
        MODEL,
        torch_dtype=torch.float32,
    ).to(device)

    model.eval()

    print("Model:", model.config.model_type)
    print("Audio encoder:", model.config.audio_encoder.model_type)
    print("Codebooks:", model.config.decoder.num_codebooks)
    print("Channels:", model.config.decoder.audio_channels)
    print("Sample rate:", model.config.audio_encoder.sampling_rate)
    print("Generation config:", model.generation_config)

    inputs = processor(
        text=["A gentle solo piano melody."],
        padding=True,
        return_tensors="pt",
    ).to(device)

    torch.manual_seed(42)

    with torch.inference_mode():
        audio = model.generate(
            **inputs,
            do_sample=True,
            guidance_scale=3.0,
            max_new_tokens=256,
        )

    print("Audio shape:", audio.shape)
    print("Finite:", torch.isfinite(audio).all().item())
    print("Min:", audio.min().item())
    print("Max:", audio.max().item())

    waveform = audio[0, 0].cpu().float().numpy()

    sf.write(
        "musicgen_diagnostic.wav",
        waveform,
        model.config.audio_encoder.sampling_rate,
        subtype="FLOAT",
    )

    print("Saved musicgen_diagnostic.wav")


if __name__ == "__main__":
    main()

