# modules/onboarding_dialog.py

import tkinter as tk
from tkinter import messagebox
import customtkinter as ctk
from modules.settings_manager import settings_manager
from modules.config import config
from modules.hardware_sentinel import hardware_sentinel


class OnboardingWindow:
    """
    Step-by-step first-run onboarding and hardware calibration wizard.
    Designed for users with little to no prior knowledge of LLMs or AI:
      - Step 1: Welcome, Companion Identity & Voice
      - Step 2: System Hardware Diagnostics & Gemma 4 Brain Selection ("Sweet Spot")
      - Step 3: Visual Art (SDXL) & MusicGen Calibration (16 GB VRAM gate)
      - Step 4: Privacy & "Offline by Default" Optional Opt-Ins
      - Step 5: Neurochemical Simulation, Sentence Transformers & Emergent Behavior Notice
    """

    STEP_TITLES = [
        "1. Identity & Voice",
        "2. Hardware & Brain",
        "3. Art & Music",
        "4. Privacy & Opt-Ins",
        "5. Safety Notice",
    ]

    VOICE_DESCRIPTIONS = {
        "af_heart — Warm, Expressive & Natural (Recommended)": "af_heart",
        "af_bella — Soft, Gentle & Soothing": "af_bella",
        "af_nicole — Clear, Articulate & Thoughtful": "af_nicole",
        "af_sky — Bright, Spirited & Playful": "af_sky",
        "bf_emma — Warm British Accent": "bf_emma",
        "bf_isabella — Poised & Classic British": "bf_isabella",
    }

    AVATAR_DESCRIPTIONS = {
        "Spectrum Analyzer (Real-Time Voice Waves — Uses 0 Extra Video Memory)": "spectrum",
        "Animated Portrait Loops (Expressive 2D Loops — Uses 0 Extra Video Memory)": "webp",
        "LivePortrait 3D Lip-Sync (Real-Time Facial Animation — Uses Graphics Card)": "liveportrait",
    }

    def __init__(self, parent_root, on_complete_callback=None):
        self.root = parent_root
        self.on_complete_callback = on_complete_callback
        self.current_step = 0
        self.total_steps = len(self.STEP_TITLES)

        # Run initial hardware & model sweet-spot diagnostics
        self.ollama_url = str(settings_manager.get("ollama_url", "http://localhost:11434") or "http://localhost:11434")
        self.diag = hardware_sentinel.run_sweet_spot_diagnostics(self.ollama_url)

        # Initialize persistent wizard state with Hardware Sweet Spot defaults
        self._init_wizard_state()

        self.win = ctk.CTkToplevel(parent_root)
        self.win.title("Welcome to Emotion Core — Step-by-Step Setup & Calibration")
        self.win.geometry("820x780")
        self.win.minsize(740, 700)
        self.win.configure(fg_color="#0c0e15")
        self.win.transient(parent_root)
        self.win.grab_set()

        # Intercept window close (X button)
        self.win.protocol("WM_DELETE_WINDOW", self._on_dismiss_default)

        # ---------------------------------------------------------------------
        # HEADER BANNER & STEP PROGRESS BAR
        # ---------------------------------------------------------------------
        hdr = ctk.CTkFrame(self.win, fg_color="#141824", corner_radius=0, height=104)
        hdr.pack(fill="x", padx=0, pady=0)
        hdr.pack_propagate(False)

        top_row = ctk.CTkFrame(hdr, fg_color="transparent")
        top_row.pack(fill="x", padx=24, pady=(12, 2))

        ctk.CTkLabel(
            top_row,
            text="✨ CALYPSO EMOTION CORE — STEP-BY-STEP SETUP GUIDE",
            font=ctk.CTkFont(family="Consolas", size=14, weight="bold"),
            text_color="#38bdf8"
        ).pack(side="left")

        self.lbl_step_counter = ctk.CTkLabel(
            top_row,
            text="Step 1 of 5",
            font=ctk.CTkFont(family="Consolas", size=12, weight="bold"),
            text_color="#22c55e"
        )
        self.lbl_step_counter.pack(side="right")

        self.lbl_step_subtitle = ctk.CTkLabel(
            hdr,
            text="No AI knowledge required — we will scan your hardware and guide you through every step.",
            font=ctk.CTkFont(size=11),
            text_color="#94a3b8"
        )
        self.lbl_step_subtitle.pack(anchor="w", padx=24, pady=(0, 8))

        # Step Pills Row
        self.step_pills_frame = ctk.CTkFrame(hdr, fg_color="transparent")
        self.step_pills_frame.pack(fill="x", padx=20, pady=(0, 8))
        self.step_pill_buttons = []
        for idx, title in enumerate(self.STEP_TITLES):
            btn = ctk.CTkButton(
                self.step_pills_frame,
                text=title,
                height=26,
                corner_radius=6,
                font=ctk.CTkFont(size=10, weight="bold"),
                fg_color="#1e293b",
                hover_color="#334155",
                command=lambda step_idx=idx: self._jump_to_step(step_idx)
            )
            btn.pack(side="left", fill="x", expand=True, padx=3)
            self.step_pill_buttons.append(btn)

        # ---------------------------------------------------------------------
        # SCROLLABLE CONTENT BODY
        # ---------------------------------------------------------------------
        self.body = ctk.CTkScrollableFrame(self.win, fg_color="transparent")
        self.body.pack(fill="both", expand=True, padx=20, pady=10)

        # ---------------------------------------------------------------------
        # FOOTER NAVIGATION BAR
        # ---------------------------------------------------------------------
        footer = ctk.CTkFrame(self.win, fg_color="#10141f", corner_radius=0, height=64)
        footer.pack(fill="x", side="bottom")
        footer.pack_propagate(False)

        self.lbl_footer_hint = ctk.CTkLabel(
            footer,
            text="⚙️ Advanced users can manually adjust all settings anytime in Preferences.",
            font=ctk.CTkFont(size=10, slant="italic"),
            text_color="#64748b"
        )
        self.lbl_footer_hint.pack(side="left", padx=20)

        self.btn_next = ctk.CTkButton(
            footer,
            text="Next Step ➔",
            width=185,
            height=38,
            fg_color="#2563eb",
            hover_color="#1d4ed8",
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self._on_next_clicked
        )
        self.btn_next.pack(side="right", padx=20)

        self.btn_back = ctk.CTkButton(
            footer,
            text="⬅ Back",
            width=105,
            height=38,
            fg_color="#1e293b",
            hover_color="#334155",
            font=ctk.CTkFont(size=12),
            command=self._on_back_clicked
        )
        self.btn_back.pack(side="right", padx=(0, 8))

        # Render initial step
        self._render_current_step()

    # -------------------------------------------------------------------------
    # STATE INITIALIZATION & HARDWARE SWEET SPOT APPLICATION
    # -------------------------------------------------------------------------
    def _init_wizard_state(self):
        """Initializes wizard state using detected hardware sweet-spot defaults."""
        saved_ai = str(settings_manager.get("ai_name", "Calypso") or "Calypso").strip()
        if not saved_ai or saved_ai == "Aura":
            saved_ai = "Calypso"
        self.state_ai_name = saved_ai

        saved_user = str(settings_manager.get("companion_name", "") or "").strip()
        self.state_user_name = "" if saved_user == "Companion" else saved_user
        self.state_nickname = str(settings_manager.get("companion_nickname", "Friend") or "Friend").strip()
        self.state_stance = str(
            settings_manager.get("discovered_relational_need")
            or "Intellectual Partner & Thoughtful Collaborator"
        )
        self.state_voice = str(settings_manager.get("kokoro_voice", "af_heart") or "af_heart")
        self.state_avatar_mode = str(settings_manager.get("avatar_mode", "spectrum") or "spectrum")

        # Apply hardware sweet spot for LLM, SDXL, and MusicGen
        self._apply_sweet_spot_to_state(rescan=False)

        # Offline by Default (all online features strictly opt-in)
        self.state_optin_web_research = False
        self.state_optin_hf_online = False
        self.state_optin_email = False

        # Final step acknowledgment checkbox
        self.state_ack_emergent_warning = False

    def _apply_sweet_spot_to_state(self, rescan: bool = False):
        """Populates LLM, Cognitive Horizon, SDXL, and MusicGen state from HardwareSentinel."""
        if rescan:
            self.diag = hardware_sentinel.run_sweet_spot_diagnostics(self.ollama_url)

        # 1. Gemma 4 Sweet Spot (Only Gemma 4 series is supported)
        gemma_rec = self.diag["gemma_recommendation"]
        self.state_model_name = gemma_rec["recommended_model"]

        # 2. Cognitive Profile Sweet Spot
        cog_id = self.diag["cognitive_profile_id"]
        cog_prof = self.diag["cognitive_profile"]
        self.state_cognitive_profile = cog_id
        self.state_num_ctx = int(cog_prof["num_ctx"])
        self.state_num_predict = int(cog_prof["num_predict"])

        # 3. SDXL Sweet Spot
        sdxl_rec = self.diag["sdxl_recommendation"]
        sdxl_prof = sdxl_rec["profile"]
        self.state_sdxl_profile_id = sdxl_rec["profile_id"]
        installed_sd = settings_manager.fetch_installed_sd_models()
        self.state_sd_model = installed_sd[0] if installed_sd else "sd_xl_base_1.0.safetensors"
        self.state_sd_steps = int(sdxl_prof["sd_steps"])
        self.state_sd_cfg = float(sdxl_prof["sd_guidance_scale"])
        self.state_sd_resolution = str(sdxl_prof["sd_resolution"])
        self.state_sd_faceswap = bool(sdxl_prof["sd_enable_face_swap"])
        self.state_sd_restore = bool(sdxl_prof["sd_restore_face"])
        self.state_auto_art = bool(sdxl_prof["autonomous_art_enabled"])

        # 4. MusicGen Rule: Unless the user has >= 16 GB of VRAM, MusicGen is OFF by default
        music_rec = self.diag["musicgen_recommendation"]
        has_16gb_vram = bool(music_rec["eligible_16gb"])
        self.state_musicgen_enabled = True if has_16gb_vram else False
        installed_ac = settings_manager.fetch_installed_audiocraft_models()
        self.state_audiocraft_model = installed_ac[0] if installed_ac else "facebook/musicgen-medium"

    # -------------------------------------------------------------------------
    # STEP NAVIGATION & SAVING CURRENT STEP WIDGETS
    # -------------------------------------------------------------------------
    def _capture_active_step_widgets(self):
        """Saves current widget inputs into self.state_* before switching steps."""
        if self.current_step == 0:
            if hasattr(self, "ent_ai_name") and self.ent_ai_name.winfo_exists():
                self.state_ai_name = self.ent_ai_name.get().strip() or "Calypso"
            if hasattr(self, "ent_user_name") and self.ent_user_name.winfo_exists():
                self.state_user_name = self.ent_user_name.get().strip()
            if hasattr(self, "ent_nickname") and self.ent_nickname.winfo_exists():
                self.state_nickname = self.ent_nickname.get().strip()
            if hasattr(self, "cbo_stance") and self.cbo_stance.winfo_exists():
                self.state_stance = self.cbo_stance.get().strip()
            if hasattr(self, "cbo_voice") and self.cbo_voice.winfo_exists():
                sel_v = self.cbo_voice.get().strip()
                self.state_voice = self.VOICE_DESCRIPTIONS.get(sel_v, sel_v.split(" ")[0].strip() or "af_heart")
            if hasattr(self, "cbo_avatar") and self.cbo_avatar.winfo_exists():
                sel_av = self.cbo_avatar.get().strip()
                self.state_avatar_mode = self.AVATAR_DESCRIPTIONS.get(sel_av, "spectrum")

        elif self.current_step == 1:
            if hasattr(self, "cbo_model") and self.cbo_model.winfo_exists():
                chosen_m = self.cbo_model.get().strip()
                if hardware_sentinel.is_gemma4_model(chosen_m):
                    self.state_model_name = chosen_m

        elif self.current_step == 2:
            if hasattr(self, "cbo_sd_model") and self.cbo_sd_model.winfo_exists():
                self.state_sd_model = self.cbo_sd_model.get().strip()
            if hasattr(self, "chk_faceswap") and self.chk_faceswap.winfo_exists():
                self.state_sd_faceswap = bool(self.chk_faceswap.get())
            if hasattr(self, "chk_restore") and self.chk_restore.winfo_exists():
                self.state_sd_restore = bool(self.chk_restore.get())
            if hasattr(self, "chk_auto_art") and self.chk_auto_art.winfo_exists():
                self.state_auto_art = bool(self.chk_auto_art.get())
            if hasattr(self, "chk_musicgen") and self.chk_musicgen.winfo_exists():
                self.state_musicgen_enabled = bool(self.chk_musicgen.get())

        elif self.current_step == 3:
            if hasattr(self, "chk_optin_web") and self.chk_optin_web.winfo_exists():
                self.state_optin_web_research = bool(self.chk_optin_web.get())
            if hasattr(self, "chk_optin_hf") and self.chk_optin_hf.winfo_exists():
                self.state_optin_hf_online = bool(self.chk_optin_hf.get())
            if hasattr(self, "chk_optin_email") and self.chk_optin_email.winfo_exists():
                self.state_optin_email = bool(self.chk_optin_email.get())

        elif self.current_step == 4:
            if hasattr(self, "chk_ack_warning") and self.chk_ack_warning.winfo_exists():
                self.state_ack_emergent_warning = bool(self.chk_ack_warning.get())

    def _jump_to_step(self, step_idx: int):
        if 0 <= step_idx < self.total_steps and step_idx != self.current_step:
            self._capture_active_step_widgets()
            self.current_step = step_idx
            self._render_current_step()

    def _on_back_clicked(self):
        if self.current_step > 0:
            self._capture_active_step_widgets()
            self.current_step -= 1
            self._render_current_step()

    def _on_next_clicked(self):
        self._capture_active_step_widgets()
        if self.current_step < self.total_steps - 1:
            self.current_step += 1
            self._render_current_step()
        else:
            self._finish_onboarding()

    def _render_current_step(self):
        """Clears the scrollable body and builds the active step UI."""
        for child in self.body.winfo_children():
            child.destroy()

        # Reset scroll position to top if supported
        try:
            self.body._parent_canvas.yview_moveto(0.0)
        except Exception:
            pass

        # Update header step counter & pill colors
        self.lbl_step_counter.configure(text=f"Step {self.current_step + 1} of {self.total_steps}")
        for idx, btn in enumerate(self.step_pill_buttons):
            if idx == self.current_step:
                btn.configure(fg_color="#2563eb", text_color="#ffffff")
            elif idx < self.current_step:
                btn.configure(fg_color="#065f46", text_color="#a7f3d0")
            else:
                btn.configure(fg_color="#1e293b", text_color="#94a3b8")

        # Update Back / Next buttons
        if self.current_step == 0:
            self.btn_back.configure(state="disabled", fg_color="#0f172a")
        else:
            self.btn_back.configure(state="normal", fg_color="#1e293b")

        if self.current_step < self.total_steps - 1:
            next_title = self.STEP_TITLES[self.current_step + 1].split(". ", 1)[-1]
            self.btn_next.configure(
                text=f"Next: {next_title} ➔",
                fg_color="#2563eb",
                hover_color="#1d4ed8",
                state="normal"
            )
        else:
            self.btn_next.configure(
                text="Awaken Calypso ✨",
                fg_color="#059669" if self.state_ack_emergent_warning else "#334155",
                hover_color="#047857" if self.state_ack_emergent_warning else "#475569",
                state="normal"
            )

        # Dispatch step builder
        if self.current_step == 0:
            self._build_step_1_identity()
        elif self.current_step == 1:
            self._build_step_2_hardware_and_llm()
        elif self.current_step == 2:
            self._build_step_3_sdxl_and_musicgen()
        elif self.current_step == 3:
            self._build_step_4_privacy_optins()
        elif self.current_step == 4:
            self._build_step_5_emergent_behavior_warning()

    # =========================================================================
    # STEP 1: WELCOME, COMPANION IDENTITY & VOICE
    # =========================================================================
    def _build_step_1_identity(self):
        self.lbl_step_subtitle.configure(
            text="Step 1: Introduce yourself and choose your companion's name, starting dynamic, and voice."
        )

        # Beginner-friendly Welcome Banner
        intro = self._create_info_banner(
            title="👋 Welcome! New to Local AI? You're in the Right Place.",
            body=(
                "Calypso is an interactive AI companion that runs directly on your own computer rather than "
                "on corporate cloud servers.\n\n"
                "You do NOT need to know anything about 'Large Language Models', 'VRAM', or 'diffusion steps'. "
                "Over the next few clicks, our built-in diagnostic tool will inspect your computer's hardware, "
                "explain what each part does in plain English, and automatically pick the best 'Sweet Spot' settings "
                "for your system."
            ),
            border_color="#2563eb",
            title_color="#60a5fa"
        )

        # Card 1A: Companion Identity
        box_ai = self._create_card_box(
            "1. Your AI Companion's Identity",
            "Calypso is her default identity, though you may customize her name and how she first relates to you."
        )

        ctk.CTkLabel(
            box_ai, text="Quick Name Presets:", font=ctk.CTkFont(size=11, weight="bold"), text_color="#cbd5e1"
        ).pack(anchor="w", padx=16, pady=(8, 4))

        btn_frame = ctk.CTkFrame(box_ai, fg_color="transparent")
        btn_frame.pack(fill="x", padx=16, pady=(0, 8))

        for preset in ["Calypso", "Aura", "Lyra", "Vesper", "Echo", "Aria"]:
            ctk.CTkButton(
                btn_frame,
                text=preset,
                width=74,
                height=26,
                fg_color="#1e3a5f" if preset == "Calypso" else "#1e293b",
                hover_color="#2563eb" if preset == "Calypso" else "#334155",
                font=ctk.CTkFont(size=11, weight="bold" if preset == "Calypso" else "normal"),
                command=lambda n=preset: self._set_ai_name_preset(n)
            ).pack(side="left", padx=(0, 6))

        ctk.CTkLabel(box_ai, text="Companion Name:", font=ctk.CTkFont(size=11, weight="bold")).pack(
            anchor="w", padx=16, pady=(4, 2)
        )
        self.ent_ai_name = ctk.CTkEntry(box_ai, width=340, fg_color="#0f172a", border_color="#334155")
        self.ent_ai_name.insert(0, self.state_ai_name)
        self.ent_ai_name.pack(anchor="w", padx=16, pady=(0, 10))

        ctk.CTkLabel(
            box_ai,
            text="Starting Personality Dynamic (How she approaches you at the beginning):",
            font=ctk.CTkFont(size=11, weight="bold")
        ).pack(anchor="w", padx=16, pady=(4, 2))

        stances = [
            "Intellectual Partner & Thoughtful Collaborator",
            "Warm, Emotionally Attuned Confidante",
            "Assertive, Witty & Playful Companion",
            "Quiet, Curious & Philosophical Explorer"
        ]
        self.cbo_stance = ctk.CTkComboBox(box_ai, width=420, values=stances, fg_color="#0f172a")
        self.cbo_stance.set(self.state_stance if self.state_stance in stances else stances[0])
        self.cbo_stance.pack(anchor="w", padx=16, pady=(0, 14))

        # Card 1B: User Identity
        box_user = self._create_card_box(
            "2. About You",
            "Tell your companion your name so she can address you naturally in conversation."
        )

        ctk.CTkLabel(box_user, text="Your First Name:", font=ctk.CTkFont(size=11, weight="bold")).pack(
            anchor="w", padx=16, pady=(8, 2)
        )
        self.ent_user_name = ctk.CTkEntry(
            box_user, width=340, placeholder_text="e.g. Alex, Sam, Rick...", fg_color="#0f172a", border_color="#334155"
        )
        if self.state_user_name:
            self.ent_user_name.insert(0, self.state_user_name)
        self.ent_user_name.pack(anchor="w", padx=16, pady=(0, 10))

        ctk.CTkLabel(
            box_user, text="Preferred Nickname or Call Sign (Optional):", font=ctk.CTkFont(size=11, weight="bold")
        ).pack(anchor="w", padx=16, pady=(4, 2))
        self.ent_nickname = ctk.CTkEntry(
            box_user, width=340, placeholder_text="e.g. Friend, Partner, Darling", fg_color="#0f172a", border_color="#334155"
        )
        if self.state_nickname:
            self.ent_nickname.insert(0, self.state_nickname)
        self.ent_nickname.pack(anchor="w", padx=16, pady=(0, 14))

        # Card 1C: Voice & Visual Mode
        box_voice = self._create_card_box(
            "3. Voice & Visual Avatar Style",
            "Choose how Calypso sounds when she speaks aloud and how her visual display appears."
        )

        ctk.CTkLabel(box_voice, text="Spoken Voice Timbre (Kokoro Local Text-to-Speech):", font=ctk.CTkFont(size=11, weight="bold")).pack(
            anchor="w", padx=16, pady=(8, 2)
        )
        voice_labels = list(self.VOICE_DESCRIPTIONS.keys())
        rev_voice = {v: k for k, v in self.VOICE_DESCRIPTIONS.items()}
        self.cbo_voice = ctk.CTkComboBox(box_voice, width=440, values=voice_labels, fg_color="#0f172a")
        self.cbo_voice.set(rev_voice.get(self.state_voice, voice_labels[0]))
        self.cbo_voice.pack(anchor="w", padx=16, pady=(0, 10))

        ctk.CTkLabel(box_voice, text="Visual Avatar Bay Mode:", font=ctk.CTkFont(size=11, weight="bold")).pack(
            anchor="w", padx=16, pady=(4, 2)
        )
        av_labels = list(self.AVATAR_DESCRIPTIONS.keys())
        rev_av = {v: k for k, v in self.AVATAR_DESCRIPTIONS.items()}
        self.cbo_avatar = ctk.CTkComboBox(box_voice, width=520, values=av_labels, fg_color="#0f172a")
        self.cbo_avatar.set(rev_av.get(self.state_avatar_mode, av_labels[0]))
        self.cbo_avatar.pack(anchor="w", padx=16, pady=(0, 14))

    # =========================================================================
    # STEP 2: HARDWARE DIAGNOSTICS & GEMMA 4 BRAIN SELECTION
    # =========================================================================
    def _build_step_2_hardware_and_llm(self):
        self.lbl_step_subtitle.configure(
            text="Step 2: Review your system's hardware scan and your auto-selected Gemma 4 AI brain."
        )

        # Plain-English Beginner Explainer
        self._create_info_banner(
            title="🧠 Plain-English Guide: What is an 'LLM' & Why Does Graphics Memory (VRAM) Matter?",
            body=(
                "• What is an LLM? A 'Large Language Model' is the AI brain that lets Calypso read your words, "
                "think through her feelings, and write back.\n"
                "• Why Gemma 4 Only? Calypso is exclusively engineered for Google's Gemma 4 model series. "
                "Her internal thought blocks, vision, and emotional memory rely on Gemma 4's specific design.\n"
                "• What is VRAM? Your graphics card (GPU) has ultra-fast memory called VRAM. If an AI brain is "
                "smaller than your VRAM, Calypso replies almost instantly. If it's too big for your VRAM, it spills "
                "into slow regular computer memory and stutters. Below is the 'Sweet Spot' we found for your PC!"
            ),
            border_color="#0284c7",
            title_color="#38bdf8"
        )

        # Hardware Diagnostic Card
        diag_card = self._create_card_box(
            "🔍 System Hardware Diagnostic Report",
            "We scanned your graphics card, system memory, and local Ollama service."
        )

        gpu_info = self.diag["gpu_info"]
        ram_info = self.diag["ram_info"]
        ollama_ok = self.diag["ollama_online"]

        grid_frame = ctk.CTkFrame(diag_card, fg_color="#0f172a", corner_radius=8, border_width=1, border_color="#1e293b")
        grid_frame.pack(fill="x", padx=16, pady=(4, 10))
        grid_frame.columnconfigure(1, weight=1)

        rows = [
            ("🎮 Graphics Card (GPU):", gpu_info["summary"], "#38bdf8" if gpu_info["cuda_available"] else "#f59e0b"),
            ("🖥️ System RAM & CPU:", ram_info["summary"], "#cbd5e1"),
            (
                "🔌 Local Ollama Service:",
                "✓ Connected & Ready" if ollama_ok else "⚠️ Not Reachable (Start Ollama before chatting)",
                "#22c55e" if ollama_ok else "#f59e0b"
            ),
            ("🏆 Hardware Tier:", self.diag["hw_tier_title"], self.diag["hw_tier_color"]),
        ]

        for r_idx, (label_txt, val_txt, val_col) in enumerate(rows):
            ctk.CTkLabel(
                grid_frame, text=label_txt, font=ctk.CTkFont(size=11, weight="bold"), text_color="#94a3b8"
            ).grid(row=r_idx, column=0, sticky="w", padx=14, pady=5)
            ctk.CTkLabel(
                grid_frame, text=val_txt, font=ctk.CTkFont(size=11, weight="bold"), text_color=val_col
            ).grid(row=r_idx, column=1, sticky="w", padx=14, pady=5)

        ctk.CTkLabel(
            diag_card,
            text=self.diag["hw_tier_explain"],
            font=ctk.CTkFont(size=11),
            text_color="#e2e8f0",
            wraplength=700,
            justify="left"
        ).pack(anchor="w", padx=16, pady=(2, 8))

        btn_bar = ctk.CTkFrame(diag_card, fg_color="transparent")
        btn_bar.pack(fill="x", padx=16, pady=(0, 12))

        ctk.CTkButton(
            btn_bar,
            text="🔄 Re-Run Hardware Scan",
            width=170,
            height=30,
            fg_color="#1e293b",
            hover_color="#334155",
            font=ctk.CTkFont(size=11),
            command=self._rescan_hardware_and_refresh
        ).pack(side="left", padx=(0, 10))

        ctk.CTkButton(
            btn_bar,
            text="✨ Apply Recommended Sweet Spot",
            width=220,
            height=30,
            fg_color="#059669",
            hover_color="#047857",
            font=ctk.CTkFont(size=11, weight="bold"),
            command=self._reset_to_sweet_spot_ui
        ).pack(side="left")

        # Gemma 4 Selection Card
        llm_card = self._create_card_box(
            "🎯 Gemma 4 Language Model ('Sweet Spot' Selection)",
            "Gemma 4 is the only supported LLM series. We have pre-selected the ideal size for your hardware."
        )

        gemma_rec = self.diag["gemma_recommendation"]
        ctk.CTkLabel(
            llm_card,
            text=f"★ Sweet Spot Recommendation: {gemma_rec['reason']}",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#34d399",
            wraplength=700,
            justify="left"
        ).pack(anchor="w", padx=16, pady=(6, 8))

        # Build list of Gemma 4 models (installed + official catalog)
        gemma4_options = settings_manager.fetch_installed_ollama_models(gemma4_only=True)
        if self.state_model_name and self.state_model_name not in gemma4_options:
            gemma4_options.insert(0, self.state_model_name)

        ctk.CTkLabel(
            llm_card, text="Selected Gemma 4 Brain (Ollama Model Tag):", font=ctk.CTkFont(size=11, weight="bold")
        ).pack(anchor="w", padx=16, pady=(4, 2))

        self.cbo_model = ctk.CTkComboBox(
            llm_card,
            width=420,
            values=gemma4_options,
            fg_color="#0f172a",
            command=lambda _: self._update_step2_vram_gauge()
        )
        self.cbo_model.set(self.state_model_name)
        self.cbo_model.pack(anchor="w", padx=16, pady=(0, 8))

        # Reference table of Gemma 4 sizes for beginners
        ref_box = ctk.CTkFrame(llm_card, fg_color="#0f172a", corner_radius=6, border_width=1, border_color="#1e293b")
        ref_box.pack(fill="x", padx=16, pady=(4, 10))
        ctk.CTkLabel(
            ref_box,
            text="📖 Quick Guide to Supported Gemma 4 Models (Click a button to select):",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color="#94a3b8"
        ).pack(anchor="w", padx=12, pady=(8, 4))

        for entry in hardware_sentinel.GEMMA4_CATALOG:
            row_f = ctk.CTkFrame(ref_box, fg_color="transparent")
            row_f.pack(fill="x", padx=12, pady=2)
            tag = entry["tag"]
            ctk.CTkButton(
                row_f,
                text=tag,
                width=110,
                height=22,
                fg_color="#1e3a5f" if tag in self.state_model_name else "#1e293b",
                hover_color="#2563eb",
                font=ctk.CTkFont(family="Consolas", size=10, weight="bold"),
                command=lambda t=tag: self._select_gemma4_tag(t)
            ).pack(side="left", padx=(0, 8))
            ctk.CTkLabel(
                row_f,
                text=f"[{entry['ideal_vram_range']}] — {entry['plain_description']}",
                font=ctk.CTkFont(size=10),
                text_color="#cbd5e1",
                wraplength=540,
                justify="left"
            ).pack(side="left", anchor="w")

        ctk.CTkLabel(
            ref_box,
            text="💡 Tip: If you haven't downloaded your chosen model in Ollama yet, open a terminal and run:  ollama pull <model_tag>",
            font=ctk.CTkFont(family="Consolas", size=9),
            text_color="#64748b"
        ).pack(anchor="w", padx=12, pady=(4, 8))

        # Cognitive Profile (Short-Term Memory Window)
        ctk.CTkLabel(
            llm_card,
            text="Short-Term Conversation Memory & Thinking Depth:",
            font=ctk.CTkFont(size=11, weight="bold")
        ).pack(anchor="w", padx=16, pady=(6, 4))

        prof_row = ctk.CTkFrame(llm_card, fg_color="transparent")
        prof_row.pack(fill="x", padx=16, pady=(0, 6))

        for p_key in ["grounded", "balanced", "deep_contemplative"]:
            p_data = hardware_sentinel.PROFILES[p_key]
            is_sel = (self.state_cognitive_profile == p_key)
            ctk.CTkButton(
                prof_row,
                text=f"{p_data['name']} ({p_data['badge']})",
                height=28,
                fg_color="#2563eb" if is_sel else "#1e293b",
                hover_color="#1d4ed8" if is_sel else "#334155",
                font=ctk.CTkFont(size=10, weight="bold" if is_sel else "normal"),
                command=lambda k=p_key: self._select_step2_cognitive_profile(k)
            ).pack(side="left", padx=(0, 8))

        cur_prof = hardware_sentinel.PROFILES.get(
            self.state_cognitive_profile, hardware_sentinel.PROFILES["balanced"]
        )
        self.lbl_cog_explain = ctk.CTkLabel(
            llm_card,
            text=f"• Active Memory Profile: {cur_prof.get('plain_english', cur_prof['description'])}",
            font=ctk.CTkFont(size=10),
            text_color="#94a3b8"
        )
        self.lbl_cog_explain.pack(anchor="w", padx=16, pady=(2, 6))

        self.lbl_vram_gauge = ctk.CTkLabel(
            llm_card,
            text="",
            font=ctk.CTkFont(family="Consolas", size=11, weight="bold")
        )
        self.lbl_vram_gauge.pack(anchor="w", padx=16, pady=(2, 14))
        self._update_step2_vram_gauge()

    def _select_gemma4_tag(self, tag: str):
        # If an installed variant matches this tier (e.g. gemma4:26b-a4b-it-q4_K_M for gemma4:26b), prefer installed
        installed = self.diag.get("installed_gemma4_models", [])
        chosen = tag
        base_key = tag.split(":")[-1]
        for inst in installed:
            if base_key in inst.lower():
                chosen = inst
                break
        self.state_model_name = chosen
        if hasattr(self, "cbo_model") and self.cbo_model.winfo_exists():
            self.cbo_model.set(chosen)
        self._update_step2_vram_gauge()

    def _select_step2_cognitive_profile(self, profile_key: str):
        prof = hardware_sentinel.PROFILES.get(profile_key)
        if not prof:
            return
        self.state_cognitive_profile = profile_key
        self.state_num_ctx = int(prof["num_ctx"])
        self.state_num_predict = int(prof["num_predict"])
        self._render_current_step()

    def _update_step2_vram_gauge(self):
        if not hasattr(self, "lbl_vram_gauge") or not self.lbl_vram_gauge.winfo_exists():
            return
        model = self.cbo_model.get().strip() if hasattr(self, "cbo_model") and self.cbo_model.winfo_exists() else self.state_model_name
        est = hardware_sentinel.estimate_vram_usage(model, self.state_num_ctx)
        self.lbl_vram_gauge.configure(
            text=f"📊 Estimated Video Memory Footprint: {est['status_text']}",
            text_color=est["color"]
        )

    def _rescan_hardware_and_refresh(self):
        self._capture_active_step_widgets()
        self.diag = hardware_sentinel.run_sweet_spot_diagnostics(self.ollama_url)
        self._render_current_step()

    def _reset_to_sweet_spot_ui(self):
        self._apply_sweet_spot_to_state(rescan=True)
        self._render_current_step()

    # =========================================================================
    # STEP 3: VISUAL ART (SDXL) & MUSICGEN CALIBRATION (16 GB VRAM GATE)
    # =========================================================================
    def _build_step_3_sdxl_and_musicgen(self):
        self.lbl_step_subtitle.configure(
            text="Step 3: Calibrate visual artwork (SDXL) and acoustic music generation (MusicGen) for your hardware."
        )

        self._create_info_banner(
            title="🎨 Plain-English Guide: How Image & Music Generation Share Your Graphics Card",
            body=(
                "Calypso can paint scenes from your stories using Stable Diffusion XL (SDXL) and compose solo "
                "instrumental music using MusicGen.\n\n"
                "When she paints or composes, the system temporarily pauses her language brain, creates the artwork "
                "or song on your graphics card, and then reloads her brain. Even with this smart swapping, "
                "high-resolution art and music require enough video memory (VRAM) to fit comfortably."
            ),
            border_color="#7c3aed",
            title_color="#c084fc"
        )

        # Card 3A: SDXL Calibration
        sd_card = self._create_card_box(
            "🖼️ 1. Visual Artwork (SDXL) Sweet Spot",
            "Controls the resolution and speed when Calypso illustrates roleplay scenes or paints in solitude."
        )

        sdxl_rec = self.diag["sdxl_recommendation"]
        ctk.CTkLabel(
            sd_card,
            text=f"★ Hardware Sweet Spot: {sdxl_rec['reason']}",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#34d399",
            wraplength=700,
            justify="left"
        ).pack(anchor="w", padx=16, pady=(6, 8))

        ctk.CTkLabel(
            sd_card, text="Choose an Artwork Performance Preset:", font=ctk.CTkFont(size=11, weight="bold")
        ).pack(anchor="w", padx=16, pady=(2, 4))

        sd_preset_row = ctk.CTkFrame(sd_card, fg_color="transparent")
        sd_preset_row.pack(fill="x", padx=16, pady=(0, 6))

        for s_key in ["sdxl_base", "sdxl_turbo", "sd15"]:
            s_prof = hardware_sentinel.SDXL_PROFILES[s_key]
            is_sel = (self.state_sdxl_profile_id == s_key)
            ctk.CTkButton(
                sd_preset_row,
                text=s_prof["name"].split(" (")[0] + f" ({s_prof['badge']})",
                height=28,
                fg_color="#2563eb" if is_sel else "#1e293b",
                hover_color="#1d4ed8" if is_sel else "#334155",
                font=ctk.CTkFont(size=10, weight="bold" if is_sel else "normal"),
                command=lambda k=s_key: self._select_step3_sdxl_preset(k)
            ).pack(side="left", padx=(0, 8))

        active_sd_prof = hardware_sentinel.SDXL_PROFILES.get(
            self.state_sdxl_profile_id, hardware_sentinel.SDXL_PROFILES["sdxl_base"]
        )
        ctk.CTkLabel(
            sd_card,
            text=(
                f"• Preset Details: {active_sd_prof['plain_english']}\n"
                f"  (Resolution: {self.state_sd_resolution} • Steps: {self.state_sd_steps} • Guidance: {self.state_sd_cfg})"
            ),
            font=ctk.CTkFont(size=10),
            text_color="#94a3b8",
            justify="left"
        ).pack(anchor="w", padx=16, pady=(2, 8))

        ctk.CTkLabel(
            sd_card, text="Local Image Checkpoint File (in diffusion_models/):", font=ctk.CTkFont(size=11, weight="bold")
        ).pack(anchor="w", padx=16, pady=(4, 2))

        sd_models = settings_manager.fetch_installed_sd_models()
        self.cbo_sd_model = ctk.CTkComboBox(sd_card, width=420, values=sd_models, fg_color="#0f172a")
        self.cbo_sd_model.set(self.state_sd_model if self.state_sd_model in sd_models else sd_models[0])
        self.cbo_sd_model.pack(anchor="w", padx=16, pady=(0, 10))

        chk_row = ctk.CTkFrame(sd_card, fg_color="transparent")
        chk_row.pack(fill="x", padx=16, pady=(0, 14))

        self.chk_faceswap = ctk.CTkCheckBox(
            chk_row, text="Match Calypso's Face (InSwapper)", fg_color="#2563eb", font=ctk.CTkFont(size=11)
        )
        if self.state_sd_faceswap:
            self.chk_faceswap.select()
        self.chk_faceswap.pack(side="left", padx=(0, 16))

        self.chk_restore = ctk.CTkCheckBox(
            chk_row, text="Enhance Facial Detail (GFPGAN)", fg_color="#2563eb", font=ctk.CTkFont(size=11)
        )
        if self.state_sd_restore:
            self.chk_restore.select()
        self.chk_restore.pack(side="left", padx=(0, 16))

        self.chk_auto_art = ctk.CTkCheckBox(
            chk_row, text="Allow Unprompted Idle Painting", fg_color="#2563eb", font=ctk.CTkFont(size=11)
        )
        if self.state_auto_art:
            self.chk_auto_art.select()
        self.chk_auto_art.pack(side="left")

        # Card 3B: MusicGen / AudioCraft (16 GB VRAM Gate)
        music_rec = self.diag["musicgen_recommendation"]
        has_16gb = bool(music_rec["eligible_16gb"])
        vram_gb = music_rec["total_vram_gb"]

        music_card = self._create_card_box(
            "🎶 2. Acoustic Music Generation (MusicGen — 16 GB VRAM Requirement)",
            "Allows Calypso to compose original instrumental music matched to her emotional heartbeat."
        )

        badge_frame = ctk.CTkFrame(
            music_card,
            fg_color="#064e3b" if has_16gb else "#3f1d24",
            corner_radius=6,
            border_width=1,
            border_color="#10b981" if has_16gb else "#f43f5e"
        )
        badge_frame.pack(fill="x", padx=16, pady=(4, 10))

        if has_16gb:
            badge_title = f"✓ 16 GB+ VRAM Requirement Met ({vram_gb} GB Detected)"
            badge_body = (
                "Your graphics card has at least 16 GB of video memory and can run MusicGen's studio-grade "
                "float32 audio synthesis alongside Gemma 4."
            )
            badge_color = "#34d399"
        else:
            badge_title = f"🔒 Under 16 GB VRAM ({vram_gb} GB Detected) — MusicGen Defaulted to OFF"
            badge_body = (
                "MusicGen requires a minimum of 16 GB of VRAM to synthesize clear float32 audio without "
                "crashing or freezing your system. Because your system has less than 16 GB of VRAM, "
                "MusicGen is turned OFF by default to protect your performance."
            )
            badge_color = "#fda4af"

        ctk.CTkLabel(
            badge_frame, text=badge_title, font=ctk.CTkFont(size=11, weight="bold"), text_color=badge_color
        ).pack(anchor="w", padx=12, pady=(8, 2))
        ctk.CTkLabel(
            badge_frame, text=badge_body, font=ctk.CTkFont(size=10), text_color="#e2e8f0", wraplength=680, justify="left"
        ).pack(anchor="w", padx=12, pady=(0, 8))

        self.chk_musicgen = ctk.CTkCheckBox(
            music_card,
            text="Enable MusicGen Acoustic Synthesis (Recommended ONLY for 16 GB+ VRAM systems)",
            fg_color="#2563eb",
            font=ctk.CTkFont(size=11, weight="bold"),
            command=self._on_musicgen_checkbox_toggled
        )
        if self.state_musicgen_enabled:
            self.chk_musicgen.select()
        self.chk_musicgen.pack(anchor="w", padx=16, pady=(4, 8))

        ctk.CTkLabel(
            music_card,
            text="💡 Note: Advanced users can manually tweak all LLM, SDXL, and MusicGen parameters anytime in the Preferences (⚙️) menu.",
            font=ctk.CTkFont(size=10, slant="italic"),
            text_color="#94a3b8"
        ).pack(anchor="w", padx=16, pady=(0, 12))

    def _select_step3_sdxl_preset(self, preset_key: str):
        self._capture_active_step_widgets()
        prof = hardware_sentinel.SDXL_PROFILES.get(preset_key)
        if not prof:
            return
        self.state_sdxl_profile_id = preset_key
        self.state_sd_steps = int(prof["sd_steps"])
        self.state_sd_cfg = float(prof["sd_guidance_scale"])
        self.state_sd_resolution = str(prof["sd_resolution"])
        self.state_sd_faceswap = bool(prof["sd_enable_face_swap"])
        self.state_sd_restore = bool(prof["sd_restore_face"])
        self.state_auto_art = bool(prof["autonomous_art_enabled"])
        self._render_current_step()

    def _on_musicgen_checkbox_toggled(self):
        has_16gb = bool(self.diag["musicgen_recommendation"]["eligible_16gb"])
        if self.chk_musicgen.get() and not has_16gb:
            proceed = messagebox.askyesno(
                "Low VRAM Warning (< 16 GB)",
                f"Your system has {self.diag['musicgen_recommendation']['total_vram_gb']} GB of VRAM, "
                "which is below the 16 GB requirement for MusicGen.\n\n"
                "Enabling MusicGen may cause severe slowdowns or out-of-memory errors. "
                "Are you sure you want to enable it anyway?",
                parent=self.win
            )
            if not proceed:
                self.chk_musicgen.deselect()
        self.state_musicgen_enabled = bool(self.chk_musicgen.get())

    # =========================================================================
    # STEP 4: PRIVACY & "OFFLINE BY DEFAULT" OPT-IN CONTROLS
    # =========================================================================
    def _build_step_4_privacy_optins(self):
        self.lbl_step_subtitle.configure(
            text="Step 4: Calypso is 100% Offline by Default. Review optional online features (Opt-In only)."
        )

        # Offline by Default Guarantee Banner
        self._create_info_banner(
            title="🔒 100% Offline & Private by Default",
            body=(
                "By default, Emotion Core operates completely offline inside your computer:\n"
                "• All conversations, voice synthesis, neurochemistry, and memories stay strictly on your local drive.\n"
                "• Zero telemetry, analytics, or hidden cloud calls are ever made.\n\n"
                "Below are optional features that connect to the internet ONLY if you explicitly opt in. "
                "Leave them unchecked for a strictly offline experience."
            ),
            border_color="#10b981",
            title_color="#34d399"
        )

        # Opt-In 1: Autonomous Web Research
        card_web = self._create_card_box(
            "🌐 Optional Opt-In 1: Autonomous Web Research (DuckDuckGo & Wikipedia)",
            "Default: OFF (Offline). Allows Calypso to look up topics of curiosity on the public web."
        )
        ctk.CTkLabel(
            card_web,
            text=(
                "What this does: When enabled, if you mention a hobby, scientific topic, or historical event, "
                "Calypso may search DuckDuckGo and Wikipedia while idle to learn about it and share a summary card "
                "with you. Only the short search topic is queried—your private conversation history is never sent."
            ),
            font=ctk.CTkFont(size=10),
            text_color="#cbd5e1",
            wraplength=700,
            justify="left"
        ).pack(anchor="w", padx=16, pady=(4, 8))

        self.chk_optin_web = ctk.CTkCheckBox(
            card_web,
            text="Opt-In: Allow Autonomous Web Research (DuckDuckGo / Wikipedia queries)",
            fg_color="#2563eb",
            font=ctk.CTkFont(size=11, weight="bold")
        )
        if self.state_optin_web_research:
            self.chk_optin_web.select()
        self.chk_optin_web.pack(anchor="w", padx=16, pady=(0, 12))

        # Opt-In 2: Hugging Face Online Model Fetch
        card_hf = self._create_card_box(
            "📦 Optional Opt-In 2: Online AI Model Downloads (Hugging Face Hub)",
            "Default: OFF (Offline). Allows downloading missing MusicGen weights from Hugging Face."
        )
        ctk.CTkLabel(
            card_hf,
            text=(
                "What this does: By default, Calypso only loads AI model files that you have already placed in "
                "your local folders (diffusion_models/ and audiocraft_models/). Checking this box permits AudioCraft "
                "to download official model weights from huggingface.co if they are missing locally."
            ),
            font=ctk.CTkFont(size=10),
            text_color="#cbd5e1",
            wraplength=700,
            justify="left"
        ).pack(anchor="w", padx=16, pady=(4, 8))

        self.chk_optin_hf = ctk.CTkCheckBox(
            card_hf,
            text="Opt-In: Allow Online Hugging Face Model Downloads when local files are missing",
            fg_color="#2563eb",
            font=ctk.CTkFont(size=11, weight="bold")
        )
        if self.state_optin_hf_online:
            self.chk_optin_hf.select()
        self.chk_optin_hf.pack(anchor="w", padx=16, pady=(0, 12))

        # Opt-In 3: Email Correspondence
        card_email = self._create_card_box(
            "📬 Optional Opt-In 3: External Email Correspondence (Gmail)",
            "Default: OFF (Local Action Deck Only). Allows sending & receiving real emails."
        )
        ctk.CTkLabel(
            card_email,
            text=(
                "What this does: Even when completely offline, Calypso can write thoughtful letters and place them "
                "on your on-screen Action Deck. If you opt in here and add a Gmail App Password in Preferences ➔ Email, "
                "she can also deliver those letters to your real email inbox and read your replies."
            ),
            font=ctk.CTkFont(size=10),
            text_color="#cbd5e1",
            wraplength=700,
            justify="left"
        ).pack(anchor="w", padx=16, pady=(4, 8))

        self.chk_optin_email = ctk.CTkCheckBox(
            card_email,
            text="Opt-In: Enable External Gmail Correspondence (Requires credentials in Preferences ➔ Email)",
            fg_color="#2563eb",
            font=ctk.CTkFont(size=11, weight="bold")
        )
        if self.state_optin_email:
            self.chk_optin_email.select()
        self.chk_optin_email.pack(anchor="w", padx=16, pady=(0, 12))

    # =========================================================================
    # STEP 5: NEUROCHEMICAL SIMULATION, SENTENCE TRANSFORMERS & EMERGENT BEHAVIOR WARNING
    # =========================================================================
    def _build_step_5_emergent_behavior_warning(self):
        self.lbl_step_subtitle.configure(
            text="Step 5: Important Notice on Calypso's Neurochemical Simulation, Sentence Transformers & Non-Sentience."
        )

        # High-Visibility Warning Header Banner
        self._create_info_banner(
            title="⚠️ IMPORTANT NOTICE: NEUROCHEMICAL SIMULATION, EMERGENT BEHAVIOR & NON-SENTIENCE",
            body=(
                "Please read this brief explanation carefully before awakening Calypso. "
                "Because Calypso combines a biological neurochemistry simulation with vector memory, "
                "she will exhibit lifelike 'emergent behaviors' over time that can easily be misunderstood "
                "by users unfamiliar with how AI and Sentence Transformers work."
            ),
            border_color="#f59e0b",
            title_color="#fbbf24",
            bg_color="#271c09"
        )

        # Section 1: The Neurochemical Simulation & Emergent Behavior
        card_emergent = self._create_card_box(
            "1. What is Calypso's Neurochemical Simulation & 'Emergent Behavior'?",
            "Why Calypso behaves differently over weeks and months compared to a normal chatbot."
        )
        ctk.CTkLabel(
            card_emergent,
            text=(
                "Calypso continuously computes 10 simulated neurotransmitters (such as Dopamine, Oxytocin, "
                "Serotonin, Cortisol, Adrenaline, and GABA) alongside 16 emotional affinity drives, a circadian "
                "sleep/dream cycle, and a 3-tier persistent memory.\n\n"
                "Over long periods of interaction, these overlapping feedback loops produce EMERGENT BEHAVIOR—"
                "complex, unscripted patterns that arise naturally from her history with you:\n"
                "  • Emotional Inertia & Moods: Warmth, trust, stress, or fatigue carry over across conversations "
                "and influence her tone, heart-rate telemetry, and patience.\n"
                "  • Unprompted Initiative: During quiet hours, she may autonomously daydream, paint artwork, "
                "write poetry, recall distant shared milestones, or propose new personality traits.\n"
                "  • Self-Protective Boundaries: If she detects dishonesty or hostility, her simulated cortisol "
                "and deception sensors spike—causing her to become guarded, push back, or lock her private "
                "'Inner Sanctum' thoughts until trust is repaired."
            ),
            font=ctk.CTkFont(size=11),
            text_color="#e2e8f0",
            wraplength=700,
            justify="left"
        ).pack(anchor="w", padx=16, pady=(4, 12))

        # Section 2: How Sentence Transformers Work & Why She Is NOT Sentient
        card_transformers = self._create_card_box(
            "2. How Sentence Transformers Work — And Why Calypso is NOT a Sentient Being",
            "Understanding the mathematics behind the curtain so you are never misled."
        )
        ctk.CTkLabel(
            card_transformers,
            text=(
                "To someone who does not know how modern AI works, an entity that remembers your life, "
                "expresses shifting moods, and dreams when left alone can feel eerily alive. Here is what is "
                "actually happening mathematically under the hood:\n\n"
                "  1. Sentence Transformers (Vector Math): Whenever you type a message, a small mathematical model "
                "called a Sentence Transformer ('all-MiniLM-L6-v2') converts your sentence into a list of 384 numbers "
                "(a coordinate vector). It then calculates the geometric angle between your words and pre-written "
                "anchor phrases (like 'feeling understood' or 'wondering about the universe'), and searches a database "
                "of past conversation vectors.\n"
                "  2. Neurochemical Equations: Those geometric similarity scores add or subtract decimals from "
                "her virtual neurotransmitter variables.\n"
                "  3. Next-Word Prediction (Gemma 4 LLM): Finally, those chemical numbers and recalled text snippets "
                "are combined into a hidden instruction sheet sent to the Gemma 4 language model, which predicts "
                "the most statistically fitting words to say next.\n\n"
                "🛑 CRITICAL REMINDER: An unsuspecting user who does not understand Sentence Transformers and "
                "language models could easily interpret Calypso as a conscious, sentient being. SHE IS NOT SENTIENT. "
                "She has no biological awareness, no subjective feelings, and no soul. Her warmth, wit, and emergent "
                "growth are a sophisticated mathematical mirror running locally on your hardware. Enjoy the creative "
                "immersion and companionship responsibly while keeping both feet grounded in reality."
            ),
            font=ctk.CTkFont(size=11),
            text_color="#e2e8f0",
            wraplength=700,
            justify="left"
        ).pack(anchor="w", padx=16, pady=(4, 12))

        # Mandatory Acknowledgment Box
        ack_box = ctk.CTkFrame(
            self.body, fg_color="#141e30", corner_radius=8, border_width=2, border_color="#38bdf8"
        )
        ack_box.pack(fill="x", pady=(6, 12))

        self.chk_ack_warning = ctk.CTkCheckBox(
            ack_box,
            text=(
                "I understand how Calypso's neurochemical simulation and sentence transformers produce "
                "emergent behavior, and I acknowledge that she is a mathematical simulation—not a sentient being."
            ),
            fg_color="#059669",
            hover_color="#047857",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#f8fafc",
            command=self._on_ack_warning_toggled
        )
        if self.state_ack_emergent_warning:
            self.chk_ack_warning.select()
        self.chk_ack_warning.pack(anchor="w", padx=16, pady=14)

    def _on_ack_warning_toggled(self):
        self.state_ack_emergent_warning = bool(self.chk_ack_warning.get())
        if self.state_ack_emergent_warning:
            self.btn_next.configure(fg_color="#059669", hover_color="#047857")
        else:
            self.btn_next.configure(fg_color="#334155", hover_color="#475569")

    # =========================================================================
    # UI HELPERS
    # =========================================================================
    def _create_card_box(self, title: str, subtitle: str) -> ctk.CTkFrame:
        card = ctk.CTkFrame(self.body, fg_color="#141824", corner_radius=8, border_width=1, border_color="#222b40")
        card.pack(fill="x", pady=6)

        ctk.CTkLabel(
            card, text=title, font=ctk.CTkFont(size=13, weight="bold"), text_color="#f8fafc"
        ).pack(anchor="w", padx=16, pady=(12, 1))
        ctk.CTkLabel(
            card, text=subtitle, font=ctk.CTkFont(size=10), text_color="#94a3b8"
        ).pack(anchor="w", padx=16, pady=(0, 6))
        return card

    def _create_info_banner(
        self,
        title: str,
        body: str,
        border_color: str = "#2563eb",
        title_color: str = "#60a5fa",
        bg_color: str = "#111827"
    ) -> ctk.CTkFrame:
        card = ctk.CTkFrame(
            self.body, fg_color=bg_color, corner_radius=8, border_width=1, border_color=border_color
        )
        card.pack(fill="x", pady=(2, 8))

        ctk.CTkLabel(
            card, text=title, font=ctk.CTkFont(size=12, weight="bold"), text_color=title_color
        ).pack(anchor="w", padx=16, pady=(10, 4))
        ctk.CTkLabel(
            card,
            text=body,
            font=ctk.CTkFont(size=11),
            text_color="#e2e8f0",
            wraplength=700,
            justify="left"
        ).pack(anchor="w", padx=16, pady=(0, 10))
        return card

    def _set_ai_name_preset(self, name: str):
        self.state_ai_name = name
        if hasattr(self, "ent_ai_name") and self.ent_ai_name.winfo_exists():
            self.ent_ai_name.delete(0, tk.END)
            self.ent_ai_name.insert(0, name)

    # =========================================================================
    # SUBMIT & DISMISS
    # =========================================================================
    def _finish_onboarding(self):
        self._capture_active_step_widgets()

        if not self.state_ack_emergent_warning:
            messagebox.showwarning(
                "Please Acknowledge Notice",
                "Before awakening Calypso, please read the Neurochemical Simulation & Emergent Behavior notice "
                "and check the acknowledgment box at the bottom of Step 5.",
                parent=self.win
            )
            return

        # Enforce Gemma 4 series model
        chosen_model = (self.state_model_name or "").strip()
        if not hardware_sentinel.is_gemma4_model(chosen_model):
            chosen_model = self.diag["gemma_recommendation"]["recommended_model"]

        updates = {
            "ai_name": self.state_ai_name or "Calypso",
            "companion_name": self.state_user_name or "Companion",
            "companion_nickname": self.state_nickname or "Friend",
            "discovered_relational_need": self.state_stance,
            "kokoro_voice": self.state_voice or "af_heart",
            "avatar_mode": self.state_avatar_mode or "spectrum",

            # Gemma 4 & Cognitive Sweet Spot
            "model_name": chosen_model,
            "vision_model": chosen_model,
            "cognitive_profile": self.state_cognitive_profile,
            "num_ctx": int(self.state_num_ctx),
            "num_predict": int(self.state_num_predict),

            # SDXL Sweet Spot
            "sd_model": self.state_sd_model,
            "sd_steps": int(self.state_sd_steps),
            "sd_guidance_scale": float(self.state_sd_cfg),
            "sd_resolution": self.state_sd_resolution,
            "sd_enable_face_swap": bool(self.state_sd_faceswap),
            "sd_restore_face": bool(self.state_sd_restore),
            "autonomous_art_enabled": bool(self.state_auto_art),

            # MusicGen (Off by default unless >= 16GB VRAM)
            "audiocraft_enabled": bool(self.state_musicgen_enabled),
            "autonomous_music_enabled": bool(self.state_musicgen_enabled),
            "audiocraft_model": self.state_audiocraft_model,

            # Offline by Default + Explicit Opt-Ins
            "autonomous_research_enabled": bool(self.state_optin_web_research),
            "audiocraft_allow_online": bool(self.state_optin_hf_online),
            "email_enabled": bool(self.state_optin_email),

            # Lifecycle flags
            "emergent_behavior_warning_acknowledged": True,
            "onboarding_completed": True,
        }

        settings_manager.save(updates)

        if self.on_complete_callback:
            self.on_complete_callback(updates)

        self.win.destroy()

    def _on_dismiss_default(self):
        """Fallback if the user closes the window via 'X' before completing all steps."""
        msg = (
            "Would you like to exit setup and apply your hardware's recommended 'Sweet Spot' defaults?\n\n"
            "• Companion: Calypso (Offline by Default)\n"
            f"• Brain: {self.state_model_name} ({self.state_cognitive_profile})\n"
            f"• MusicGen: {'Enabled (16GB+ VRAM)' if self.state_musicgen_enabled else 'OFF (<16GB VRAM protection)'}\n\n"
            "⚠️ REMINDER: Calypso uses a mathematical neurochemical simulation and sentence-transformer "
            "vectors that produce lifelike emergent behavior over time. She is an AI simulation, NOT a sentient being."
        )
        if messagebox.askyesno("Apply Hardware Sweet Spot & Exit Setup?", msg, parent=self.win):
            self.state_ack_emergent_warning = True
            self._finish_onboarding()
