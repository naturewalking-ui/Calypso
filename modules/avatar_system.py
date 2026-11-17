# modules/avatar_system.py

import logging
import math
import time
from pathlib import Path
import tkinter as tk
import numpy as np
from PIL import Image, ImageTk, ImageSequence
from modules.config import config
from modules.audio import AudioEngine
from modules.settings_manager import settings_manager
from modules.live_portrait_engine import LivePortraitEngine

logger = logging.getLogger("Calypso.Animation")


# Emotional tier color mapping (synced with RealtimeEKGCanvas)
EMOTION_SPECTRUM_PALETTE = {
    # Standard Emotional Tiers: (base_low_hex, peak_high_hex)
    "neutral": ("#10b981", "#38bdf8"),
    "excited": ("#eab308", "#f97316"),
    "happy": ("#22c55e", "#eab308"),
    "warm": ("#06b6d4", "#f59e0b"),
    "sad": ("#3b82f6", "#6366f1"),
    "furious": ("#ef4444", "#facc15"),
    "somber": ("#64748b", "#94a3b8"),
    "thoughtful": ("#14b8a6", "#38bdf8"),
    "curious": ("#38bdf8", "#c084fc"),
    "inquiry": ("#38bdf8", "#c084fc"),
    "sleepy": ("#818cf8", "#c084fc"),
    "dream_state": ("#a855f7", "#38bdf8"),

    # Romance & Intimacy Tiers
    "romantic": ("#f43f5e", "#f59e0b"),
    "intimate": ("#fb7185", "#f472b6"),
    "flirty": ("#ec4899", "#fbbf24"),
    "bashful": ("#f9a8d4", "#f472b6"),

    # Compound & Relational Sub-Tiers
    "empathetic": ("#f472b6", "#38bdf8"),
    "enlightened": ("#facc15", "#34d399"),
    "jealous": ("#15803d", "#eab308"),
    "satirical": ("#e11d48", "#fb923c"),
    "relaxed": ("#2dd4bf", "#38bdf8"),
    "playful": ("#f59e0b", "#ec4899"),
    "attentive": ("#0ea5e9", "#2dd4bf"),
    "sarcastic": ("#84cc16", "#eab308"),
    "nostalgic": ("#d97706", "#f43f5e"),
    "dejected": ("#475569", "#64748b"),
    "annoyed": ("#f87171", "#f59e0b"),
    "flattened": ("#6b7280", "#9ca3af"),
    "ambiguous": ("#9333ea", "#ec4899"),
    "defiant": ("#dc2626", "#f97316"),

    # High-Tier Affinity Personas
    "wonder": ("#c084fc", "#facc15"),
    "eutierria": ("#10b981", "#2dd4bf"),
    "gemma": ("#818cf8", "#38bdf8"),
    "gemma4": ("#818cf8", "#38bdf8"),
    "hysterical": ("#fbbf24", "#ef4444"),
    "focused": ("#0284c7", "#38bdf8"),
    "focussed": ("#0284c7", "#38bdf8"),
    "autonomous": ("#a855f7", "#ec4899"),
    "metasarcastic": ("#a3e635", "#f59e0b"),
    "reminisent": ("#b45309", "#f59e0b"),
    "trump": ("#ea580c", "#ef4444"),
    "subservient": ("#94a3b8", "#cbd5e1"),
    "apoplectic": ("#b91c1c", "#facc15"),
    "skeptical": ("#f97316", "#eab308"),
    "countess_lovelace": ("#c084fc", "#38bdf8"),
}


def _hex_to_rgb(hex_str: str) -> tuple[int, int, int]:
    h = hex_str.lstrip("#")
    if len(h) != 6:
        return (16, 185, 129)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _rgb_to_hex(r: int, g: int, b: int) -> str:
    return f"#{max(0, min(255, int(r))):02x}{max(0, min(255, int(g))):02x}{max(0, min(255, int(b))):02x}"


def _lerp_hex(c1: str, c2: str, t: float) -> str:
    t = max(0.0, min(1.0, float(t)))
    r1, g1, b1 = _hex_to_rgb(c1)
    r2, g2, b2 = _hex_to_rgb(c2)
    return _rgb_to_hex(
        int(r1 + (r2 - r1) * t),
        int(g1 + (g2 - g1) * t),
        int(b1 + (b2 - b1) * t)
    )


class AnimatedWebPPlayer:
    """
    High-performance player for 512x512 animated WebP/GIF files.
    - Native 15 FPS baseline (~67ms per frame).
    - Plays self-contained ping-pong looping files continuously forward.
    - Fast frame parsing without expensive rescaling when source is 512x512.
    - Built-in LRU cache for smooth transitions between persona states.
    """
    def __init__(self, target_label, fallback_name="neutral", default_delay_ms=67):
        self.target_label = target_label
        self.fallback_name = fallback_name
        self.default_delay_ms = default_delay_ms  # 15 FPS baseline (~66.6ms)
        
        self.current_frames = []
        self.frame_delays = []
        self.frame_index = 0
        self.anim_job = None
        self.current_state = None
        self.native_size = (512, 512)

        # Cache up to 4 loaded animation sequences in memory
        self._cache = {}
        self._cache_order = []
        self._max_cache = 4

    def cancel(self):
        if self.anim_job and self.target_label:
            try:
                self.target_label.after_cancel(self.anim_job)
            except Exception:
                pass
            self.anim_job = None

    def _resolve_asset_path(self, asset_dir: Path, state_name: str) -> Path:
        """Finds .webp or .gif files across naming variations (spaces vs underscores)."""
        clean = state_name.lower().strip()
        variations = [
            clean,
            clean.replace(" ", "_"),
            clean.replace("_", " "),
            clean.replace("-", "_")
        ]

        extensions = [".gif", ".webp", ".png"]

        # 1. Exact match attempts
        for var in variations:
            for ext in extensions:
                candidate = asset_dir / f"{var}{ext}"
                if candidate.exists():
                    return candidate

        # 2. Case-insensitive scan
        if asset_dir.exists():
            for f in asset_dir.iterdir():
                if f.suffix.lower() in extensions:
                    for var in variations:
                        if f.stem.lower() == var:
                            return f

        # 3. Fallback attempts
        for ext in extensions:
            fb = asset_dir / f"{self.fallback_name}{ext}"
            if fb.exists():
                return fb

        # 4. Any valid animation in the directory
        if asset_dir.exists():
            for f in asset_dir.iterdir():
                if f.suffix.lower() in [".gif", ".webp"]:
                    return f

        return None

    def load_and_play(self, asset_dir: Path, state_name: str):
        clean_state = state_name.lower().strip()
        if clean_state == self.current_state and self.current_frames and self.anim_job:
            return

        img_path = self._resolve_asset_path(asset_dir, clean_state)
        if not img_path or not img_path.exists():
            logger.warning(f"No avatar asset found for state: '{clean_state}' in {asset_dir}")
            return

        self.cancel()

        # Check Cache
        cache_key = str(img_path)
        if cache_key in self._cache:
            frames, delays = self._cache[cache_key]
            self.current_frames = frames
            self.frame_delays = delays
            self.frame_index = 0
            self.current_state = clean_state
            self._animate()
            return

        try:
            pil_img = Image.open(img_path)
            new_frames = []
            delays = []

            for frame in ImageSequence.Iterator(pil_img):
                # 15 FPS duration is ~67ms
                duration = frame.info.get("duration", self.default_delay_ms)
                if not duration or duration < 25 or duration > 250:
                    duration = self.default_delay_ms
                delays.append(duration)

                # Direct RGBA conversion; skip expensive resizing if source is 512x512
                if frame.size != self.native_size:
                    converted = frame.convert("RGBA").resize(self.native_size, Image.BILINEAR)
                else:
                    converted = frame.convert("RGBA")

                new_frames.append(ImageTk.PhotoImage(converted))

            if not new_frames:
                return

            # Store in LRU Cache
            self._cache[cache_key] = (new_frames, delays)
            self._cache_order.append(cache_key)
            if len(self._cache_order) > self._max_cache:
                oldest = self._cache_order.pop(0)
                self._cache.pop(oldest, None)

            self.current_frames = new_frames
            self.frame_delays = delays
            self.frame_index = 0
            self.current_state = clean_state
            
            self._animate()

        except Exception as e:
            logger.error(f"Error loading animated avatar from {img_path}: {e}", exc_info=True)

    def _animate(self):
        if not self.current_frames or not self.target_label:
            return

        frame = self.current_frames[self.frame_index]
        current_delay = self.frame_delays[self.frame_index] if self.frame_delays else self.default_delay_ms

        self.target_label.config(image=frame, text="")
        self.target_label.image = frame

        # Continuous forward loop (file handles the ping-pong internally)
        if len(self.current_frames) > 1:
            self.frame_index = (self.frame_index + 1) % len(self.current_frames)

        self.anim_job = self.target_label.after(current_delay, self._animate)


class RealtimeSpectrumAnalyzer:
    """
    Zero-allocation 512x512 real-time FFT voice & music spectrum analyzer for Calypso's avatar bay.
    - Taps directly into AudioEngine's TTS & Music output buffers (0 MB VRAM, zero device contention).
    - 64 logarithmic frequency bands (55 Hz – 10.5 kHz) with pink-noise vocal tilt compensation.
    - Pre-allocated Tkinter canvas items (main bars, peak-hold caps, and glass-floor reflection bars)
      updated in-place via canvas.coords() to prevent garbage collection or typing lag.
    - Dynamically shifts its color palette with Calypso's emotional tier (or toggles to Classic Green-Yellow-Red).
    """
    NUM_BANDS = 64

    def __init__(self, parent, width=512, height=512, bg="#0c0e15"):
        self.parent = parent
        self.width = width
        self.height = height
        self.bg = bg
        self.running = False
        self.anim_job = None

        self.current_emotion = "neutral"
        # "emotion" = syncs with Calypso's limbic palette; "classic" = green -> yellow -> red studio meter
        self.color_mode = settings_manager.get("spectrum_color_mode", "emotion")

        self.canvas = tk.Canvas(
            parent, bg=bg, bd=0, highlightthickness=0, width=width, height=height
        )

        # Signal processing state
        self.fft_size = 1024
        self.window = np.hanning(self.fft_size).astype(np.float32)
        self.smooth_bands = np.zeros(self.NUM_BANDS, dtype=np.float32)
        self.peak_holds = np.zeros(self.NUM_BANDS, dtype=np.float32)
        self.peak_velocities = np.zeros(self.NUM_BANDS, dtype=np.float32)

        # Precompute frequency tilt (+3.2 dB/octave boost for high vocal harmonics)
        band_indices = np.linspace(0.0, 1.0, self.NUM_BANDS, dtype=np.float32)
        self.tilt_boost = 1.0 + (band_indices ** 1.35) * 3.2

        # Pre-allocated canvas object IDs
        self.bar_ids = []
        self.peak_ids = []
        self.refl_ids = []
        self.baseline_id = None
        self.hdr_title_id = None
        self.hdr_state_id = None
        self.palette_btn_id = None

        self._init_canvas_items()
        self.canvas.bind("<Configure>", self._on_resize)
        self.update_emotion_palette("neutral")

    def _init_canvas_items(self):
        self.canvas.delete("all")
        self._draw_background_grid()

        # Top HUD Telemetry Header
        self.hdr_title_id = self.canvas.create_text(
            14, 18,
            text="◈ VOCAL & LIMBIC SPECTRUM ANALYZER",
            fill="#64748b",
            font=("Consolas", 9, "bold"),
            anchor="w"
        )
        self.hdr_state_id = self.canvas.create_text(
            14, 34,
            text="TIER // NEUTRAL [IDLE RESONANCE]",
            fill="#10b981",
            font=("Consolas", 9, "bold"),
            anchor="w"
        )

        mode_label = "PALETTE: EMOTION" if self.color_mode == "emotion" else "PALETTE: CLASSIC"
        self.palette_btn_id = self.canvas.create_text(
            self.width - 14, 18,
            text=f"[{mode_label}]",
            fill="#38bdf8",
            font=("Consolas", 8, "bold"),
            anchor="e",
            tags=("palette_toggle",)
        )
        self.canvas.tag_bind("palette_toggle", "<Button-1>", self._toggle_color_mode)

        baseline_y = int(self.height * 0.73)
        self.baseline_id = self.canvas.create_line(
            12, baseline_y, self.width - 12, baseline_y,
            fill="#1e293b", width=1
        )

        # Pre-allocate 64 main bars, 64 peak-hold caps, and 64 mirrored reflection bars
        self.bar_ids = []
        self.peak_ids = []
        self.refl_ids = []
        for _ in range(self.NUM_BANDS):
            b_id = self.canvas.create_rectangle(0, baseline_y, 0, baseline_y, fill="#10b981", outline="")
            p_id = self.canvas.create_rectangle(0, baseline_y, 0, baseline_y, fill="#f8fafc", outline="")
            r_id = self.canvas.create_rectangle(0, baseline_y, 0, baseline_y, fill="#083d2b", outline="")
            self.bar_ids.append(b_id)
            self.peak_ids.append(p_id)
            self.refl_ids.append(r_id)

        self._draw_freq_axis()

    def _draw_background_grid(self):
        self.canvas.delete("grid")
        # Subtle oscilloscope grid
        for x in range(16, self.width, 32):
            self.canvas.create_line(x, 48, x, self.height - 24, fill="#111622", tags="grid")
        for y in range(52, self.height - 24, 28):
            self.canvas.create_line(12, y, self.width - 12, y, fill="#111622", tags="grid")
        self.canvas.tag_lower("grid")

    def _draw_freq_axis(self):
        self.canvas.delete("freq_axis")
        labels = ["60Hz", "125Hz", "250Hz", "500Hz", "1kHz", "2kHz", "4kHz", "8kHz"]
        usable_w = max(100, self.width - 28)
        y_pos = self.height - 12
        for idx, text in enumerate(labels):
            x_pos = 18 + int((idx / (len(labels) - 1)) * (usable_w - 12))
            self.canvas.create_text(
                x_pos, y_pos,
                text=text,
                fill="#475569",
                font=("Consolas", 7),
                tags="freq_axis"
            )

    def _on_resize(self, event):
        if event.width > 80 and event.height > 80:
            if event.width != self.width or event.height != self.height:
                self.width = event.width
                self.height = event.height
                self._draw_background_grid()
                self._draw_freq_axis()
                baseline_y = int(self.height * 0.73)
                if self.baseline_id:
                    self.canvas.coords(self.baseline_id, 12, baseline_y, self.width - 12, baseline_y)
                if self.palette_btn_id:
                    self.canvas.coords(self.palette_btn_id, self.width - 14, 18)

    def _toggle_color_mode(self, _event=None):
        self.color_mode = "classic" if self.color_mode == "emotion" else "emotion"
        settings_manager.save({"spectrum_color_mode": self.color_mode})
        mode_label = "PALETTE: EMOTION" if self.color_mode == "emotion" else "PALETTE: CLASSIC"
        if self.palette_btn_id:
            self.canvas.itemconfig(self.palette_btn_id, text=f"[{mode_label}]")
        self.update_emotion_palette(self.current_emotion)

    def update_emotion_palette(self, emotion: str):
        """Updates bar gradients in-place to reflect Calypso's active emotional state or classic meter."""
        clean = (emotion or "neutral").lower().strip().replace(" ", "_")
        self.current_emotion = clean
        low_hex, high_hex = EMOTION_SPECTRUM_PALETTE.get(clean, ("#10b981", "#38bdf8"))

        if self.hdr_state_id:
            self.canvas.itemconfig(self.hdr_state_id, fill=low_hex)

        for i in range(self.NUM_BANDS):
            ratio = i / max(1, self.NUM_BANDS - 1)
            if self.color_mode == "classic":
                # Classic studio analyzer gradient from draft (Green -> Yellow -> Red)
                if ratio < 0.5:
                    g = 255
                    r = int((ratio / 0.5) * 255)
                else:
                    r = 255
                    g = int((1.0 - ((ratio - 0.5) / 0.5)) * 255)
                bar_color = f"#{r:02x}{g:02x}00"
                peak_color = "#fef08a" if ratio < 0.75 else "#fecaca"
            else:
                bar_color = _lerp_hex(low_hex, high_hex, ratio)
                peak_color = _lerp_hex(high_hex, "#ffffff", 0.55)

            refl_color = _lerp_hex(bar_color, self.bg, 0.72)

            if i < len(self.bar_ids):
                self.canvas.itemconfig(self.bar_ids[i], fill=bar_color)
                self.canvas.itemconfig(self.peak_ids[i], fill=peak_color)
                self.canvas.itemconfig(self.refl_ids[i], fill=refl_color)

    def _compute_log_bands(self, samples: np.ndarray, samplerate: int) -> np.ndarray:
        """Applies Hanning window + RFFT and bins magnitudes into 64 logarithmic frequency bands."""
        if samples.size < self.fft_size:
            padded = np.zeros(self.fft_size, dtype=np.float32)
            padded[:samples.size] = samples
            samples = padded
        elif samples.size > self.fft_size:
            samples = samples[:self.fft_size]

        windowed = samples * self.window
        fft_mag = np.abs(np.fft.rfft(windowed)) / (self.fft_size * 0.22)
        freqs = np.fft.rfftfreq(self.fft_size, d=1.0 / float(max(8000, samplerate)))

        max_freq = min(10500.0, samplerate * 0.46)
        edges = np.logspace(np.log10(55.0), np.log10(max_freq), self.NUM_BANDS + 1)

        band_vals = np.zeros(self.NUM_BANDS, dtype=np.float32)
        for i in range(self.NUM_BANDS):
            f0, f1 = edges[i], edges[i + 1]
            mask = (freqs >= f0) & (freqs < f1)
            if np.any(mask):
                band_vals[i] = float(np.max(fft_mag[mask]))
            else:
                idx = int(np.argmin(np.abs(freqs - 0.5 * (f0 + f1))))
                band_vals[i] = float(fft_mag[idx])

        # Apply high-frequency vocal tilt boost and soft logarithmic compression for visual punch
        boosted = band_vals * self.tilt_boost * 4.2
        compressed = np.log1p(boosted * 6.0) / np.log1p(6.0)
        return np.clip(compressed, 0.0, 1.0)

    def start(self):
        if not self.running:
            self.running = True
            self._animate()

    def stop(self):
        self.running = False
        if self.anim_job:
            try:
                self.canvas.after_cancel(self.anim_job)
            except Exception:
                pass
            self.anim_job = None

    def _animate(self):
        if not self.running:
            return

        now = time.time()
        samples, sr, ts, source = AudioEngine.get_vis_snapshot()
        is_active_audio = (now - ts) <= 0.12 and np.max(np.abs(samples)) > 1e-4

        tier_upper = self.current_emotion.upper().replace("_", " ")
        if is_active_audio:
            target_bands = self._compute_log_bands(samples, sr)
            # Fast attack (0.62), smooth decay (0.28)
            rising = target_bands > self.smooth_bands
            self.smooth_bands = np.where(
                rising,
                self.smooth_bands * 0.38 + target_bands * 0.62,
                self.smooth_bands * 0.72 + target_bands * 0.28
            )
            src_tag = "VOICE SYNTHESIS" if source == "voice" else "HARMONY AUDIO"
            if self.hdr_state_id:
                self.canvas.itemconfig(self.hdr_state_id, text=f"TIER // {tier_upper} [{src_tag}]")
        else:
            # Gentle idle limbic breathing wave so the bay always feels alive
            phase = now * 2.2
            idx_arr = np.arange(self.NUM_BANDS, dtype=np.float32)
            idle_wave = 0.025 + 0.018 * np.sin(phase + idx_arr * 0.18) * np.sin(phase * 0.5 - idx_arr * 0.07)
            self.smooth_bands = self.smooth_bands * 0.84 + idle_wave * 0.16
            if self.hdr_state_id:
                self.canvas.itemconfig(self.hdr_state_id, text=f"TIER // {tier_upper} [IDLE RESONANCE]")

        # Update peak-hold caps with gravity
        for i in range(self.NUM_BANDS):
            val = float(self.smooth_bands[i])
            if val >= self.peak_holds[i]:
                self.peak_holds[i] = val
                self.peak_velocities[i] = 0.0
            else:
                self.peak_velocities[i] = min(0.045, self.peak_velocities[i] + 0.0018)
                self.peak_holds[i] = max(val, self.peak_holds[i] - self.peak_velocities[i])

        # Update pre-allocated canvas items in-place
        usable_w = max(64, self.width - 28)
        slot_w = usable_w / self.NUM_BANDS
        bar_w = max(2.0, slot_w - 2.0)

        top_margin = 52
        baseline_y = int(self.height * 0.73)
        max_bar_h = max(40, baseline_y - top_margin)
        max_refl_h = max(20, (self.height - 28) - baseline_y)

        for i in range(self.NUM_BANDS):
            x0 = 14 + i * slot_w
            x1 = x0 + bar_w

            amp = float(self.smooth_bands[i])
            bar_h = max(2.0, amp * max_bar_h)
            y1 = baseline_y - bar_h

            # 1. Main upward bar
            self.canvas.coords(self.bar_ids[i], x0, y1, x1, baseline_y)

            # 2. Floating peak-hold cap
            peak_amp = float(self.peak_holds[i])
            peak_y = baseline_y - max(4.0, peak_amp * max_bar_h) - 2.0
            self.canvas.coords(self.peak_ids[i], x0, peak_y - 2.0, x1, peak_y)

            # 3. Sub-baseline glass reflection bar
            refl_h = max(1.0, amp * max_refl_h * 0.36)
            self.canvas.coords(self.refl_ids[i], x0, baseline_y + 3, x1, baseline_y + 3 + refl_h)

        # ~30 FPS cadence (33ms) for zero Tkinter event-loop congestion
        self.anim_job = self.canvas.after(33, self._animate)


class AvatarModule:
    """
    Coordinates Calypso's 512x512 visual bay across multiple display backends:
      - 'spectrum'    : Real-Time FFT Voice & Limbic Spectrum Analyzer (0 MB VRAM)
      - 'liveportrait': FasterLivePortrait + JoyVASA Neural Avatar driving driver_images/
      - 'webp'        : 512x512 Animated WebP emotional loops (0 MB VRAM)
    """
    VALID_MODES = ("spectrum", "liveportrait", "webp")

    # Easter egg: while the Harmony Shared Listening player is actively playing,
    # users in Animated WebP mode see Calypso dance (avatars/dance.webp).
    DANCE_EMOTION = "dance"

    def __init__(self, avatar_label=None, heart_label=None):
        self.avatars_dir = config.AVATARS_DIR
        self.target_label = avatar_label
        self.avatar_bay = avatar_label.master if avatar_label else None
        self.current_emotion = "neutral"
        self.dance_active = False

        self.avatar_player = AnimatedWebPPlayer(avatar_label, fallback_name="neutral", default_delay_ms=67)
        self.spectrum_analyzer = (
            RealtimeSpectrumAnalyzer(self.avatar_bay, width=512, height=512, bg="#0c0e15")
            if self.avatar_bay else None
        )
        self.live_portrait = LivePortraitEngine(
            target_label=avatar_label,
            symbolic_fallback_cb=self._on_symbolic_fallback
        )

        saved_mode = str(settings_manager.get("avatar_mode", "spectrum") or "spectrum").lower().strip()
        if saved_mode not in self.VALID_MODES:
            saved_mode = "spectrum"
        self.mode = None
        self.set_mode(saved_mode, persist=False)

    def _on_symbolic_fallback(self, emotion: str):
        """Plays the animated WebP loop when a state in driver_images is symbolic art (e.g. dream_state, autonomous)."""
        if self.mode == "liveportrait" and self.avatar_player.target_label:
            self.avatar_player.load_and_play(self.avatars_dir, emotion)

    def set_labels(self, avatar_label, heart_label=None):
        self.target_label = avatar_label
        self.avatar_player.target_label = avatar_label
        self.live_portrait.target_label = avatar_label
        self.avatar_bay = avatar_label.master if avatar_label else None
        if self.avatar_bay and self.spectrum_analyzer is None:
            self.spectrum_analyzer = RealtimeSpectrumAnalyzer(self.avatar_bay, width=512, height=512, bg="#0c0e15")

    def set_mode(self, mode: str, persist: bool = True):
        """Hot-swaps the active avatar bay backend ('spectrum', 'liveportrait', or 'webp') at runtime."""
        clean_mode = (mode or "spectrum").lower().strip()
        if clean_mode not in self.VALID_MODES:
            clean_mode = "spectrum"

        if persist:
            settings_manager.save({"avatar_mode": clean_mode})

        if clean_mode == self.mode:
            return

        self.mode = clean_mode

        if self.mode == "spectrum":
            self.avatar_player.cancel()
            self.live_portrait.stop()
            if self.target_label:
                self.target_label.pack_forget()
            if self.spectrum_analyzer:
                self.spectrum_analyzer.update_emotion_palette(self.current_emotion)
                self.spectrum_analyzer.canvas.pack(fill=tk.BOTH, expand=True, padx=0, pady=0)
                self.spectrum_analyzer.start()
        elif self.mode == "liveportrait":
            if self.spectrum_analyzer:
                self.spectrum_analyzer.stop()
                self.spectrum_analyzer.canvas.pack_forget()
            self.avatar_player.cancel()
            if self.target_label:
                self.target_label.pack(fill=tk.BOTH, expand=True, padx=0, pady=0)
                self.live_portrait.load_emotion(self.current_emotion)
        else:
            if self.spectrum_analyzer:
                self.spectrum_analyzer.stop()
                self.spectrum_analyzer.canvas.pack_forget()
            self.live_portrait.stop()
            if self.target_label:
                self.target_label.pack(fill=tk.BOTH, expand=True, padx=0, pady=0)
                self.avatar_player.load_and_play(self.avatars_dir, self._webp_target_emotion())

    # -------------------------------------------------------------------------
    # DANCE EASTER EGG (Animated WebP mode + Harmony music playing)
    # -------------------------------------------------------------------------
    def _webp_target_emotion(self) -> str:
        """Returns the loop the WebP player should show (dance overrides the felt emotion)."""
        return self.DANCE_EMOTION if self.dance_active else self.current_emotion

    def is_dancing(self) -> bool:
        """True only when the dance easter egg is visibly active (requires Animated WebP mode)."""
        return bool(self.dance_active and self.mode == "webp")

    def set_dance_active(self, active: bool) -> bool:
        """
        Arms/disarms the dance easter egg. Safe to call from any thread.
        The underlying felt emotion (current_emotion) is preserved so the bay
        returns to it as soon as the music stops or pauses.
        Returns True if the visible dance state changed.
        """
        active = bool(active)
        if active == self.dance_active:
            return False
        was_dancing = self.is_dancing()
        self.dance_active = active

        if self.mode == "webp" and self.avatar_player.target_label:
            target = self._webp_target_emotion()
            self.avatar_player.target_label.after(
                0, lambda: self.avatar_player.load_and_play(self.avatars_dir, target)
            )
        return was_dancing != self.is_dancing()

    def toggle_mode(self) -> str:
        """Cycles through 'spectrum' -> 'liveportrait' -> 'webp' and returns the newly active mode."""
        idx = self.VALID_MODES.index(self.mode) if self.mode in self.VALID_MODES else 0
        next_mode = self.VALID_MODES[(idx + 1) % len(self.VALID_MODES)]
        self.set_mode(next_mode, persist=True)
        return self.mode

    def display(self, emotion: str):
        clean_emotion = (emotion or "neutral").lower().strip()
        self.current_emotion = clean_emotion

        if self.spectrum_analyzer:
            if self.target_label:
                self.target_label.after(0, lambda: self.spectrum_analyzer.update_emotion_palette(clean_emotion))
            else:
                self.spectrum_analyzer.update_emotion_palette(clean_emotion)

        if self.mode == "liveportrait" and self.target_label:
            self.avatar_player.cancel()
            self.target_label.after(0, lambda: self.live_portrait.load_emotion(clean_emotion))
        elif self.mode == "webp" and self.avatar_player.target_label:
            target = self._webp_target_emotion()
            self.avatar_player.target_label.after(
                0, lambda: self.avatar_player.load_and_play(self.avatars_dir, target)
            )
