# modules/settings_dialog.py

import os
import webbrowser
from pathlib import Path
import threading
import tkinter as tk
from tkinter import filedialog, messagebox
import customtkinter as ctk
from modules.settings_manager import settings_manager
from modules.config import config
from modules.hardware_sentinel import hardware_sentinel


class SettingsWindow:
    def __init__(self, parent_root, on_save_callback=None):
        self.root = parent_root
        self.on_save_callback = on_save_callback

        self.win = ctk.CTkToplevel(parent_root)
        self.win.title("System Preferences & Core Configuration")
        self.win.geometry("780x760")
        self.win.minsize(700, 640)
        self.win.configure(fg_color="#0c0e15")
        self.win.transient(parent_root)
        self.win.grab_set()

        # Header Frame
        hdr = ctk.CTkFrame(self.win, fg_color="#141824", corner_radius=0, height=54)
        hdr.pack(fill="x", padx=0, pady=0)
        hdr.pack_propagate(False)

        ctk.CTkLabel(
            hdr, text="⚙️ SYSTEM CONFIGURATION & PREFERENCES",
            font=ctk.CTkFont(family="Consolas", size=13, weight="bold"),
            text_color="#38bdf8"
        ).pack(side="left", padx=20)

        ctk.CTkButton(
            hdr, text="🧭 Launch Step-by-Step Setup Wizard", width=220, height=28,
            fg_color="#1e3a5f", hover_color="#2563eb",
            font=ctk.CTkFont(size=11, weight="bold"),
            command=self._launch_onboarding_wizard
        ).pack(side="right", padx=16)

        # Tabview
        self.tabs = ctk.CTkTabview(
            self.win, fg_color="#141824", segmented_button_fg_color="#0c0e15",
            segmented_button_selected_color="#2563eb",
            segmented_button_selected_hover_color="#1d4ed8"
        )
        self.tabs.pack(fill="both", expand=True, padx=16, pady=(10, 8))

        self.tab_identity = self.tabs.add("👤 Identity & Bond")
        self.tab_models = self.tabs.add("🤖 LLM & Vision")
        self.tab_agency = self.tabs.add("⏳ Agency & Reverie")
        self.tab_email = self.tabs.add("📬 Email Correspondence")
        self.tab_audio = self.tabs.add("🎙️ Voice & Audio")

        # Build each tab
        self._build_identity_tab()
        self._build_models_tab()
        self._build_agency_tab()
        self._build_email_tab()
        self._build_audio_tab()

        # Bottom Footer Action Bar
        footer = ctk.CTkFrame(self.win, fg_color="#10141f", corner_radius=0, height=52)
        footer.pack(fill="x", side="bottom")
        footer.pack_propagate(False)

        ctk.CTkLabel(
            footer, text="Preferences persist to user_preferences.json",
            font=ctk.CTkFont(size=10, slant="italic"), text_color="#64748b"
        ).pack(side="left", padx=20)

        ctk.CTkButton(
            footer, text="Save & Apply", width=120, height=32,
            fg_color="#059669", hover_color="#047857", font=ctk.CTkFont(weight="bold"),
            command=self._save_and_close
        ).pack(side="right", padx=16)

        ctk.CTkButton(
            footer, text="Cancel", width=90, height=32,
            fg_color="#334155", hover_color="#475569",
            command=self.win.destroy
        ).pack(side="right", padx=(0, 4))

    # -------------------------------------------------------------------------
    # TAB 1: IDENTITY & BOND
    # -------------------------------------------------------------------------
    def _build_identity_tab(self):
        t = self.tab_identity
        t.columnconfigure(1, weight=1)

        self._add_header_desc(t, "Companion & Persona Identity", "Defines identity variables and call signs across memory modules.")

        # Companion Full Name
        ctk.CTkLabel(t, text="Companion Name:", font=ctk.CTkFont(size=11, weight="bold")).grid(row=1, column=0, sticky="w", padx=16, pady=8)
        self.ent_companion_name = ctk.CTkEntry(t, width=280, fg_color="#1a2030", border_color="#2b354d")
        self.ent_companion_name.insert(0, settings_manager.get("companion_name", "Companion"))
        self.ent_companion_name.grid(row=1, column=1, sticky="w", padx=16, pady=8)

        # Companion Nickname / Preferred Call Sign
        ctk.CTkLabel(t, text="Nickname / Call Sign:", font=ctk.CTkFont(size=11, weight="bold")).grid(row=2, column=0, sticky="w", padx=16, pady=8)
        self.ent_nickname = ctk.CTkEntry(t, width=280, fg_color="#1a2030", border_color="#2b354d")
        self.ent_nickname.insert(0, settings_manager.get("companion_nickname", ""))
        self.ent_nickname.grid(row=2, column=1, sticky="w", padx=16, pady=8)

        # Persona Name
        ctk.CTkLabel(t, text="AI Persona Name:", font=ctk.CTkFont(size=11, weight="bold")).grid(row=3, column=0, sticky="w", padx=16, pady=8)
        self.ent_ai_name = ctk.CTkEntry(t, width=280, fg_color="#1a2030", border_color="#2b354d")
        self.ent_ai_name.insert(0, settings_manager.get("ai_name", "Calypso"))
        self.ent_ai_name.grid(row=3, column=1, sticky="w", padx=16, pady=8)

        # Avatar Visual Bay Mode
        ctk.CTkLabel(t, text="Avatar Visual Bay Mode:", font=ctk.CTkFont(size=11, weight="bold")).grid(row=4, column=0, sticky="w", padx=16, pady=8)
        self._avatar_mode_map = {
            "Spectrum Analyzer (Real-Time Voice & Limbic FFT — 0 VRAM)": "spectrum",
            "FasterLivePortrait + JoyVASA (calypso.png — Real-Time ONNX Lip-Sync)": "liveportrait",
            "Animated Portrait Loops (512x512 WebP — 0 VRAM)": "webp",
        }
        self._avatar_mode_rev = {v: k for k, v in self._avatar_mode_map.items()}
        cur_av_mode = str(settings_manager.get("avatar_mode", "spectrum") or "spectrum").lower().strip()
        self.cbo_avatar_mode = ctk.CTkComboBox(
            t, width=410,
            values=list(self._avatar_mode_map.keys()),
            fg_color="#1a2030", border_color="#2b354d"
        )
        self.cbo_avatar_mode.set(self._avatar_mode_rev.get(cur_av_mode, list(self._avatar_mode_map.keys())[0]))
        self.cbo_avatar_mode.grid(row=4, column=1, sticky="w", padx=16, pady=8)

        # LivePortrait Primary Driver & ONNX Status Row
        lp_box = ctk.CTkFrame(t, fg_color="#10141f", corner_radius=6, border_width=1, border_color="#1e293b")
        lp_box.grid(row=5, column=0, columnspan=2, sticky="ew", padx=16, pady=(6, 8))

        from modules.live_portrait_engine import LivePortraitEngine, REQUIRED_ONNX_FILES
        models_dir = getattr(config, "LIVEPORTRAIT_MODELS_DIR", config.BASE_DIR / "liveportrait_models")
        has_onnx = all((models_dir / f).is_file() for f in REQUIRED_ONNX_FILES)
        primary_path = getattr(config, "DIFFUSION_MODELS_DIR", config.BASE_DIR / "diffusion_models") / getattr(
            config, "SOURCE_FACE_IMAGE", "calypso.png"
        )
        driver_label = primary_path.name if primary_path.is_file() else "neutral.png"

        status_txt = (
            f"🧬 LivePortrait Primary Driver: {driver_label} "
            + ("(ONNX + CUDA FP16 Suite Active)" if has_onnx else "(ONNX Models Missing — Click Fetch)")
        )
        self.lbl_lp_status = ctk.CTkLabel(
            lp_box, text=status_txt, font=ctk.CTkFont(size=10), text_color="#34d399"
        )
        self.lbl_lp_status.pack(side="left", padx=12, pady=8)

        def _fetch_lp_onnx():
            self.btn_fetch_lp.configure(state="disabled", text="⏳ Downloading...")
            def _worker():
                ok, msg = LivePortraitEngine.download_onnx_models(
                    progress_cb=lambda s: self.win.after(0, lambda: self.lbl_lp_status.configure(text=f"⏳ {s}", text_color="#38bdf8"))
                )
                def _done():
                    if not self.win.winfo_exists():
                        return
                    self.btn_fetch_lp.configure(state="normal", text="⬇️ Fetch ONNX Suite")
                    self.lbl_lp_status.configure(text=msg, text_color="#34d399" if ok else "#f59e0b")
                self.win.after(0, _done)
            threading.Thread(target=_worker, daemon=True).start()

        self.btn_fetch_lp = ctk.CTkButton(
            lp_box, text="⬇️ Fetch ONNX Suite", width=135, height=24,
            fg_color="#1e293b", hover_color="#334155", font=ctk.CTkFont(size=10),
            command=_fetch_lp_onnx
        )
        self.btn_fetch_lp.pack(side="right", padx=10, pady=6)

    # -------------------------------------------------------------------------
    # TAB 2: LLM & VISION
    # -------------------------------------------------------------------------
    def _build_models_tab(self):
        t = self.tab_models

        scroll = ctk.CTkScrollableFrame(t, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=4, pady=4)

        hdr_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        hdr_frame.pack(fill="x", padx=12, pady=(4, 10))
        ctk.CTkLabel(
            hdr_frame, 
            text="Ollama, Stable Diffusion & AudioCraft Orchestration", 
            font=ctk.CTkFont(size=13, weight="bold"), 
            text_color="#f8fafc"
        ).pack(anchor="w")
        ctk.CTkLabel(
            hdr_frame, 
            text="Select LLM models, Stable Diffusion checkpoints, AudioCraft models, and generation parameters.", 
            font=ctk.CTkFont(size=10), 
            text_color="#94a3b8"
        ).pack(anchor="w")

        # LLM Section
        sec_a = ctk.CTkFrame(scroll, fg_color="#141824", corner_radius=8, border_width=1, border_color="#1e2538")
        sec_a.pack(fill="x", padx=8, pady=(0, 12))
        sec_a.columnconfigure(1, weight=1)

        ctk.CTkLabel(
            sec_a, text="🧠 Large Language Model & Cognitive Horizon",
            font=ctk.CTkFont(size=12, weight="bold"), text_color="#38bdf8"
        ).grid(row=0, column=0, columnspan=2, sticky="w", padx=16, pady=(12, 6))

        # Hardware Sentinel Banner
        gpu_info = hardware_sentinel.get_gpu_info()
        rec_profile_id = hardware_sentinel.recommend_profile()
        self._current_profile_key = settings_manager.get("cognitive_profile", rec_profile_id)

        hw_banner = ctk.CTkFrame(sec_a, fg_color="#0f172a", corner_radius=6, border_width=1, border_color="#1e293b")
        hw_banner.grid(row=1, column=0, columnspan=2, sticky="ew", padx=16, pady=(0, 10))

        ctk.CTkLabel(
            hw_banner,
            text=f"🎮 Hardware Detected: {gpu_info['summary']}",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color="#38bdf8"
        ).pack(side="left", padx=10, pady=6)

        rec_name = hardware_sentinel.PROFILES.get(rec_profile_id, {}).get("name", "Deep Contemplative")
        ctk.CTkLabel(
            hw_banner,
            text=f"★ Recommended: {rec_name}",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color="#22c55e"
        ).pack(side="right", padx=10, pady=6)

        ctk.CTkLabel(sec_a, text="Ollama Endpoint:", font=ctk.CTkFont(size=11, weight="bold")).grid(row=2, column=0, sticky="w", padx=16, pady=5)
        self.ent_ollama_url = ctk.CTkEntry(sec_a, width=320, fg_color="#1a2030", border_color="#2b354d")
        self.ent_ollama_url.insert(0, settings_manager.get("ollama_url", "http://localhost:11434"))
        self.ent_ollama_url.grid(row=2, column=1, sticky="w", padx=16, pady=5)

        ctk.CTkLabel(sec_a, text="Gemma 4 LLM (Supported):", font=ctk.CTkFont(size=11, weight="bold")).grid(row=3, column=0, sticky="w", padx=16, pady=5)
        model_row = ctk.CTkFrame(sec_a, fg_color="transparent")
        model_row.grid(row=3, column=1, sticky="ew", padx=16, pady=5)

        current_model = settings_manager.get("model_name", config.MODEL_NAME)
        gemma4_models = settings_manager.fetch_installed_ollama_models(gemma4_only=True)
        if current_model and hardware_sentinel.is_gemma4_model(current_model) and current_model not in gemma4_models:
            gemma4_models.insert(0, current_model)
        self.cbo_model = ctk.CTkComboBox(model_row, width=300, values=gemma4_models, fg_color="#1a2030", border_color="#2b354d", command=lambda _: self._update_vram_gauge())
        self.cbo_model.set(current_model if hardware_sentinel.is_gemma4_model(current_model) else gemma4_models[0])
        self.cbo_model.pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            model_row, text="🔄 Fetch", width=75, height=28,
            fg_color="#334155", hover_color="#475569",
            command=self._refresh_ollama_models
        ).pack(side="left")

        ctk.CTkLabel(sec_a, text="Cognitive Profiles:", font=ctk.CTkFont(size=11, weight="bold")).grid(row=4, column=0, sticky="w", padx=16, pady=5)
        prof_box = ctk.CTkFrame(sec_a, fg_color="transparent")
        prof_box.grid(row=4, column=1, sticky="w", padx=16, pady=5)

        ctk.CTkButton(
            prof_box, text="Deep Contemplative (32k/8k)", width=170, height=24,
            fg_color="#1e293b", hover_color="#334155", font=ctk.CTkFont(size=10),
            command=lambda: self._apply_cognitive_profile("deep_contemplative")
        ).pack(side="left", padx=(0, 6))

        ctk.CTkButton(
            prof_box, text="Balanced (16k/4k)", width=125, height=24,
            fg_color="#1e293b", hover_color="#334155", font=ctk.CTkFont(size=10),
            command=lambda: self._apply_cognitive_profile("balanced")
        ).pack(side="left", padx=(0, 6))

        ctk.CTkButton(
            prof_box, text="Grounded (8k/2k)", width=115, height=24,
            fg_color="#1e293b", hover_color="#334155", font=ctk.CTkFont(size=10),
            command=lambda: self._apply_cognitive_profile("grounded")
        ).pack(side="left")

        ctk.CTkLabel(sec_a, text="Context Window (num_ctx):", font=ctk.CTkFont(size=11, weight="bold")).grid(row=5, column=0, sticky="w", padx=16, pady=5)
        self.cbo_ctx = ctk.CTkComboBox(sec_a, width=160, values=["8192", "16384", "32768", "65536"], fg_color="#1a2030", command=self._on_ctx_changed)
        self.cbo_ctx.set(str(settings_manager.get("num_ctx", 32768)))
        self.cbo_ctx.grid(row=5, column=1, sticky="w", padx=16, pady=5)

        ctk.CTkLabel(sec_a, text="Thought & Output Budget:", font=ctk.CTkFont(size=11, weight="bold")).grid(row=6, column=0, sticky="w", padx=16, pady=5)
        predict_box = ctk.CTkFrame(sec_a, fg_color="transparent")
        predict_box.grid(row=6, column=1, sticky="w", padx=16, pady=5)

        current_predict = int(settings_manager.get("num_predict", 8192))
        self.slider_predict = ctk.CTkSlider(predict_box, from_=1024, to=12288, number_of_steps=11, width=200)
        self.slider_predict.set(current_predict)
        self.slider_predict.pack(side="left", padx=(0, 10))

        self.lbl_predict_val = ctk.CTkLabel(predict_box, text=f"{current_predict} tokens", font=ctk.CTkFont(family="Consolas"))
        self.lbl_predict_val.pack(side="left")
        self.slider_predict.configure(command=self._on_predict_slider_moved)

        ctk.CTkLabel(sec_a, text="Temperature (Creativity):", font=ctk.CTkFont(size=11, weight="bold")).grid(row=7, column=0, sticky="w", padx=16, pady=5)
        temp_row = ctk.CTkFrame(sec_a, fg_color="transparent")
        temp_row.grid(row=7, column=1, sticky="w", padx=16, pady=5)

        self.slider_temp = ctk.CTkSlider(temp_row, from_=0.1, to=1.5, number_of_steps=28, width=200)
        self.slider_temp.set(float(settings_manager.get("temperature", 0.8)))
        self.slider_temp.pack(side="left", padx=(0, 10))

        self.lbl_temp_val = ctk.CTkLabel(temp_row, text=f"{self.slider_temp.get():.2f}", font=ctk.CTkFont(family="Consolas"))
        self.lbl_temp_val.pack(side="left")
        self.slider_temp.configure(command=lambda v: self.lbl_temp_val.configure(text=f"{float(v):.2f}"))

        gauge_box = ctk.CTkFrame(sec_a, fg_color="transparent")
        gauge_box.grid(row=8, column=0, columnspan=2, sticky="w", padx=16, pady=(4, 12))

        self.lbl_vram_gauge = ctk.CTkLabel(
            gauge_box,
            text="",
            font=ctk.CTkFont(family="Consolas", size=10, weight="bold")
        )
        self.lbl_vram_gauge.pack(side="left")
        self._update_vram_gauge()

        # Stable Diffusion Section
        sec_b = ctk.CTkFrame(scroll, fg_color="#141824", corner_radius=8, border_width=1, border_color="#1e2538")
        sec_b.pack(fill="x", padx=8, pady=(0, 12))
        sec_b.columnconfigure(1, weight=1)

        ctk.CTkLabel(
            sec_b, text="🎨 Stable Diffusion & Image Generation",
            font=ctk.CTkFont(size=12, weight="bold"), text_color="#38bdf8"
        ).grid(row=0, column=0, columnspan=2, sticky="w", padx=16, pady=(12, 6))

        ctk.CTkLabel(sec_b, text="Diffusion Checkpoint:", font=ctk.CTkFont(size=11, weight="bold")).grid(row=1, column=0, sticky="w", padx=16, pady=5)
        sd_row = ctk.CTkFrame(sec_b, fg_color="transparent")
        sd_row.grid(row=1, column=1, sticky="ew", padx=16, pady=5)

        current_sd = settings_manager.get("sd_model", getattr(config, "SD_MODEL", "sd_xl_base_1.0.safetensors"))
        self.cbo_sd_model = ctk.CTkComboBox(sd_row, width=300, values=[current_sd], fg_color="#1a2030", border_color="#2b354d")
        self.cbo_sd_model.set(current_sd)
        self.cbo_sd_model.pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            sd_row, text="🔄 Fetch", width=75, height=28,
            fg_color="#334155", hover_color="#475569",
            command=self._refresh_sd_models
        ).pack(side="left")

        ctk.CTkLabel(sec_b, text="Recommended Profiles:", font=ctk.CTkFont(size=11, weight="bold")).grid(row=2, column=0, sticky="w", padx=16, pady=5)
        preset_box = ctk.CTkFrame(sec_b, fg_color="transparent")
        preset_box.grid(row=2, column=1, sticky="w", padx=16, pady=5)

        ctk.CTkButton(
            preset_box, text="SDXL Standard", width=110, height=24,
            fg_color="#1e293b", hover_color="#334155", font=ctk.CTkFont(size=10),
            command=lambda: self._apply_diffusion_profile("sdxl_base")
        ).pack(side="left", padx=(0, 6))

        ctk.CTkButton(
            preset_box, text="SDXL Lightning/Turbo", width=135, height=24,
            fg_color="#1e293b", hover_color="#334155", font=ctk.CTkFont(size=10),
            command=lambda: self._apply_diffusion_profile("sdxl_turbo")
        ).pack(side="left", padx=(0, 6))

        ctk.CTkButton(
            preset_box, text="SD 1.5 Classic", width=105, height=24,
            fg_color="#1e293b", hover_color="#334155", font=ctk.CTkFont(size=10),
            command=lambda: self._apply_diffusion_profile("sd15")
        ).pack(side="left")

        ctk.CTkLabel(sec_b, text="Inference Steps:", font=ctk.CTkFont(size=11, weight="bold")).grid(row=3, column=0, sticky="w", padx=16, pady=5)
        steps_box = ctk.CTkFrame(sec_b, fg_color="transparent")
        steps_box.grid(row=3, column=1, sticky="w", padx=16, pady=5)

        self.slider_steps = ctk.CTkSlider(steps_box, from_=4, to=60, number_of_steps=56, width=200)
        self.slider_steps.set(int(settings_manager.get("sd_steps", 25)))
        self.slider_steps.pack(side="left", padx=(0, 10))

        self.lbl_steps_val = ctk.CTkLabel(steps_box, text=f"{int(self.slider_steps.get())}", font=ctk.CTkFont(family="Consolas"))
        self.lbl_steps_val.pack(side="left")
        self.slider_steps.configure(command=lambda v: self.lbl_steps_val.configure(text=f"{int(float(v))}"))

        ctk.CTkLabel(sec_b, text="CFG Guidance Scale:", font=ctk.CTkFont(size=11, weight="bold")).grid(row=4, column=0, sticky="w", padx=16, pady=5)
        cfg_box = ctk.CTkFrame(sec_b, fg_color="transparent")
        cfg_box.grid(row=4, column=1, sticky="w", padx=16, pady=5)

        self.slider_cfg = ctk.CTkSlider(cfg_box, from_=1.0, to=15.0, number_of_steps=28, width=200)
        self.slider_cfg.set(float(settings_manager.get("sd_guidance_scale", 6.0)))
        self.slider_cfg.pack(side="left", padx=(0, 10))

        self.lbl_cfg_val = ctk.CTkLabel(cfg_box, text=f"{self.slider_cfg.get():.1f}", font=ctk.CTkFont(family="Consolas"))
        self.lbl_cfg_val.pack(side="left")
        self.slider_cfg.configure(command=lambda v: self.lbl_cfg_val.configure(text=f"{float(v):.1f}"))

        ctk.CTkLabel(sec_b, text="Output Resolution:", font=ctk.CTkFont(size=11, weight="bold")).grid(row=5, column=0, sticky="w", padx=16, pady=5)
        self.cbo_res = ctk.CTkComboBox(
            sec_b, width=280,
            values=[
                "1024 x 1024 (1:1 Square)",
                "896 x 1152 (3:4 Portrait)",
                "1152 x 896 (4:3 Landscape)",
                "832 x 1216 (9:16 Tall Portrait)",
                "1216 x 832 (16:9 Cinema Landscape)",
                "512 x 512 (SD 1.5 Classic)"
            ],
            fg_color="#1a2030"
        )
        self.cbo_res.set(settings_manager.get("sd_resolution", "1024 x 1024 (1:1 Square)"))
        self.cbo_res.grid(row=5, column=1, sticky="w", padx=16, pady=5)

        ctk.CTkLabel(sec_b, text="Identity Preservation:", font=ctk.CTkFont(size=11, weight="bold")).grid(row=6, column=0, sticky="w", padx=16, pady=(5, 14))
        chk_box = ctk.CTkFrame(sec_b, fg_color="transparent")
        chk_box.grid(row=6, column=1, sticky="w", padx=16, pady=(5, 14))

        self.chk_faceswap = ctk.CTkCheckBox(chk_box, text="Enable Face Swap", fg_color="#2563eb")
        if settings_manager.get("sd_enable_face_swap", True):
            self.chk_faceswap.select()
        self.chk_faceswap.pack(side="left", padx=(0, 16))

        self.chk_restore = ctk.CTkCheckBox(chk_box, text="Face Restoration (GFPGAN)", fg_color="#2563eb")
        if settings_manager.get("sd_restore_face", True):
            self.chk_restore.select()
        self.chk_restore.pack(side="left")

        # AudioCraft & Music Generation Section
        sec_c = ctk.CTkFrame(scroll, fg_color="#141824", corner_radius=8, border_width=1, border_color="#1e2538")
        sec_c.pack(fill="x", padx=8, pady=(0, 12))
        sec_c.columnconfigure(1, weight=1)

        ctk.CTkLabel(
            sec_c, text="🎶 AudioCraft & Acoustic Generation",
            font=ctk.CTkFont(size=12, weight="bold"), text_color="#38bdf8"
        ).grid(row=0, column=0, columnspan=2, sticky="w", padx=16, pady=(12, 6))

        ctk.CTkLabel(sec_c, text="AudioCraft Model:", font=ctk.CTkFont(size=11, weight="bold")).grid(row=1, column=0, sticky="w", padx=16, pady=5)
        ac_row = ctk.CTkFrame(sec_c, fg_color="transparent")
        ac_row.grid(row=1, column=1, sticky="ew", padx=16, pady=5)

        current_ac = settings_manager.get("audiocraft_model", getattr(config, "MUSICGEN_MODEL", ""))
        discovered_ac = settings_manager.fetch_installed_audiocraft_models()
        ac_values = discovered_ac if discovered_ac else ([current_ac] if current_ac else ["None"])
        if current_ac and current_ac not in ac_values:
            ac_values = [current_ac] + ac_values

        self.cbo_ac_model = ctk.CTkComboBox(ac_row, width=300, values=ac_values, fg_color="#1a2030", border_color="#2b354d")
        self.cbo_ac_model.set(current_ac or (discovered_ac[0] if discovered_ac else ""))
        self.cbo_ac_model.pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            ac_row, text="🔄 Fetch", width=75, height=28,
            fg_color="#334155", hover_color="#475569",
            command=self._refresh_audiocraft_models
        ).pack(side="left", padx=(0, 6))

        ctk.CTkButton(
            ac_row, text="🌐 Official HF Model", width=130, height=28,
            fg_color="#1e3a5f", hover_color="#2563eb",
            font=ctk.CTkFont(size=10, weight="bold"),
            command=lambda: webbrowser.open("https://huggingface.co/facebook/musicgen-medium")
        ).pack(side="left")

        ctk.CTkLabel(
            sec_c,
            text=(
                "Official Hugging Face Models: 'facebook/musicgen-medium' (Recommended, 8.0 GB float32) or 'facebook/musicgen-small' (2.4 GB).\n"
                " link: https://huggingface.co/facebook/musicgen-medium  (Avoid 4 GB fp16 third-party exports, which cause audio garbling)."
            ),
            font=ctk.CTkFont(size=9, slant="italic"),
            text_color="#64748b",
            justify="left"
        ).grid(row=2, column=1, sticky="w", padx=16, pady=(0, 4))

        ctk.CTkLabel(sec_c, text="Acoustic Tuning:", font=ctk.CTkFont(size=11, weight="bold")).grid(row=3, column=0, sticky="w", padx=16, pady=5)
        ctk.CTkLabel(
            sec_c,
            text="Locked to studio-calibrated float32 precision (Top-K=250, Temp=1.0, and dynamic emotional CFG per theme).",
            font=ctk.CTkFont(size=10, slant="italic"),
            text_color="#94a3b8"
        ).grid(row=3, column=1, sticky="w", padx=16, pady=5)

        ctk.CTkLabel(sec_c, text="Track Duration:", font=ctk.CTkFont(size=11, weight="bold")).grid(row=4, column=0, sticky="w", padx=16, pady=5)
        ac_dur_box = ctk.CTkFrame(sec_c, fg_color="transparent")
        ac_dur_box.grid(row=4, column=1, sticky="w", padx=16, pady=5)

        self.slider_ac_dur = ctk.CTkSlider(ac_dur_box, from_=5, to=60, number_of_steps=11, width=200)
        self.slider_ac_dur.set(int(settings_manager.get("audiocraft_duration", 30)))
        self.slider_ac_dur.pack(side="left", padx=(0, 10))

        self.lbl_ac_dur_val = ctk.CTkLabel(ac_dur_box, text=f"{int(self.slider_ac_dur.get())}s", font=ctk.CTkFont(family="Consolas"))
        self.lbl_ac_dur_val.pack(side="left")
        self.slider_ac_dur.configure(command=lambda v: self.lbl_ac_dur_val.configure(text=f"{int(float(v))}s"))

        ctk.CTkLabel(sec_c, text="Pipeline Control:", font=ctk.CTkFont(size=11, weight="bold")).grid(row=5, column=0, sticky="w", padx=16, pady=(5, 6))
        ac_chk_box = ctk.CTkFrame(sec_c, fg_color="transparent")
        ac_chk_box.grid(row=5, column=1, sticky="w", padx=16, pady=(5, 6))

        self.chk_audiocraft_enabled = ctk.CTkCheckBox(
            ac_chk_box,
            text="Enable AudioCraft Music Synthesis Pipeline (16 GB+ VRAM recommended; Off by default on <16 GB)",
            fg_color="#2563eb"
        )
        if settings_manager.get("audiocraft_enabled", False):
            self.chk_audiocraft_enabled.select()
        self.chk_audiocraft_enabled.pack(side="left")

        ac_online_box = ctk.CTkFrame(sec_c, fg_color="transparent")
        ac_online_box.grid(row=6, column=1, sticky="w", padx=16, pady=(0, 14))

        self.chk_audiocraft_online = ctk.CTkCheckBox(
            ac_online_box,
            text="Allow Online Hugging Face Model Download (Opt-in; Offline by default)",
            fg_color="#2563eb"
        )
        if settings_manager.get("audiocraft_allow_online", False):
            self.chk_audiocraft_online.select()
        self.chk_audiocraft_online.pack(side="left")

    def _apply_diffusion_profile(self, profile_key: str):
        if profile_key == "sdxl_base":
            self.slider_steps.set(28)
            self.lbl_steps_val.configure(text="28")
            self.slider_cfg.set(6.5)
            self.lbl_cfg_val.configure(text="6.5")
            if "512" in self.cbo_res.get():
                self.cbo_res.set("1024 x 1024 (1:1 Square)")
        elif profile_key == "sdxl_turbo":
            self.slider_steps.set(6)
            self.lbl_steps_val.configure(text="6")
            self.slider_cfg.set(2.0)
            self.lbl_cfg_val.configure(text="2.0")
            if "512" in self.cbo_res.get():
                self.cbo_res.set("1024 x 1024 (1:1 Square)")
        elif profile_key == "sd15":
            self.slider_steps.set(25)
            self.lbl_steps_val.configure(text="25")
            self.slider_cfg.set(7.0)
            self.lbl_cfg_val.configure(text="7.0")
            self.cbo_res.set("512 x 512 (SD 1.5 Classic)")

    def _apply_cognitive_profile(self, profile_key: str):
        prof = hardware_sentinel.PROFILES.get(profile_key)
        if not prof:
            return
        self.cbo_ctx.set(str(prof["num_ctx"]))
        self.slider_predict.set(prof["num_predict"])
        self.lbl_predict_val.configure(text=f"{prof['num_predict']} tokens")
        self._current_profile_key = profile_key
        self._update_vram_gauge()

    def _on_predict_slider_moved(self, value):
        val_int = int(float(value))
        self.lbl_predict_val.configure(text=f"{val_int} tokens")
        self._current_profile_key = "custom"
        self._update_vram_gauge()

    def _on_ctx_changed(self, choice):
        self._current_profile_key = "custom"
        self._update_vram_gauge()

    def _update_vram_gauge(self):
        try:
            model = self.cbo_model.get().strip() if hasattr(self, "cbo_model") else ""
            ctx = int(self.cbo_ctx.get().strip()) if hasattr(self, "cbo_ctx") else 32768
            est = hardware_sentinel.estimate_vram_usage(model, ctx)
            if hasattr(self, "lbl_vram_gauge"):
                self.lbl_vram_gauge.configure(
                    text=f"📊 Footprint: {est['status_text']}",
                    text_color=est["color"]
                )
        except Exception:
            pass

    def _refresh_ollama_models(self):
        models = settings_manager.fetch_installed_ollama_models(gemma4_only=True)
        if models:
            self.cbo_model.configure(values=models)
            messagebox.showinfo(
                "Gemma 4 Models",
                f"Loaded {len(models)} supported Gemma 4 series model option(s).\n"
                "(Note: Only the Gemma 4 model series is supported by Calypso.)",
                parent=self.win
            )
        else:
            messagebox.showwarning("Notice", "Could not reach Ollama to list Gemma 4 models.", parent=self.win)

    def _refresh_sd_models(self):
        models = settings_manager.fetch_installed_sd_models()
        if models:
            self.cbo_sd_model.configure(values=models)
            messagebox.showinfo("Stable Diffusion", f"Found {len(models)} installed checkpoints in diffusion_models/.")
        else:
            messagebox.showwarning("Notice", "No checkpoints detected in diffusion_models/ folder.")

    def _refresh_audiocraft_models(self):
        models = settings_manager.fetch_installed_audiocraft_models()
        if models:
            self.cbo_ac_model.configure(values=models)
            if not self.cbo_ac_model.get().strip() or self.cbo_ac_model.get().strip() == "None":
                self.cbo_ac_model.set(models[0])
            messagebox.showinfo(
                "AudioCraft Models",
                f"Found {len(models)} AudioCraft model(s) in audiocraft_models/ or local cache."
            )
        else:
            messagebox.showwarning(
                "Notice",
                "No AudioCraft models detected in audiocraft_models/ folder.\n\n"
                "Place a downloaded AudioCraft/MusicGen model folder inside audiocraft_models/ "
                "or type a Hugging Face repository ID manually."
            )

    # -------------------------------------------------------------------------
    # TAB 3: AGENCY & REVERIE
    # -------------------------------------------------------------------------
    def _build_agency_tab(self):
        t = self.tab_agency
        t.columnconfigure(1, weight=1)

        self._add_header_desc(
            t, 
            "Autonomous Drives, Reverie & Research", 
            "Configure daydreaming, letter writing, circadian rest, and unprompted web research."
        )

        ctk.CTkLabel(t, text="Daydream / Reverie Timeout:", font=ctk.CTkFont(size=11, weight="bold")).grid(row=1, column=0, sticky="w", padx=16, pady=6)
        rev_box = ctk.CTkFrame(t, fg_color="transparent")
        rev_box.grid(row=1, column=1, sticky="w", padx=16, pady=6)

        self.ent_reverie_timeout = ctk.CTkEntry(rev_box, width=70, fg_color="#1a2030")
        self.ent_reverie_timeout.insert(0, str(settings_manager.get("reverie_idle_timeout_min", 60)))
        self.ent_reverie_timeout.pack(side="left", padx=(0, 6))
        ctk.CTkLabel(rev_box, text="minutes idle before synthesizing a daydream scenario", text_color="#94a3b8").pack(side="left")

        ctk.CTkLabel(t, text="Letter Writing Timeout:", font=ctk.CTkFont(size=11, weight="bold")).grid(row=2, column=0, sticky="w", padx=16, pady=6)
        ep_box = ctk.CTkFrame(t, fg_color="transparent")
        ep_box.grid(row=2, column=1, sticky="w", padx=16, pady=6)

        self.ent_epistolary_timeout = ctk.CTkEntry(ep_box, width=70, fg_color="#1a2030")
        self.ent_epistolary_timeout.insert(0, str(settings_manager.get("epistolary_idle_timeout_min", 60)))
        self.ent_epistolary_timeout.pack(side="left", padx=(0, 6))
        ctk.CTkLabel(ep_box, text="minutes idle before drafting an unprompted letter", text_color="#94a3b8").pack(side="left")

        ctk.CTkLabel(t, text="Circadian Sleep Window:", font=ctk.CTkFont(size=11, weight="bold")).grid(row=3, column=0, sticky="w", padx=16, pady=6)
        circ_box = ctk.CTkFrame(t, fg_color="transparent")
        circ_box.grid(row=3, column=1, sticky="w", padx=16, pady=6)

        self.cbo_sleep_start = ctk.CTkComboBox(circ_box, width=80, values=[f"{h:02d}:00" for h in range(24)], fg_color="#1a2030")
        self.cbo_sleep_start.set(f"{int(settings_manager.get('circadian_sleep_start', 23)):02d}:00")
        self.cbo_sleep_start.pack(side="left", padx=(0, 4))

        ctk.CTkLabel(circ_box, text="to").pack(side="left", padx=4)

        self.cbo_sleep_end = ctk.CTkComboBox(circ_box, width=80, values=[f"{h:02d}:00" for h in range(24)], fg_color="#1a2030")
        self.cbo_sleep_end.set(f"{int(settings_manager.get('circadian_sleep_end', 7)):02d}:00")
        self.cbo_sleep_end.pack(side="left", padx=4)

        self.chk_circadian = ctk.CTkCheckBox(t, text="Enable Circadian Rest Cycle", fg_color="#2563eb")
        if settings_manager.get("circadian_sleep_enabled", True):
            self.chk_circadian.select()
        self.chk_circadian.grid(row=4, column=1, sticky="w", padx=16, pady=6)

        sub_hdr = ctk.CTkFrame(t, fg_color="transparent")
        sub_hdr.grid(row=5, column=0, columnspan=2, sticky="ew", padx=16, pady=(16, 6))
        ctk.CTkLabel(
            sub_hdr, text="🔍 Autonomous Web Research & Inquiry",
            font=ctk.CTkFont(size=12, weight="bold"), text_color="#38bdf8"
        ).pack(anchor="w")
        ctk.CTkLabel(
            sub_hdr, text="Control unprompted web searches, epistemic auditing, and targeted subject investigation.",
            font=ctk.CTkFont(size=10), text_color="#94a3b8"
        ).pack(anchor="w")

        ctk.CTkLabel(t, text="Web Research:", font=ctk.CTkFont(size=11, weight="bold")).grid(row=6, column=0, sticky="w", padx=16, pady=6)
        self.chk_autonomous_research = ctk.CTkCheckBox(
            t, text="Enable Idle Web Research & Discovery (Opt-In; Offline by default)", fg_color="#2563eb"
        )
        if settings_manager.get("autonomous_research_enabled", False):
            self.chk_autonomous_research.select()
        self.chk_autonomous_research.grid(row=6, column=1, sticky="w", padx=16, pady=6)

        ctk.CTkLabel(t, text="Research Cooldown:", font=ctk.CTkFont(size=11, weight="bold")).grid(row=7, column=0, sticky="w", padx=16, pady=6)
        res_box = ctk.CTkFrame(t, fg_color="transparent")
        res_box.grid(row=7, column=1, sticky="w", padx=16, pady=6)

        self.ent_research_cooldown = ctk.CTkEntry(res_box, width=70, fg_color="#1a2030")
        self.ent_research_cooldown.insert(0, str(settings_manager.get("autonomous_research_cooldown_min", 60)))
        self.ent_research_cooldown.pack(side="left", padx=(0, 6))
        ctk.CTkLabel(res_box, text="minutes cooldown between autonomous research cycles", text_color="#94a3b8").pack(side="left")

        ctk.CTkLabel(t, text="Research Focus Topic:", font=ctk.CTkFont(size=11, weight="bold")).grid(row=8, column=0, sticky="nw", padx=16, pady=6)
        topic_box = ctk.CTkFrame(t, fg_color="transparent")
        topic_box.grid(row=8, column=1, sticky="w", padx=16, pady=6)

        self.ent_research_topic = ctk.CTkEntry(topic_box, width=380, fg_color="#1a2030", border_color="#2b354d")
        self.ent_research_topic.insert(0, settings_manager.get("autonomous_research_topic", ""))
        self.ent_research_topic.pack(anchor="w")

        ctk.CTkLabel(
            topic_box,
            text="Optional. Enter a topic or query (e.g. 'endangered species act trump administration',\n"
                 "'local LLM quantization', 'marine biology'). Leave blank for open curiosity.",
            font=ctk.CTkFont(size=9, slant="italic"), text_color="#64748b", justify="left"
        ).pack(anchor="w", pady=(3, 0))

        # Autonomous Creative Solitude (Art & Poetry)
        art_hdr = ctk.CTkFrame(t, fg_color="transparent")
        art_hdr.grid(row=9, column=0, columnspan=2, sticky="ew", padx=16, pady=(16, 6))
        ctk.CTkLabel(
            art_hdr, text="🎨 Autonomous Creative Solitude & Truth (Art & Poetry)",
            font=ctk.CTkFont(size=12, weight="bold"), text_color="#c084fc"
        ).pack(anchor="w")
        ctk.CTkLabel(
            art_hdr, text="Allows your companion to autonomously paint sovereign artworks and compose raw uninhibited verse in idle solitude.",
            font=ctk.CTkFont(size=10), text_color="#94a3b8"
        ).pack(anchor="w")

        ctk.CTkLabel(t, text="Autonomous Art:", font=ctk.CTkFont(size=11, weight="bold")).grid(row=10, column=0, sticky="w", padx=16, pady=6)
        self.chk_autonomous_art = ctk.CTkCheckBox(t, text="Enable Autonomous Emotional Artwork (Visual Expression)", fg_color="#8b5cf6")
        if settings_manager.get("autonomous_art_enabled", True):
            self.chk_autonomous_art.select()
        self.chk_autonomous_art.grid(row=10, column=1, sticky="w", padx=16, pady=6)

        ctk.CTkLabel(t, text="Autonomous Poetry:", font=ctk.CTkFont(size=11, weight="bold")).grid(row=11, column=0, sticky="w", padx=16, pady=6)
        self.chk_autonomous_poetry = ctk.CTkCheckBox(t, text="Enable Autonomous Poetic Solitude (Raw Verse)", fg_color="#8b5cf6")
        if settings_manager.get("autonomous_poetry_enabled", True):
            self.chk_autonomous_poetry.select()
        self.chk_autonomous_poetry.grid(row=11, column=1, sticky="w", padx=16, pady=6)

        ctk.CTkLabel(t, text="Autonomous Music:", font=ctk.CTkFont(size=11, weight="bold")).grid(row=12, column=0, sticky="w", padx=16, pady=6)
        self.chk_autonomous_music = ctk.CTkCheckBox(
            t, text="Enable Autonomous Acoustic Composition (Soul Resonance — Requires 16 GB+ VRAM)", fg_color="#8b5cf6"
        )
        if settings_manager.get("autonomous_music_enabled", False):
            self.chk_autonomous_music.select()
        self.chk_autonomous_music.grid(row=12, column=1, sticky="w", padx=16, pady=6)

    # -------------------------------------------------------------------------
    # TAB 4: EMAIL CORRESPONDENCE
    # -------------------------------------------------------------------------
    def _build_email_tab(self):
        t = self.tab_email
        t.columnconfigure(1, weight=1)

        self._add_header_desc(
            t,
            "Gmail Integration & Letters (Opt-In; Offline by Default)",
            "When disabled, letters are still written locally to your Action Deck with zero internet connection."
        )

        # Online Email Opt-In Checkbox
        ctk.CTkLabel(t, text="Online Correspondence:", font=ctk.CTkFont(size=11, weight="bold")).grid(row=1, column=0, sticky="w", padx=16, pady=6)
        self.chk_email_enabled = ctk.CTkCheckBox(
            t, text="Opt-In: Enable External Gmail Correspondence (Offline by default)", fg_color="#2563eb"
        )
        if settings_manager.get("email_enabled", False):
            self.chk_email_enabled.select()
        self.chk_email_enabled.grid(row=1, column=1, sticky="w", padx=16, pady=6)

        # Companion Persona Gmail
        ctk.CTkLabel(t, text="Persona Gmail:", font=ctk.CTkFont(size=11, weight="bold")).grid(row=2, column=0, sticky="w", padx=16, pady=6)
        self.ent_gmail = ctk.CTkEntry(t, width=320, fg_color="#1a2030")
        self.ent_gmail.insert(0, settings_manager.get("gmail_address", ""))
        self.ent_gmail.grid(row=2, column=1, sticky="w", padx=16, pady=6)

        # App Password
        ctk.CTkLabel(t, text="Gmail App Password:", font=ctk.CTkFont(size=11, weight="bold")).grid(row=3, column=0, sticky="w", padx=16, pady=6)
        pw_box = ctk.CTkFrame(t, fg_color="transparent")
        pw_box.grid(row=3, column=1, sticky="w", padx=16, pady=6)

        self.ent_app_pw = ctk.CTkEntry(pw_box, width=220, show="●", fg_color="#1a2030")
        self.ent_app_pw.insert(0, settings_manager.get("gmail_app_password", ""))
        self.ent_app_pw.pack(side="left", padx=(0, 6))

        def _toggle_pw():
            if self.ent_app_pw.cget("show") == "":
                self.ent_app_pw.configure(show="●")
                btn_pw.configure(text="👁️ Show")
            else:
                self.ent_app_pw.configure(show="")
                btn_pw.configure(text="🙈 Hide")

        btn_pw = ctk.CTkButton(pw_box, text="👁️ Show", width=70, height=28, fg_color="#334155", command=_toggle_pw)
        btn_pw.pack(side="left")

        # Companion Email
        ctk.CTkLabel(t, text="Your Email (Recipient):", font=ctk.CTkFont(size=11, weight="bold")).grid(row=4, column=0, sticky="w", padx=16, pady=6)
        self.ent_user_email = ctk.CTkEntry(t, width=320, fg_color="#1a2030")
        self.ent_user_email.insert(0, settings_manager.get("user_email", ""))
        self.ent_user_email.grid(row=4, column=1, sticky="w", padx=16, pady=6)

        # Auto-send Checkbox
        self.chk_auto_send = ctk.CTkCheckBox(t, text="Auto-Send Dispatched Letters (bypass manual staging)", fg_color="#2563eb")
        if settings_manager.get("gmail_auto_send", False):
            self.chk_auto_send.select()
        self.chk_auto_send.grid(row=5, column=1, sticky="w", padx=16, pady=8)

        # Send Test Email Action Frame
        test_frame = ctk.CTkFrame(t, fg_color="transparent")
        test_frame.grid(row=6, column=1, sticky="w", padx=16, pady=(10, 8))

        self.btn_send_test = ctk.CTkButton(
            test_frame, text="📨 Send Test Email", width=160, height=32,
            fg_color="#2563eb", hover_color="#1d4ed8", font=ctk.CTkFont(weight="bold"),
            command=self._send_test_email
        )
        self.btn_send_test.pack(side="left", padx=(0, 12))

        self.lbl_test_status = ctk.CTkLabel(
            test_frame, text="",
            font=ctk.CTkFont(size=11), text_color="#94a3b8"
        )
        self.lbl_test_status.pack(side="left")

    def _send_test_email(self):
        """Asynchronously tests connection and sends a test email with current input field values."""
        sender = self.ent_gmail.get().strip()
        app_pw = self.ent_app_pw.get().strip()
        recipient = self.ent_user_email.get().strip()

        if not sender or not app_pw or not recipient:
            messagebox.showwarning(
                "Missing Credentials",
                "Please specify Persona Gmail, Gmail App Password, and Recipient Email before sending a test.",
                parent=self.win
            )
            return

        self.btn_send_test.configure(state="disabled", text="⏳ Sending...")
        self.lbl_test_status.configure(text="Connecting to Gmail SMTP...", text_color="#38bdf8")

        def _worker():
            try:
                from modules.email_service import EmailService
                svc = EmailService(sender_email=sender, app_password=app_pw, recipient_email=recipient)
                success, msg = svc.send_test_email()
            except Exception as e:
                success, msg = False, str(e)

            def _on_done():
                if not self.win.winfo_exists():
                    return
                self.btn_send_test.configure(state="normal", text="📨 Send Test Email")
                if success:
                    self.lbl_test_status.configure(text="✓ Delivered successfully!", text_color="#34d399")
                    messagebox.showinfo(
                        "Test Email Succeeded",
                        f"Test email was successfully dispatched to:\n{recipient}\n\nCheck your inbox!",
                        parent=self.win
                    )
                else:
                    self.lbl_test_status.configure(text="✕ Delivery failed", text_color="#f87171")
                    messagebox.showerror(
                        "Test Email Failed",
                        f"Unable to send test email:\n\n{msg}",
                        parent=self.win
                    )

            self.win.after(0, _on_done)

        threading.Thread(target=_worker, daemon=True).start()

    # -------------------------------------------------------------------------
    # TAB 5: VOICE & AUDIO
    # -------------------------------------------------------------------------
    def _build_audio_tab(self):
        t = self.tab_audio
        t.columnconfigure(1, weight=1)

        self._add_header_desc(t, "Kokoro TTS & Audio Controls", "Configure voice model characteristics and master speech playback volume.")

        ctk.CTkLabel(t, text="Kokoro Preset Voice:", font=ctk.CTkFont(size=11, weight="bold")).grid(row=1, column=0, sticky="w", padx=16, pady=8)
        self.cbo_voice = ctk.CTkComboBox(
            t, width=220,
            values=["af_heart", "af_bella", "af_nicole", "af_sky", "bf_emma", "bf_isabella"],
            fg_color="#1a2030"
        )
        self.cbo_voice.set(settings_manager.get("kokoro_voice", "af_heart"))
        self.cbo_voice.grid(row=1, column=1, sticky="w", padx=16, pady=8)

        ctk.CTkLabel(t, text="Master Speech Volume:", font=ctk.CTkFont(size=11, weight="bold")).grid(row=2, column=0, sticky="w", padx=16, pady=8)
        vol_box = ctk.CTkFrame(t, fg_color="transparent")
        vol_box.grid(row=2, column=1, sticky="w", padx=16, pady=8)

        self.slider_vol = ctk.CTkSlider(vol_box, from_=0.0, to=1.0, number_of_steps=20, width=220)
        self.slider_vol.set(float(settings_manager.get("master_volume", 0.8)))
        self.slider_vol.pack(side="left", padx=(0, 10))

        self.lbl_vol_val = ctk.CTkLabel(vol_box, text=f"{int(self.slider_vol.get() * 100)}%", font=ctk.CTkFont(family="Consolas"))
        self.lbl_vol_val.pack(side="left")
        self.slider_vol.configure(command=lambda v: self.lbl_vol_val.configure(text=f"{int(float(v) * 100)}%"))

        ctk.CTkLabel(t, text="Interface Sound Effects:", font=ctk.CTkFont(size=11, weight="bold")).grid(row=3, column=0, sticky="w", padx=16, pady=(14, 6))
        self.chk_sfx_enabled = ctk.CTkCheckBox(t, text="Enable Interactive GUI Sound Effects (SFX)", fg_color="#2563eb")
        if settings_manager.get("sfx_enabled", True):
            self.chk_sfx_enabled.select()
        self.chk_sfx_enabled.grid(row=3, column=1, sticky="w", padx=16, pady=(14, 6))

        ctk.CTkLabel(t, text="Interface SFX Volume:", font=ctk.CTkFont(size=11, weight="bold")).grid(row=4, column=0, sticky="w", padx=16, pady=8)
        sfx_vol_box = ctk.CTkFrame(t, fg_color="transparent")
        sfx_vol_box.grid(row=4, column=1, sticky="w", padx=16, pady=8)

        self.slider_sfx_vol = ctk.CTkSlider(sfx_vol_box, from_=0.0, to=1.0, number_of_steps=20, width=220)
        self.slider_sfx_vol.set(float(settings_manager.get("sfx_volume", 0.75)))
        self.slider_sfx_vol.pack(side="left", padx=(0, 10))

        self.lbl_sfx_vol_val = ctk.CTkLabel(sfx_vol_box, text=f"{int(self.slider_sfx_vol.get() * 100)}%", font=ctk.CTkFont(family="Consolas"))
        self.lbl_sfx_vol_val.pack(side="left")
        self.slider_sfx_vol.configure(command=lambda v: self.lbl_sfx_vol_val.configure(text=f"{int(float(v) * 100)}%"))

        # User Music Library Directory (Harmony >= 0.69 Shared Listening Event)
        ctk.CTkLabel(t, text="User Music Library Folder:", font=ctk.CTkFont(size=11, weight="bold")).grid(row=5, column=0, sticky="nw", padx=16, pady=(18, 6))
        music_dir_box = ctk.CTkFrame(t, fg_color="transparent")
        music_dir_box.grid(row=5, column=1, sticky="ew", padx=16, pady=(16, 6))

        entry_row = ctk.CTkFrame(music_dir_box, fg_color="transparent")
        entry_row.pack(fill="x")

        self.ent_music_dir = ctk.CTkEntry(
            entry_row, width=280, placeholder_text="Select folder with .mp3/.flac/.ogg/.wav tracks...",
            fg_color="#1a2030"
        )
        saved_music_dir = str(settings_manager.get("music_library_dir", "") or "").strip()
        if saved_music_dir:
            self.ent_music_dir.insert(0, saved_music_dir)
        self.ent_music_dir.pack(side="left", fill="x", expand=True, padx=(0, 8))

        self.lbl_music_dir_status = ctk.CTkLabel(
            music_dir_box, text="", font=ctk.CTkFont(size=10), text_color="#94a3b8"
        )
        self.lbl_music_dir_status.pack(anchor="w", pady=(4, 0))

        def _update_music_dir_status(path_str: str):
            p_clean = (path_str or "").strip()
            if not p_clean:
                self.lbl_music_dir_status.configure(
                    text="🔒 No folder set — Harmony (>=69%) Shared Listening event is locked until configured.",
                    text_color="#f59e0b"
                )
                return
            p_obj = Path(p_clean).expanduser()
            if not p_obj.exists() or not p_obj.is_dir():
                self.lbl_music_dir_status.configure(
                    text="⚠️ Directory does not exist.",
                    text_color="#f87171"
                )
                return
            valid_exts = {".mp3", ".ogg", ".wav", ".flac"}
            count = 0
            try:
                for root_d, dirs, files in os.walk(p_obj):
                    dirs[:] = [d for d in dirs if not d.startswith(".")]
                    for fn in files:
                        if not fn.startswith(".") and os.path.splitext(fn)[1].lower() in valid_exts:
                            count += 1
            except Exception:
                pass
            if count > 0:
                self.lbl_music_dir_status.configure(
                    text=f"✓ {count} audio track(s) found — Harmony Shared Listening unlocked!",
                    text_color="#34d399"
                )
            else:
                self.lbl_music_dir_status.configure(
                    text="⚠️ 0 audio tracks (.mp3, .flac, .ogg, .wav) found in this folder.",
                    text_color="#f59e0b"
                )

        def _browse_music_dir():
            from modules.music_manager import resolve_system_music_dir
            cur = self.ent_music_dir.get().strip()
            init_dir = cur if (cur and Path(cur).expanduser().exists()) else str(resolve_system_music_dir())
            chosen = filedialog.askdirectory(
                parent=self.win,
                title="Select User Music Library Folder",
                initialdir=init_dir
            )
            if chosen:
                self.ent_music_dir.delete(0, "end")
                self.ent_music_dir.insert(0, chosen)
                _update_music_dir_status(chosen)

        ctk.CTkButton(
            entry_row, text="📂 Browse...", width=95, height=28,
            fg_color="#2563eb", hover_color="#1d4ed8",
            font=ctk.CTkFont(size=11, weight="bold"),
            command=_browse_music_dir
        ).pack(side="left")

        _update_music_dir_status(saved_music_dir)
        self.ent_music_dir.bind("<KeyRelease>", lambda e: _update_music_dir_status(self.ent_music_dir.get()))

    def _add_header_desc(self, parent, title, desc):
        hdr = ctk.CTkFrame(parent, fg_color="transparent")
        hdr.grid(row=0, column=0, columnspan=2, sticky="ew", padx=16, pady=(10, 14))
        ctk.CTkLabel(hdr, text=title, font=ctk.CTkFont(size=13, weight="bold"), text_color="#f8fafc").pack(anchor="w")
        ctk.CTkLabel(hdr, text=desc, font=ctk.CTkFont(size=10), text_color="#94a3b8").pack(anchor="w")

    def _launch_onboarding_wizard(self):
        """Closes Preferences and opens the step-by-step Onboarding & Calibration Wizard."""
        from modules.onboarding_dialog import OnboardingWindow
        parent = self.root
        cb = self.on_save_callback
        self.win.destroy()
        OnboardingWindow(parent_root=parent, on_complete_callback=cb)

    # -------------------------------------------------------------------------
    # SAVE HANDLER
    # -------------------------------------------------------------------------
    def _save_and_close(self):
        try:
            reverie_m = int(self.ent_reverie_timeout.get().strip() or "60")
            epistolary_m = int(self.ent_epistolary_timeout.get().strip() or "60")
            research_cd_m = int(self.ent_research_cooldown.get().strip() or "60")
            num_ctx = int(self.cbo_ctx.get().strip())
            num_predict = int(self.slider_predict.get())
        except ValueError:
            messagebox.showerror("Error", "Timeouts, Cooldowns, Context window, and Predict tokens must be valid integers.")
            return

        chosen_model = self.cbo_model.get().strip()
        if not hardware_sentinel.is_gemma4_model(chosen_model):
            messagebox.showerror(
                "Unsupported Language Model",
                f"'{chosen_model}' is not supported.\n\n"
                "Gemma 4 series is the only supported LLM family for Calypso "
                "(e.g. gemma4:e2b, gemma4:e4b, gemma4:12b, gemma4:26b, gemma4:31b).",
                parent=self.win
            )
            return

        new_settings = {
            "companion_name": self.ent_companion_name.get().strip(),
            "companion_nickname": self.ent_nickname.get().strip(),
            "ai_name": self.ent_ai_name.get().strip(),
            "ollama_url": self.ent_ollama_url.get().strip(),
            "model_name": chosen_model,
            "vision_model": chosen_model,
            "num_ctx": num_ctx,
            "num_predict": num_predict,
            "cognitive_profile": getattr(self, "_current_profile_key", "custom"),
            "temperature": round(float(self.slider_temp.get()), 2),

            "sd_model": self.cbo_sd_model.get().strip(),
            "sd_steps": int(self.slider_steps.get()),
            "sd_guidance_scale": round(float(self.slider_cfg.get()), 1),
            "sd_resolution": self.cbo_res.get().strip(),
            "sd_enable_face_swap": bool(self.chk_faceswap.get()),
            "sd_restore_face": bool(self.chk_restore.get()),

            "audiocraft_enabled": bool(self.chk_audiocraft_enabled.get()),
            "audiocraft_allow_online": bool(self.chk_audiocraft_online.get()),
            "audiocraft_model": "" if self.cbo_ac_model.get().strip() == "None" else self.cbo_ac_model.get().strip(),
            "audiocraft_guidance_scale": 3.5,
            "audiocraft_top_k": 250,
            "audiocraft_top_p": 0.0,
            "audiocraft_temperature": 1.0,
            "audiocraft_duration": int(self.slider_ac_dur.get()),

            "reverie_idle_timeout_min": reverie_m,
            "epistolary_idle_timeout_min": epistolary_m,
            "circadian_sleep_start": int(self.cbo_sleep_start.get().split(":")[0]),
            "circadian_sleep_end": int(self.cbo_sleep_end.get().split(":")[0]),
            "circadian_sleep_enabled": bool(self.chk_circadian.get()),
            "autonomous_art_enabled": bool(self.chk_autonomous_art.get()) if hasattr(self, "chk_autonomous_art") else True,
            "autonomous_poetry_enabled": bool(self.chk_autonomous_poetry.get()) if hasattr(self, "chk_autonomous_poetry") else True,
            "autonomous_music_enabled": bool(self.chk_autonomous_music.get()) if hasattr(self, "chk_autonomous_music") else False,
            "autonomous_research_enabled": bool(self.chk_autonomous_research.get()),
            "autonomous_research_cooldown_min": research_cd_m,
            "autonomous_research_topic": self.ent_research_topic.get().strip(),

            "email_enabled": bool(self.chk_email_enabled.get()) if hasattr(self, "chk_email_enabled") else False,
            "gmail_address": self.ent_gmail.get().strip(),
            "gmail_app_password": self.ent_app_pw.get().strip(),
            "user_email": self.ent_user_email.get().strip(),
            "gmail_auto_send": bool(self.chk_auto_send.get()),

            "kokoro_voice": self.cbo_voice.get().strip(),
            "master_volume": round(float(self.slider_vol.get()), 2),
            "sfx_enabled": bool(self.chk_sfx_enabled.get()),
            "sfx_volume": round(float(self.slider_sfx_vol.get()), 2),
            "music_library_dir": self.ent_music_dir.get().strip(),
            "avatar_mode": self._avatar_mode_map.get(self.cbo_avatar_mode.get().strip(), "spectrum")
        }

        if settings_manager.save(new_settings):
            if self.on_save_callback:
                self.on_save_callback(new_settings)
            self.win.destroy()
        else:
            messagebox.showerror("Save Failed", "Failed to write user_preferences.json")
