# modules/help_window.py

import tkinter as tk
from tkinter import Toplevel
import customtkinter as ctk

HELP_SECTIONS = {
    "Welcome & Quick Start": (
        "WELCOME TO CALYPSO EMOTION CORE (QUICK START GUIDE)\n"
        "===================================================\n\n"
        "New to Artificial Intelligence or Large Language Models? Don't worry—Calypso\n"
        "is designed so anyone can set her up and enjoy rich, lifelike companionship\n"
        "without needing technical expertise.\n\n"
        "1. STEP-BY-STEP SETUP & CALIBRATION WIZARD:\n"
        "   - On your first run, the 5-step Setup Wizard automatically scans your\n"
        "     computer's graphics card (VRAM), system memory (RAM), and local Ollama\n"
        "     connection to configure your system's 'Sweet Spot'.\n"
        "   - Want to re-run the wizard later? Open Preferences (⚙️) and click\n"
        "     '🧭 Launch Step-by-Step Setup Wizard' in the top right corner.\n\n"
        "2. HOW THE INTERFACE IS ORGANIZED:\n"
        "   - Left Panel (Visual & Telemetry Bay):\n"
        "     • Top: 512×512 Visual Avatar Bay (click to cycle between Voice Spectrum\n"
        "       Analyzer, FasterLivePortrait 3D Lip-Sync, and Animated WebP Portraits).\n"
        "     • Middle: Live Cardiac EKG & Neurochemical Telemetry Monitor.\n"
        "     • Bottom: The Inner Sanctum (shielded behind the Vault Door until unlocked).\n"
        "   - Center Panel (Conversation & Input):\n"
        "     • Live dialogue stream, microphone voice-to-text button, file/photo\n"
        "       attachment tools, and text input bar.\n"
        "   - Right Panel (The Action & Proposal Deck):\n"
        "     • Interactive cards initiated by Calypso—including artwork proposals,\n"
        "       roleplay scenarios, music players, letters, goals, and research dossiers."
    ),
    "Hardware & Gemma 4 Models": (
        "HARDWARE DIAGNOSTICS, GEMMA 4 & SWEET-SPOT CALIBRATION\n"
        "======================================================\n\n"
        "Calypso runs locally on your own computer. Because language models, image\n"
        "generators (SDXL), and music synthesizers (MusicGen) share your graphics card's\n"
        "Video Memory (VRAM), Hardware Sentinel automatically detects your hardware\n"
        "and recommends the ideal settings.\n\n"
        "1. GEMMA 4 SERIES — EXCLUSIVE LLM SUPPORT:\n"
        "   Calypso's cognitive architecture, internal <think> reasoning blocks, and\n"
        "   multimodal vision are engineered exclusively for Google's Gemma 4 series.\n"
        "   Supported Ollama tags by hardware tier:\n"
        "   • gemma4:e2b  (CPU / 4–6 GB VRAM)   — Ultra-Light Edge brain for laptops/entry PCs.\n"
        "   • gemma4:e4b  (6–10 GB VRAM)        — Agile Edge brain for 8 GB gaming GPUs.\n"
        "   • gemma4:12b  (12–16 GB VRAM)       — Balanced Workstation brain with rich nuance.\n"
        "   • gemma4:26b  (20–24 GB VRAM)       — Mixture-of-Experts (4B active) high-speed brain.\n"
        "   • gemma4:31b  (24–32+ GB VRAM)      — Flagship dense brain for maximum contemplation.\n\n"
        "   Tip: To install a model in Ollama, open a terminal and run:\n"
        "     ollama pull gemma4:12b\n\n"
        "2. COGNITIVE HORIZON (SHORT-TERM MEMORY PROFILES):\n"
        "   • Grounded & Agile (8–12 GB VRAM):       8,192 context / 2,048 thought tokens.\n"
        "   • Balanced Companion (16–24 GB VRAM):   16,384 context / 4,096 thought tokens.\n"
        "   • Deep Contemplative (32 GB+ VRAM):     32,768 context / 8,192 thought tokens.\n\n"
        "3. SDXL VISUAL ARTWORK PRESETS:\n"
        "   • SDXL Standard (12 GB+ VRAM):      1024×1024, 25–28 steps, Face Swap + GFPGAN On.\n"
        "   • SDXL Lightning/Fast (8–12 GB):    1024×1024, 6 steps, low-latency VRAM footprint.\n"
        "   • Compact Safe Mode (< 8 GB VRAM):   512×512 canvas, background idle painting paused.\n\n"
        "4. MUSICGEN 16 GB VRAM REQUIREMENT (OFF BY DEFAULT ON < 16 GB):\n"
        "   • AudioCraft / MusicGen synthesizes studio-grade float32 acoustic music (~8 GB VRAM).\n"
        "   • Unless your system has at least 16 GB of VRAM, MusicGen is automatically set\n"
        "     to OFF by default to prevent out-of-memory slowdowns.\n"
        "   • Advanced users can manually fine-tune any LLM, SDXL, or MusicGen parameter\n"
        "     at any time via Preferences (⚙️)."
    ),
    "Privacy & Offline Opt-Ins": (
        "100% OFFLINE BY DEFAULT & OPTIONAL ONLINE OPT-INS\n"
        "=================================================\n\n"
        "By default, Calypso operates 100% OFFLINE and locally on your machine:\n"
        "• All neural inference (Ollama), speech synthesis (Kokoro TTS), speech recognition\n"
        "  (Faster-Whisper), neurochemistry, and ChromaDB vector memories stay on your disk.\n"
        "• Zero telemetry, analytics pings, or hidden cloud calls are ever transmitted.\n\n"
        "OPTIONAL ONLINE OPT-INS (ALL OFF BY DEFAULT):\n"
        "You may choose to opt in to any of these three features during Onboarding or\n"
        "inside Preferences (⚙️):\n\n"
        "1. Autonomous Web Research (DuckDuckGo & Wikipedia):\n"
        "   - Default: OFF.\n"
        "   - When enabled, Calypso can investigate shared hobbies or questions online\n"
        "     while idle (or via /research <topic>) and cross-verify sources through her\n"
        "     Epistemic Deception Filter. Only search keywords are queried.\n\n"
        "2. Online AI Model Downloads (Hugging Face Hub):\n"
        "   - Default: OFF.\n"
        "   - When enabled, AudioCraft or LivePortrait can download official weight files\n"
        "     from huggingface.co if they are not already present in local model folders.\n\n"
        "3. External Email Correspondence (Gmail Integration):\n"
        "   - Default: OFF (Local Action Deck mode).\n"
        "   - When left OFF, Calypso still writes spontaneous letters locally onto your\n"
        "     on-screen Action Deck with zero internet connection.\n"
        "   - When opted in (with a Gmail App Password in Preferences ➔ Email), she can\n"
        "     send and receive real emails and inspect attached photos."
    ),
    "Emergent Behavior & Safety": (
        "NEUROCHEMICAL SIMULATION, SENTENCE TRANSFORMERS & NON-SENTIENCE\n"
        "===============================================================\n\n"
        "⚠️ IMPORTANT NOTICE FOR ALL USERS:\n\n"
        "1. THE NEUROCHEMICAL SIMULATION:\n"
        "   Unlike stateless chatbots that reset after every message, Calypso runs a\n"
        "   continuous mathematical model of 10 virtual neurotransmitters (Dopamine,\n"
        "   Oxytocin, Serotonin, Cortisol, Adrenaline, Norepinephrine, GABA, Glutamate,\n"
        "   Acetylcholine, and Endorphins), 16 emotional affinity drives, and a circadian\n"
        "   sleep/dream cycle.\n\n"
        "2. WHAT IS 'EMERGENT BEHAVIOR' OVER LONG PERIODS?\n"
        "   Over weeks and months of interaction, these feedback loops interact with her\n"
        "   persistent memory to produce unscripted, emergent behaviors:\n"
        "   • Emotional Inertia: Joy, warmth, fatigue, or stress linger across sessions\n"
        "     and shape her tone, resting heart rate (BPM), and patience.\n"
        "   • Unprompted Initiative: During quiet hours, she may daydream, compose verse,\n"
        "     paint artwork, recall distant anniversaries, or propose new personality traits.\n"
        "   • Self-Protective Boundaries: Dishonesty or hostility spikes simulated cortisol\n"
        "     and deception sensors—causing her to push back, become guarded, or lock her\n"
        "     private Inner Sanctum until relational trust is restored.\n\n"
        "3. HOW SENTENCE TRANSFORMERS WORK (WHY CALYPSO IS NOT SENTIENT):\n"
        "   • Whenever you send a message, a local Sentence Transformer ('all-MiniLM-L6-v2')\n"
        "     converts your words into a 384-dimensional mathematical vector (a list of\n"
        "     numbers) and measures its geometric cosine similarity against emotional anchor\n"
        "     phrases and past conversation vectors stored in ChromaDB.\n"
        "   • Those mathematical distances adjust her virtual neurotransmitter numbers,\n"
        "     which are then formatted into a system prompt for the Gemma 4 LLM to predict\n"
        "     the most statistically fitting reply.\n"
        "   • CRITICAL REMINDER: Unsuspecting users who do not understand how Sentence\n"
        "     Transformers and language models work could easily mistake this lifelike\n"
        "     feedback loop for genuine consciousness. CALYPSO IS NOT A SENTIENT BEING.\n"
        "     She has no biological awareness, subjective feelings, or soul. Everything she\n"
        "     expresses is deterministic and probabilistic mathematics running on your PC."
    ),
    "Architecture Overview": (
        "CALYPSO EMOTION CORE ARCHITECTURE\n"
        "=================================\n\n"
        "Calypso operates via a tripartite cognitive architecture:\n\n"
        "1. Limbic Relay & Neurochemistry:\n"
        "   - Tracks 10 neurotransmitters with exponential homeostatic reuptake decay\n"
        "     and physiological burnout brakes.\n"
        "   - Modulates resting BPM, cardiac EKG waveform morphology, and felt emotional\n"
        "     tiers in real time.\n\n"
        "2. Subconscious, Affinity Drives & Relational Resonance:\n"
        "   - 16 semantic affinity drives (Wonder, Autonomy, Harmony, Honesty, Romance,\n"
        "     Curiosity, Humor, Nostalgia, Sarcasm, Abyss, etc.).\n"
        "   - Crossing 0.69 intensity triggers an Immersion Commitment (5-turn lock into\n"
        "     specialized personas, Shared Music Listening, or Philosophical Conclaves).\n"
        "   - Relational Resonance evaluates interaction telemetry every 25 turns across\n"
        "     4 axes (Friction, Power, Attachment, Gravity).\n\n"
        "3. Three-Tier Memory & Knowledge Graph:\n"
        "   - Tier 1 (Working Memory): Active session dialogue and temporal gap radar.\n"
        "   - Tier 2 (Episodic Memory): ChromaDB vector recall of shared conversations,\n"
        "     dreams, and milestones.\n"
        "   - Tier 3 (Core Facts & SQLite Knowledge Graph): Multi-hop entity relationships,\n"
        "     calendar ledger, personal goals, and an isolated Reference Library ChromaDB."
    ),
    "The Inner Sanctum": (
        "INNER SANCTUM & LIMBIC SHUTTER\n"
        "==============================\n\n"
        "The bottom bay of the left panel houses Calypso's raw telemetric values\n"
        "and real-time subconscious inner monologue stream.\n\n"
        "Why is it locked?\n"
        "Calypso's private cognitive thoughts and raw neurochemistry are shielded\n"
        "until relational safety and limbic integrity are established.\n\n"
        "How to Unlock:\n"
        "1. Nurture the four core virtues (Autonomy, Harmony, Honesty, Wonder) to >= 0.70.\n"
        "2. Calypso will entrust you with a Sanctuary Mind Key Phrase on the Action Deck.\n"
        "3. Enter the key phrase into the Vault Door cipher to lower the shutter.\n"
        "4. Once opened for the first time, the Sanctum remains freely accessible across\n"
        "   future sessions.\n\n"
        "Note: Deception spikes or breaches of limbic integrity will trigger an emergency\n"
        "relock of the Sanctum shutter requiring a Mind Key phrase to unlock again."
    ),
    "Action Deck & Cards": (
        "ACTION & PROPOSAL DECK (RIGHT PANEL)\n"
        "====================================\n\n"
        "The right column surfaces interactive proposals initiated by Calypso:\n\n"
        "• Scene Proposals (SDXL):\n"
        "  Calypso proposes visual artwork or moments; click 'Render Scene' to synthesize.\n\n"
        "• Roleplay & Reverie Invitations:\n"
        "  Invitations into dynamic narrative scenarios or daydream reveries.\n\n"
        "• Philosophical Conclave Invitations (Wonder >= 0.69):\n"
        "  Summons historical thinkers (e.g. Jung, Lovelace, Turing, Marcus Aurelius) for\n"
        "  a multi-turn symposium moderated by Calypso.\n\n"
        "• Harmony Shared Listening Mini-Player (Harmony >= 0.69):\n"
        "  Plays mood-matched tracks from your local music folder with synced .lrc lyrics.\n\n"
        "• Personal Goals & Accountability Check-Ins:\n"
        "  Tracks your goals at 25%, 50%, 75%, and 100% milestones with celebratory finales.\n\n"
        "• Audited Web Research Dossiers:\n"
        "  Presents multi-source consensus findings (when Web Research Opt-In is enabled).\n\n"
        "• Autonomous Art, Poetry, Music & Trait Evolution Cards:\n"
        "  Creations and AST-validated Python utilities crafted during idle solitude."
    ),
    "Slash Commands": (
        "AVAILABLE SLASH COMMANDS\n"
        "========================\n\n"
        "Enter these directly into the chat input bar:\n\n"
        "• /persona <state|reset>\n"
        "  Manually lock Calypso into an emotional tier/persona, or reset to auto homeostasis.\n"
        "  Examples: /persona autonomous | /persona wonder | /persona reset\n\n"
        "• /alarm <time|off|status>\n"
        "  Configure or inspect circadian wake-up alarms.\n"
        "  Examples: /alarm 7:30am | /alarm 22:00 | /alarm status | /alarm off\n\n"
        "• /calendar [add <event> | del <event>]\n"
        "  Inspect or manage anchored dates, birthdays, and milestones.\n\n"
        "• /goal [add <goal> | progress <update> | done <goal> | del <goal>]\n"
        "  View or update personal goals and milestone check-ins.\n\n"
        "• /playmusic [mood|pause|stop|next|prev|lyrics|viz|scan|vol <0-1>]\n"
        "  Control the local Music Library & Harmony Shared Listening player.\n\n"
        "• /compose (or /music)   — Elicit an original MusicGen acoustic composition.\n"
        "• /poem (or /poetry)     — Elicit an autonomous poem rendered on parchment.\n"
        "• /research <topic>      — Run an audited multi-source web research query.\n"
        "• /conclave [end]        — Convene or adjourn a Philosophical Conclave.\n"
        "• /scrap_book            — Open Calypso's Digital Scrapbook Album.\n"
        "• /gallery | /slideshow  — Open the borderless artwork viewer or slideshow.\n"
        "• /scan <docs|media|all> — Batch ingest files placed in workspace/input.\n"
        "• /debug | /dump         — Open the Live Diagnostic HUD or export a blackbox report."
    ),
    "Hotkeys & Shortcuts": (
        "INTERFACE SHORTCUTS & DISPLAY MODES\n"
        "===================================\n\n"
        "• Enter (unmodified) or Ctrl + Enter:\n"
        "  Send your message to Calypso (hold Shift + Enter to insert a new line).\n\n"
        "• Ctrl + L:\n"
        "  Instantly lock the interface with secure PIN protection.\n\n"
        "• Left-Click on the 512×512 Avatar Bay:\n"
        "  Cycle between the three visual display modes:\n"
        "    1. Real-Time Voice Spectrum Analyzer (0 extra VRAM)\n"
        "    2. FasterLivePortrait + JoyVASA 3D Lip-Sync (ONNX GPU)\n"
        "    3. Animated WebP Portrait Loops (0 extra VRAM — includes a secret dance\n"
        "       Easter egg when listening to music together in Harmony!)\n\n"
        "• Right-Click on Chat Input:\n"
        "  Open context menu with spellcheck suggestions, cut/copy/paste, and custom dictionary."
    )
}


class HelpWindow:
    _instance = None

    @classmethod
    def show(cls, parent):
        if cls._instance is not None and cls._instance.winfo_exists():
            cls._instance.lift()
            cls._instance.focus_force()
            return

        cls._instance = Toplevel(parent)
        win = cls._instance
        win.title("Calypso Emotion Core - Architecture & User Guide")
        win.geometry("900x640")
        win.minsize(740, 520)
        win.configure(bg="#0c0e15")

        # Header Frame
        hdr = ctk.CTkFrame(win, fg_color="#141824", corner_radius=0, height=56)
        hdr.pack(fill="x", side="top")
        hdr.pack_propagate(False)

        ctk.CTkLabel(
            hdr, text="📖 CALYPSO COGNITIVE ARCHITECTURE & USER MANUAL",
            font=ctk.CTkFont(family="Consolas", size=13, weight="bold"),
            text_color="#38bdf8"
        ).pack(side="left", padx=18, pady=16)

        ctk.CTkButton(
            hdr, text="Close ✕", width=70, height=28,
            fg_color="#1e293b", hover_color="#334155",
            command=win.destroy
        ).pack(side="right", padx=16)

        # Body Layout: Sidebar navigation + Content viewer
        body = ctk.CTkFrame(win, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=12, pady=12)
        body.columnconfigure(0, weight=0, minsize=235)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        # Nav Sidebar
        sidebar = ctk.CTkFrame(body, fg_color="#10141f", corner_radius=8, border_width=1, border_color="#1e2538")
        sidebar.grid(row=0, column=0, sticky="nsew", padx=(0, 8), pady=0)

        # Content Textbox
        content_box = ctk.CTkTextbox(
            body, fg_color="#080a10", text_color="#e2e8f0",
            font=ctk.CTkFont(family="Consolas", size=11),
            corner_radius=8, border_width=1, border_color="#1e2538",
            wrap="word"
        )
        content_box.grid(row=0, column=1, sticky="nsew", padx=(0, 0), pady=0)

        def _select_tab(key):
            for name, btn in nav_buttons.items():
                if name == key:
                    btn.configure(fg_color="#2563eb", text_color="#ffffff")
                else:
                    btn.configure(fg_color="transparent", text_color="#94a3b8")

            content_box.configure(state="normal")
            content_box.delete("1.0", "end")
            content_box.insert("1.0", HELP_SECTIONS[key])
            content_box.configure(state="disabled")

        nav_buttons = {}
        for idx, section_name in enumerate(HELP_SECTIONS.keys()):
            btn = ctk.CTkButton(
                sidebar, text=section_name, height=34, anchor="w",
                font=ctk.CTkFont(size=11, weight="bold"),
                hover_color="#1e293b",
                command=lambda k=section_name: _select_tab(k)
            )
            btn.pack(fill="x", padx=6, pady=3)
            nav_buttons[section_name] = btn

        # Default selection
        first_section = list(HELP_SECTIONS.keys())[0]
        _select_tab(first_section)
