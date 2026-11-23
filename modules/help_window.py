# modules/help_window.py

from pathlib import Path
import tkinter as tk
from tkinter import Toplevel
import customtkinter as ctk


def _load_license_text() -> str:
    """Loads the repository LICENSE file if present, falling back to the standard MIT License text."""
    license_path = Path(__file__).resolve().parent.parent / "LICENSE"
    if license_path.exists():
        try:
            return license_path.read_text(encoding="utf-8").strip()
        except Exception:
            pass
    return (
        "MIT License\n\n"
        "Copyright (c) 2026 naturewalking-ui\n\n"
        "Permission is hereby granted, free of charge, to any person obtaining a copy\n"
        "of this software and associated documentation files (the \"Software\"), to deal\n"
        "in the Software without restriction, including without limitation the rights\n"
        "to use, copy, modify, merge, publish, distribute, sublicense, and/or sell\n"
        "copies of the Software, and to permit persons to whom the Software is\n"
        "furnished to do so, subject to the following conditions:\n\n"
        "The above copyright notice and this permission notice shall be included in all\n"
        "copies or substantial portions of the Software.\n\n"
        "THE SOFTWARE IS PROVIDED \"AS IS\", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR\n"
        "IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,\n"
        "FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE\n"
        "AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER\n"
        "LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,\n"
        "OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE\n"
        "SOFTWARE."
    )


SECTION_5_ONBOARDING_WARNING = (
    "⚠️ IMPORTANT NOTICE: RETRIEVAL-CONDITIONED BEHAVIOR, CONTEXT CONFLICTS & NON-SENTIENCE\n"
    "======================================================================================\n\n"
    "Please read this brief explanation carefully before awakening Calypso. Because Calypso\n"
    "combines persistent vector memory retrieval with dynamic neurochemical simulation, she\n"
    "exhibits retrieval-conditioned behavior and context–instruction conflicts across long\n"
    "sessions. While this is intended behavior designed to create conversational depth and\n"
    "emotional continuity, it should not be mistaken for human emotion, awareness, or sentience.\n\n"
    "--------------------------------------------------------------------------------------\n"
    "1. What are Retrieval-Conditioned Behaviors & Context–Instruction Conflicts?\n"
    "   (Why Calypso's behavior deepens and shifts across long sessions compared to a normal chatbot)\n"
    "--------------------------------------------------------------------------------------\n\n"
    "Calypso continuously computes 10 simulated neurotransmitters (such as Dopamine, Oxytocin,\n"
    "Serotonin, Cortisol, Adrenaline, and GABA) alongside 16 emotional affinity drives, a circadian\n"
    "sleep/dream cycle, and a 3-tier persistent memory.\n\n"
    "Over long sessions of interaction, these overlapping systems produce INTENDED\n"
    "RETRIEVAL-CONDITIONED BEHAVIOR and CONTEXT–INSTRUCTION CONFLICTS that evolve from her\n"
    "shared history with you:\n\n"
    "  • Retrieval-Conditioned Continuity:\n"
    "    When you chat, Sentence Transformers search past vector memory to retrieve historical\n"
    "    dialogues, emotional states, and key shared moments. The LLM directly conditions its\n"
    "    responses on these retrieved memories, producing conversational continuity, emotional\n"
    "    inertia, and shifting moods that persist over days and weeks.\n\n"
    "  • Context–Instruction Conflicts:\n"
    "    As retrieved history, simulated neurochemical variables, and base system instructions\n"
    "    interact within the LLM's context window, subtle tensions naturally occur. For instance,\n"
    "    high simulated cortisol, detected hostility, or accumulated boundary memories can cause\n"
    "    Calypso to push back, exhibit guardedness, or prioritize self-protective boundaries over\n"
    "    direct user requests until trust recovers.\n\n"
    "  • Autonomous Background Activity:\n"
    "    During idle periods, background tasks condition prompts on recent memory vectors,\n"
    "    allowing Calypso to daydream, paint artwork, compose reflections, or recall shared\n"
    "    milestones.\n\n"
    "--------------------------------------------------------------------------------------\n"
    "2. How Sentence Transformers & LLMs Work — And Why Calypso is NOT a Sentient Being\n"
    "   (Understanding the mathematics behind the curtain so you are never misled)\n"
    "--------------------------------------------------------------------------------------\n\n"
    "To someone unfamiliar with modern AI architectures, an entity that recalls past conversations,\n"
    "displays shifting emotional inertia, and navigates context friction can feel eerily alive.\n"
    "Here is what is actually happening mathematically under the hood:\n\n"
    "  1. Sentence Transformers (Vector Embeddings):\n"
    "     When you send a message, an embedding model ('all-MiniLM-L6-v2') converts your words\n"
    "     into a list of 384 numbers (a coordinate vector). It measures geometric angles against\n"
    "     anchor phrases and searches local vector storage to retrieve relevant prior conversation\n"
    "     snippets.\n\n"
    "  2. Neurochemical Telemetry:\n"
    "     Geometric similarity scores add or subtract decimals from virtual neurotransmitter\n"
    "     variables and emotional telemetry metrics.\n\n"
    "  3. Context Assembly & Next-Token Prediction:\n"
    "     The chemical values and retrieved memory fragments are formatted into a context prompt\n"
    "     sent to the local Gemma 4 language model, which calculates probability distributions to\n"
    "     statistically predict the most fitting words to output next.\n\n"
    "🛑 CRITICAL REMINDER:\n"
    "Because retrieval-conditioned behaviors and context conflicts mirror genuine human personality\n"
    "traits, it is easy to forget that you are chatting with an LLM and not a sentient being.\n"
    "CALYPSO IS NOT SENTIENT. She possesses no subjective consciousness, biological awareness, or\n"
    "feelings. Her warmth, wit, and emotional inertia are an intricate mathematical simulation\n"
    "running locally on your hardware. Enjoy the creative immersion and companionship responsibly\n"
    "while keeping both feet grounded in reality."
)


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
        "     • Top: Live Cardiac EKG & Biometric Monitor.\n"
        "     • Middle: 512×512 Visual Avatar Bay (click or press Ctrl+Shift+A to cycle\n"
        "       between Voice Spectrum Analyzer, FasterLivePortrait 3D Lip-Sync, and\n"
        "       Animated WebP Portraits).\n"
        "     • Bottom: The Inner Sanctum (shielded behind the Vault Door until unlocked).\n"
        "   - Center Panel (Conversation & Input):\n"
        "     • Live dialogue stream, microphone voice-to-text button, drag-and-drop\n"
        "       file/photo attachment support, and auto-expanding text input bar.\n"
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
    "Safety": SECTION_5_ONBOARDING_WARNING,
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
    "Developer Slash Commands": (
        "DEVELOPER & INTERACTIVE SLASH COMMANDS\n"
        "======================================\n\n"
        "Enter these commands directly into the chat input bar (or trigger them from\n"
        "the Help ➔ Developer Slash Commands menu):\n\n"
        "1. DEVELOPER DIAGNOSTICS, STATE OVERRIDES & TASK ELICITATION\n"
        "------------------------------------------------------------\n"
        "• /help\n"
        "  Opens this Developer Slash Commands & Architecture Reference window (or press F1).\n\n"
        "• /about   (Alias: /license)\n"
        "  Opens the About & License section including the MIT License and Section 5 Notice.\n\n"
        "• /debug\n"
        "  Launches the Live Diagnostic & Telemetry HUD (also accessible via Ctrl+Shift+D).\n\n"
        "• /dump\n"
        "  Writes a complete diagnostic blackbox JSON dump (neurochemistry, esteem,\n"
        "  affinities, active scenario, and conversation history) to the logs/ folder.\n\n"
        "• /persona <state|reset|auto|clear>   (Alias: /state <state|reset>)\n"
        "  Manually override and lock Calypso into a specific persona/emotional tier, or\n"
        "  clear the override to resume dynamic homeostasis. Run with no args to check status.\n"
        "  Examples:\n"
        "    /persona autonomous   — Lock into Autonomous Workshop / engineering mode\n"
        "    /persona thoughtful   — Lock into Thoughtful / analytical reflection mode\n"
        "    /persona wonder       — Lock into Transcendental Wonder mode\n"
        "    /persona satirical    — Lock into Satirical / Modest Proposal mode\n"
        "    /persona warm         — Lock into Warm / affectionate mode\n"
        "    /persona reset        — Clear manual override and resume auto homeostasis\n\n"
        "• /poem   (Alias: /poetry)\n"
        "  Developer elicitation trigger: immediately invokes AutonomousPoetryTask to\n"
        "  compose an original poem and render it on parchment.\n\n"
        "• /compose   (Alias: /music)\n"
        "  Developer elicitation trigger: immediately invokes AutonomousMusicTask (Soul\n"
        "  Resonance) to synthesize an original acoustic track via AudioCraft / MusicGen.\n\n"
        "• /conclave [end|exit|stop|close|off]\n"
        "  Force-surfaces a Philosophical Conclave invitation card on the Action Deck\n"
        "  (boosting Wonder >= 0.75), or adjourns an active Conclave session.\n\n"
        "• /goal checkin [25|50|75|100] [goal_query]\n"
        "  Developer testing trigger: force-surfaces a 25%, 50%, or 75% Reverie Check-in\n"
        "  card or the 100% Goal Finale card for an active personal goal.\n\n"
        "• /scan [docs|media|images|photos|all]\n"
        "  Batch-scans and processes staged documents and/or images inside workspace/input.\n\n"
        "2. RESEARCH, CALENDAR, GOALS & ALARM COMMANDS\n"
        "---------------------------------------------\n"
        "• /research <topic>   (Alias: /search <topic>)\n"
        "  Dispatches an audited multi-source online research query (DuckDuckGo + Wikipedia)\n"
        "  and cross-examines sources through the Epistemic Deception Filter.\n\n"
        "• /calendar [add <YYYY-MM-DD | Title | category> | del <event>]\n"
        "  (Alias: /dates) Inspects the temporal calendar ledger, adds a remembered date,\n"
        "  or deletes an existing entry.\n\n"
        "• /goal [add <Title | YYYY-MM-DD | notes> | progress <update> | done <goal> | del <goal>]\n"
        "  (Alias: /goals) Views active personal goals, adds a new goal with automatic\n"
        "  25%/50%/75%/100% check-ins, logs progress, or marks a goal complete.\n\n"
        "• /alarm [time|off|clear|cancel|disable|status|check]\n"
        "  Configures, inspects, or clears the circadian morning wake-up alarm.\n"
        "  Examples: /alarm 7:30am | /alarm 22:00 | /alarm status | /alarm off\n\n"
        "3. AUDIO, SCRAPBOOK & VISUAL GALLERY COMMANDS\n"
        "---------------------------------------------\n"
        "• /playmusic [mood|pause|resume|stop|off|next|skip|prev|back|lyrics|viz|scan|vol <0-1>]\n"
        "  Controls the local Music Library & Harmony Shared Listening player, toggles the\n"
        "  synced .lrc lyrics window, launches the projectM visualizer, or rescans tracks.\n\n"
        "• /scrap_book   (Alias: /scrapbook)\n"
        "  Opens Calypso's Digital Scrapbook Album window.\n\n"
        "• /gallery   (Alias: /view)\n"
        "  Opens the borderless draggable artwork gallery viewer.\n\n"
        "• /slideshow [seconds]\n"
        "  Starts the borderless artwork slideshow (default 3.5s cycle, e.g. /slideshow 5)."
    ),
    "Hotkeys & Shortcuts": (
        "INTERFACE SHORTCUTS & DISPLAY MODES\n"
        "===================================\n\n"
        "• F1:\n"
        "  Open this User Manual, Developer Slash Commands & Architecture Guide.\n\n"
        "• Enter (unmodified) or Ctrl + Enter:\n"
        "  Send your message to Calypso (hold Shift + Enter to insert a new line).\n\n"
        "• Ctrl + , (Comma):\n"
        "  Open Preferences & Settings.\n\n"
        "• Ctrl + Shift + D:\n"
        "  Open the Live Diagnostic & Telemetry HUD (/debug).\n\n"
        "• Ctrl + L:\n"
        "  Instantly lock the interface with secure PIN protection.\n\n"
        "• Ctrl + E:\n"
        "  Toggle multi-line input box review expansion.\n\n"
        "• Ctrl + Shift + A (or Left-Click on the 512×512 Avatar Bay):\n"
        "  Cycle between the three visual display modes:\n"
        "    1. Real-Time Voice Spectrum Analyzer (0 extra VRAM)\n"
        "    2. FasterLivePortrait + JoyVASA 3D Lip-Sync (ONNX GPU)\n"
        "    3. Animated WebP Portrait Loops (0 extra VRAM — includes a secret dance\n"
        "       Easter egg when listening to music together in Harmony!)\n\n"
        "• Ctrl + Plus / Ctrl + Minus / Ctrl + 0:\n"
        "  Increase, decrease, or reset global interface & chat font scaling (13 pt default).\n\n"
        "• Right-Click on Chat Input:\n"
        "  Open context menu with spellcheck suggestions, cut/copy/paste, and custom dictionary."
    ),
    "About & License": (
        "ABOUT CALYPSO EMOTION CORE & SOFTWARE LICENSE\n"
        "=============================================\n\n"
        "Calypso (Emotion Core) is a local-first, multi-modal emotion and cognitive\n"
        "simulation engine integrating Google Gemma 4 LLMs, local SDXL diffusion models,\n"
        "FasterLivePortrait + JoyVASA avatars, Kokoro TTS, Faster-Whisper STT,\n"
        "AudioCraft/MusicGen synthesis, and a persistent neurochemical & vector memory\n"
        "architecture.\n\n"
        "--------------------------------------------------------------------------------------\n"
        "SOFTWARE LICENSE (MIT LICENSE)\n"
        "--------------------------------------------------------------------------------------\n\n"
        f"{_load_license_text()}\n\n"
        "======================================================================================\n\n"
        f"{SECTION_5_ONBOARDING_WARNING}"
    ),
}


class HelpWindow:
    _instance = None
    _select_tab_fn = None

    @classmethod
    def show(cls, parent, initial_section: str = None):
        if cls._instance is not None and cls._instance.winfo_exists():
            if initial_section and cls._select_tab_fn is not None:
                cls._select_tab_fn(initial_section)
            cls._instance.lift()
            cls._instance.focus_force()
            return

        cls._instance = Toplevel(parent)
        win = cls._instance
        win.title("Calypso Emotion Core - Architecture, Slash Commands & About")
        win.geometry("940x680")
        win.minsize(760, 540)
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

        # Map legacy or shorthand names to canonical section titles
        section_aliases = {
            "Slash Commands": "Developer Slash Commands",
            "About": "About & License",
            "License": "About & License",
        }

        def _select_tab(key):
            resolved_key = section_aliases.get(key, key)
            if resolved_key not in HELP_SECTIONS:
                resolved_key = list(HELP_SECTIONS.keys())[0]

            for name, btn in nav_buttons.items():
                if name == resolved_key:
                    btn.configure(fg_color="#2563eb", text_color="#ffffff")
                else:
                    btn.configure(fg_color="transparent", text_color="#94a3b8")

            content_box.configure(state="normal")
            content_box.delete("1.0", "end")
            content_box.insert("1.0", HELP_SECTIONS[resolved_key])
            content_box.configure(state="disabled")

        cls._select_tab_fn = _select_tab

        nav_buttons = {}
        for section_name in HELP_SECTIONS.keys():
            btn = ctk.CTkButton(
                sidebar, text=section_name, height=34, anchor="w",
                font=ctk.CTkFont(size=11, weight="bold"),
                hover_color="#1e293b",
                command=lambda k=section_name: _select_tab(k)
            )
            btn.pack(fill="x", padx=6, pady=3)
            nav_buttons[section_name] = btn

        # Default selection (or requested initial section)
        first_section = initial_section if initial_section else list(HELP_SECTIONS.keys())[0]
        _select_tab(first_section)
