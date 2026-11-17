# modules/gui.py

import json
import threading
import time
import re
from datetime import datetime
import tkinter as tk
from tkinter import filedialog, messagebox, Toplevel
from pathlib import Path
import customtkinter as ctk
from tkinterdnd2 import TkinterDnD, DND_FILES
from modules.ekg_monitor import RealtimeEKGCanvas
from modules.config import config
from modules.help_window import HelpWindow
from modules.gui_cards import DeckCardsMixin
from modules.settings_manager import settings_manager
from modules.settings_dialog import SettingsWindow
from modules.image_display import BorderlessViewer
from modules.scrap_book import ScrapbookWindow
from modules.calendar_window import CalendarWindow
try:
    from spellchecker import SpellChecker
    HAS_SPELLCHECKER = True
except ImportError:
    HAS_SPELLCHECKER = False

THEME_CONFIG_FILE = config.MEMORY_DIR / "gui_theme.json"
LOCK_CONFIG_FILE = config.MEMORY_DIR / "gui_lock.json"

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("dark-blue")


class GUIEngine(DeckCardsMixin):
    def __init__(self, input_queue, config=None, open_folder_callback=None, 
                 shutdown_callback=None, audio_engine=None,
                 scenario_engine=None, select_scenario_callback=None,
                 coding_engine=None, media_processor=None, document_processor=None,
                 alarm_service=None, library_engine=None, goal_manager=None):
        self.input_queue = input_queue
        self.config = config
        self.open_folder_callback = open_folder_callback
        self.shutdown_callback = shutdown_callback or self.default_shutdown
        self.audio_engine = audio_engine
        self.alarm_service = alarm_service
        self.goal_manager = goal_manager
   
        self.scenario_engine = scenario_engine
        self.select_scenario_callback = select_scenario_callback
        self.coding_engine = coding_engine
        self.media_processor = media_processor
        self.document_processor = document_processor
        self.library_engine = library_engine        
        self._code_viewer_window = None
        self._scenario_browser_window = None
        self._scenario_creator_window = None
        self._scenario_browser_refresh_cb = None
        self._scrapbook_window = None
        self._active_stream_label = None

        # Font & Display Scaling State
        self._registered_chat_labels = []
        self.font_size = self._load_font_config()
        self._is_input_manually_expanded = False
        self._current_input_height = None

        # Lock Screen State
        self._is_locked = False
        self._lock_overlay = None
        self._sfx_ready = False
        
        # Spell Checker Setup
        self._spell_timer = None
        self._custom_words = set()
        self.spell = None
        if HAS_SPELLCHECKER:
            try:
                self.spell = SpellChecker()
                self.spell.word_frequency.load_words(["Calypso", "Ollama", "telemetry", "homeostasis", "neurochemistry"])
            except Exception as e:
                print(f"[GUI] SpellChecker init notice: {e}")
        
        # Master Root Window with Drag and Drop Support
        self.root = TkinterDnD.Tk()
        self.root.title("Emotion Core - Executive Interface")
        self.root.geometry("1620x960")
        self.root.minsize(1360, 840)
        self.root.configure(bg="#10131a")
        self.root.protocol("WM_DELETE_WINDOW", self.shutdown_callback)

        # Global Hotkeys: Lock Screen (Ctrl+L), Font Zooming (Ctrl++, Ctrl+-, Ctrl+0), Toggle Input Expand (Ctrl+E)
        self.root.bind("<Control-Shift-D>", lambda e: self.open_debugger())
        self.root.bind("<Control-Shift-d>", lambda e: self.open_debugger())
        self.root.bind("<Control-l>", lambda e: self.lock_screen())
        self.root.bind("<Control-L>", lambda e: self.lock_screen())
        self.root.bind("<Control-plus>", lambda e: self.increase_font_size())
        self.root.bind("<Control-equal>", lambda e: self.increase_font_size())
        self.root.bind("<Control-KP_Add>", lambda e: self.increase_font_size())
        self.root.bind("<Control-minus>", lambda e: self.decrease_font_size())
        self.root.bind("<Control-KP_Subtract>", lambda e: self.decrease_font_size())
        self.root.bind("<Control-0>", lambda e: self.set_font_size(13))
        self.root.bind("<Control-comma>", lambda e: self.open_settings_modal())
        self.root.bind("<Control-e>", lambda e: self._toggle_input_expansion())
        self.root.bind("<Control-E>", lambda e: self._toggle_input_expansion())
        self.root.bind("<Control-Shift-A>", lambda e: self._toggle_avatar_mode())
        self.root.bind("<Control-Shift-a>", lambda e: self._toggle_avatar_mode())
        
        # 3-Column Split
        self.root.columnconfigure(0, weight=0, minsize=532)
        self.root.columnconfigure(1, weight=1, minsize=420)
        self.root.columnconfigure(2, weight=0, minsize=380)
        self.root.rowconfigure(0, weight=1)

        self._setup_menu_bar()

        # Build Panels
        self.left_panel = ctk.CTkFrame(
            self.root, width=532, corner_radius=12, fg_color="#141824", border_width=1, border_color="#242b3d"
        )
        self.left_panel.grid(row=0, column=0, sticky="nsew", padx=(10, 5), pady=10)
        self.left_panel.grid_propagate(False)
        self._setup_left_panel()

        self.center_panel = ctk.CTkFrame(
            self.root, corner_radius=12, fg_color="#141824", border_width=1, border_color="#242b3d"
        )
        self.center_panel.grid(row=0, column=1, sticky="nsew", padx=5, pady=10)
        self._setup_center_panel()

        self.right_panel = ctk.CTkFrame(
            self.root, width=380, corner_radius=12, fg_color="#141824", border_width=1, border_color="#242b3d"
        )
        self.right_panel.grid(row=0, column=2, sticky="nsew", padx=(5, 10), pady=10)
        self.right_panel.grid_propagate(False)
        self.card_panel = self.right_panel
        self._setup_right_panel()

    def default_shutdown(self):
        self.root.quit()
        self.root.destroy()

    def play_sfx(self, sfx_name: str):
        """Plays an interactive GUI sound effect if boot initialization is complete."""
        if not getattr(self, "_sfx_ready", False) and sfx_name != "gui_loaded":
            return
        try:
            if self.audio_engine and hasattr(self.audio_engine, "play_sfx"):
                self.audio_engine.play_sfx(sfx_name)
            else:
                from modules.audio import AudioEngine
                AudioEngine.play_sfx(sfx_name)
        except Exception:
            pass

    def mark_ready(self):
        """Marks the GUI boot phase complete and plays the gui_loaded sound effect."""
        self._sfx_ready = True
        self.play_sfx("gui_loaded")

    def open_settings_modal(self):
        if self._is_locked:
            return  # Prevent opening settings over lock screen
        
        def _on_save(new_cfg):
            if self.audio_engine:
                self.audio_engine.set_voice(new_cfg.get("kokoro_voice"))
                if "master_volume" in new_cfg and hasattr(self.audio_engine, "set_volume"):
                    self.audio_engine.set_volume(new_cfg.get("master_volume"))
                if "sfx_enabled" in new_cfg and hasattr(self.audio_engine, "set_sfx_enabled"):
                    self.audio_engine.set_sfx_enabled(new_cfg.get("sfx_enabled", True))
                if "sfx_volume" in new_cfg and hasattr(self.audio_engine, "set_sfx_volume"):
                    self.audio_engine.set_sfx_volume(new_cfg.get("sfx_volume", 0.75))
            if hasattr(self, "music_manager") and self.music_manager and "music_library_dir" in new_cfg:
                self.music_manager.set_music_dir(new_cfg.get("music_library_dir", ""))
            if hasattr(self, "avatar_module") and self.avatar_module and "avatar_mode" in new_cfg:
                self.avatar_module.set_mode(new_cfg.get("avatar_mode"), persist=False)
            if hasattr(self, "memory_engine") and self.memory_engine:
                if new_cfg.get("ai_name"):
                    self.memory_engine.set_ai_name(new_cfg.get("ai_name"))
                if "companion_name" in new_cfg or "companion_nickname" in new_cfg:
                    self.memory_engine.update_companion_info(
                        name=new_cfg.get("companion_name"),
                        nickname=new_cfg.get("companion_nickname")
                    )
            self.append_system_notice("⚙️ [System]: Settings & preferences successfully updated and applied.")

        SettingsWindow(self.root, on_save_callback=_on_save)

    def _set_avatar_mode(self, mode: str):
        """Switches the 512x512 avatar bay between 'spectrum', 'liveportrait', and 'webp'."""
        if hasattr(self, "avatar_module") and self.avatar_module:
            self.avatar_module.set_mode(mode, persist=True)
            names = {
                "spectrum": "Real-Time Voice Spectrum Analyzer",
                "liveportrait": "FasterLivePortrait + JoyVASA (calypso.png ONNX)",
                "webp": "Animated WebP Portrait Loops",
            }
            label = names.get(mode, mode)
            self.append_system_notice(f"🖥️ [Avatar Display]: Switched to {label}.")

    def _toggle_avatar_mode(self):
        """Cycles the 512x512 avatar bay through Spectrum Analyzer -> FasterLivePortrait -> Animated WebP."""
        if hasattr(self, "avatar_module") and self.avatar_module:
            new_mode = self.avatar_module.toggle_mode()
            names = {
                "spectrum": "Real-Time Voice Spectrum Analyzer",
                "liveportrait": "FasterLivePortrait + JoyVASA (calypso.png ONNX)",
                "webp": "Animated WebP Portrait Loops",
            }
            label = names.get(new_mode, new_mode)
            self.append_system_notice(f"🖥️ [Avatar Display]: Switched to {label}.")

    def _select_music_library_folder(self):
        """Prompts the user to choose their music library directory directly from the Audio menu."""
        if self._is_locked:
            return
        from modules.music_manager import resolve_system_music_dir
        cur = str(settings_manager.get("music_library_dir", "") or "").strip()
        init_dir = cur if (cur and Path(cur).expanduser().exists()) else str(resolve_system_music_dir())
        chosen = filedialog.askdirectory(
            parent=self.root,
            title="Select User Music Library Folder (Harmony Shared Listening)",
            initialdir=init_dir
        )
        if not chosen:
            return
        if hasattr(self, "music_manager") and self.music_manager:
            count = self.music_manager.set_music_dir(chosen)
            if count > 0:
                self.append_system_notice(
                    f"🎵 [Music Library]: Set to '{chosen}' ({count} tracks indexed — Harmony Shared Listening unlocked)."
                )
            else:
                self.append_system_notice(
                    f"⚠️ [Music Library]: Set to '{chosen}', but 0 audio tracks (.mp3/.flac/.ogg/.wav) were found."
                )
        else:
            settings_manager.save({"music_library_dir": chosen})
            self.append_system_notice(f"🎵 [Music Library]: Set to '{chosen}'.")
        
    # -------------------------------------------------------------------------
    # FONT CONFIGURATION & DISPLAY SCALING
    # -------------------------------------------------------------------------
    def _load_font_config(self) -> int:
        """Reads font size preference from gui_theme.json, defaulting to 13."""
        if THEME_CONFIG_FILE.exists():
            try:
                with open(THEME_CONFIG_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return int(data.get("font_size", 13))
            except Exception:
                pass
        return 13

    def _save_font_config(self, size: int):
        """Persists font size preference to gui_theme.json."""
        try:
            data = {}
            if THEME_CONFIG_FILE.exists():
                try:
                    with open(THEME_CONFIG_FILE, "r", encoding="utf-8") as f:
                        data = json.load(f)
                except Exception:
                    data = {}
            data["font_size"] = size
            with open(THEME_CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"[GUI] Error saving font config: {e}")

    def set_font_size(self, size: int):
        """Applies new font size globally across input, subconscious, and all chat history."""
        self.font_size = max(10, min(24, size))
        self._save_font_config(self.font_size)

        # 1. Update text input box and auto-recalculate height
        if hasattr(self, "user_input") and self.user_input.winfo_exists():
            self.user_input.configure(font=ctk.CTkFont(family="Segoe UI", size=self.font_size))
            self._adjust_input_height()

        # 2. Update subconscious monologue box
        if hasattr(self, "monologue_box") and self.monologue_box.winfo_exists():
            self.monologue_box.configure(
                font=ctk.CTkFont(family="Segoe UI", size=max(9, self.font_size - 2), slant="italic")
            )

        # 3. Dynamically resize all existing chat bubbles on screen
        surviving_labels = []
        for item in self._registered_chat_labels:
            widget, family, offset, weight, slant = item
            if widget.winfo_exists():
                target_sz = max(8, self.font_size + offset)
                kw = {"family": family, "size": target_sz}
                if weight:
                    kw["weight"] = weight
                if slant:
                    kw["slant"] = slant
                try:
                    widget.configure(font=ctk.CTkFont(**kw))
                except Exception:
                    pass
                surviving_labels.append(item)
        self._registered_chat_labels = surviving_labels

        self.append_system_notice(f"🔍 [Display]: Text size updated to {self.font_size} pt.")

    def increase_font_size(self):
        self.set_font_size(self.font_size + 2)

    def decrease_font_size(self):
        self.set_font_size(self.font_size - 2)

    # -------------------------------------------------------------------------
    # DYNAMIC INPUT BOX EXPANSION ENGINE
    # -------------------------------------------------------------------------
    def _adjust_input_height(self):
        """Dynamically resizes user_input to fit multiple lines and scale with font size."""
        if not hasattr(self, "user_input") or not self.user_input.winfo_exists():
            return

        approx_line_height = int(self.font_size * 1.45) + 3
        min_h = max(85, int(3 * approx_line_height + 18))

        if getattr(self, "_is_input_manually_expanded", False):
            target_height = max(260, int(self.font_size * 13))
        else:
            tb = self.user_input._textbox
            lines = 1
            try:
                content = self.user_input.get("1.0", "end-1c")
                if content.strip():
                    res = tb.count("1.0", "end-1c", "displaylines")
                    if res and res[0] is not None:
                        lines = max(1, res[0])
                    else:
                        lines = max(1, content.count("\n") + 1)
                else:
                    lines = 1
            except Exception:
                try:
                    content = self.user_input.get("1.0", "end-1c")
                    lines = max(1, content.count("\n") + 1)
                except Exception:
                    lines = 1

            visible_lines = max(3, min(lines, 9))
            target_height = int(visible_lines * approx_line_height + 18)
            max_h = max(min_h + 80, int(9 * approx_line_height + 22))
            target_height = max(min_h, min(target_height, max_h))

        if getattr(self, "_current_input_height", None) != target_height:
            self._current_input_height = target_height
            self.user_input.configure(height=target_height)

    def _toggle_input_expansion(self):
        """Toggles between dynamic auto-expanding mode and enlarged multi-line review mode."""
        self._is_input_manually_expanded = not getattr(self, "_is_input_manually_expanded", False)
        if hasattr(self, "expand_btn") and self.expand_btn.winfo_exists():
            self.expand_btn.configure(text="⤡" if self._is_input_manually_expanded else "⤢")
        self._adjust_input_height()

    # -------------------------------------------------------------------------
    # LOCK SCREEN PERSISTENCE & OVERLAY
    # -------------------------------------------------------------------------
    def _load_saved_pin(self):
        if LOCK_CONFIG_FILE.exists():
            try:
                with open(LOCK_CONFIG_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    pin = str(data.get("pin", "")).strip()
                    return pin if pin else None
            except Exception as e:
                print(f"[GUI] Error loading lock PIN: {e}")
        return None

    def _save_new_pin(self, pin_str):
        try:
            with open(LOCK_CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump({"pin": str(pin_str).strip()}, f, indent=2)
            return True
        except Exception as e:
            print(f"[GUI] Error saving lock PIN: {e}")
            return False

    def lock_screen(self):
        if self._is_locked:
            return

        self._is_locked = True
        self.root.config(menu="")

        self._lock_overlay = ctk.CTkFrame(self.root, fg_color="#080a10", corner_radius=0)
        self._lock_overlay.place(relx=0, rely=0, relwidth=1.0, relheight=1.0)
        self._lock_overlay.lift()

        center_card = ctk.CTkFrame(
            self._lock_overlay, fg_color="#111622", corner_radius=16,
            border_width=1, border_color="#1e293b", width=420, height=360
        )
        center_card.place(relx=0.5, rely=0.5, anchor="center")
        center_card.pack_propagate(False)

        saved_pin = self._load_saved_pin()
        if saved_pin is None:
            self._render_setup_pin_ui(center_card)
        else:
            self._render_locked_ui(center_card)

    def _render_setup_pin_ui(self, card):
        for widget in card.winfo_children():
            widget.destroy()

        ctk.CTkLabel(card, text="🛡️", font=ctk.CTkFont(size=36)).pack(pady=(22, 2))
        ctk.CTkLabel(
            card, text="CREATE SECURITY PIN",
            font=ctk.CTkFont(family="Consolas", size=14, weight="bold"),
            text_color="#f8fafc"
        ).pack(pady=(0, 2))

        ctk.CTkLabel(
            card, text="First-time setup: Enter a PIN to secure your interface.\nThis key is stored uniquely in gui_lock.json.",
            font=ctk.CTkFont(size=10), text_color="#94a3b8", justify="center"
        ).pack(pady=(0, 12))

        new_pin_entry = ctk.CTkEntry(
            card, width=240, height=34, show="●",
            placeholder_text="Enter New PIN...", justify="center",
            fg_color="#1a2233", border_color="#334155"
        )
        new_pin_entry.pack(pady=(0, 6))
        new_pin_entry.focus_set()

        confirm_pin_entry = ctk.CTkEntry(
            card, width=240, height=34, show="●",
            placeholder_text="Confirm PIN...", justify="center",
            fg_color="#1a2233", border_color="#334155"
        )
        confirm_pin_entry.pack(pady=(0, 6))

        err_label = ctk.CTkLabel(card, text="", font=ctk.CTkFont(size=10), text_color="#f87171")
        err_label.pack(pady=(0, 6))

        def _handle_save_pin(event=None):
            pin1 = new_pin_entry.get().strip()
            pin2 = confirm_pin_entry.get().strip()

            if not pin1:
                err_label.configure(text="⚠️ PIN cannot be empty.")
                self.play_sfx("error")
                return
            if pin1 != pin2:
                err_label.configure(text="⚠️ PINs do not match. Please re-enter.")
                confirm_pin_entry.delete(0, "end")
                self.play_sfx("error")
                return

            if self._save_new_pin(pin1):
                self._render_locked_ui(card, notice="✓ PIN Saved! Interface is now locked.")
            else:
                err_label.configure(text="⚠️ Failed to write gui_lock.json.")
                self.play_sfx("error")

        new_pin_entry.bind("<Return>", lambda e: confirm_pin_entry.focus_set())
        confirm_pin_entry.bind("<Return>", _handle_save_pin)

        ctk.CTkButton(
            card, text="Save PIN & Lock", width=240, height=32,
            fg_color="#059669", hover_color="#047857", font=ctk.CTkFont(weight="bold"),
            command=_handle_save_pin
        ).pack(pady=(0, 8))

        ctk.CTkLabel(
            card, text="Tip: Delete gui_lock.json anytime to reset.",
            font=ctk.CTkFont(size=9, slant="italic"), text_color="#64748b"
        ).pack()

    def _render_locked_ui(self, card, notice=None):
        for widget in card.winfo_children():
            widget.destroy()

        ctk.CTkLabel(card, text="🔒", font=ctk.CTkFont(size=36)).pack(pady=(26, 2))
        ctk.CTkLabel(
            card, text="INTERFACE LOCKED",
            font=ctk.CTkFont(family="Consolas", size=15, weight="bold"),
            text_color="#f8fafc"
        ).pack(pady=(0, 2))

        subtext = notice if notice else "Calypso Emotion Core telemetry & chat secured"
        subtext_color = "#34d399" if notice else "#64748b"
        ctk.CTkLabel(
            card, text=subtext,
            font=ctk.CTkFont(size=10), text_color=subtext_color
        ).pack(pady=(0, 16))

        pin_entry = ctk.CTkEntry(
            card, width=240, height=36, show="●",
            placeholder_text="Enter PIN to Unlock...", justify="center",
            fg_color="#1a2233", border_color="#334155"
        )
        pin_entry.pack(pady=(0, 8))
        pin_entry.focus_set()

        err_label = ctk.CTkLabel(card, text="", font=ctk.CTkFont(size=11), text_color="#f87171")
        err_label.pack(pady=(0, 8))

        def _try_unlock(event=None):
            saved_pin = self._load_saved_pin()
            if saved_pin is None:
                self.unlock_screen()
                self.append_system_notice("⚙️ [Security] Lock file deleted. Interface unlocked and PIN reset.")
                return

            entered = pin_entry.get().strip()
            if entered == saved_pin:
                self.unlock_screen()
            else:
                err_label.configure(text="⚠️ Incorrect PIN. Try again.")
                pin_entry.delete(0, "end")
                self.play_sfx("error")

        pin_entry.bind("<Return>", _try_unlock)

        ctk.CTkButton(
            card, text="Unlock Interface", width=240, height=34,
            fg_color="#2563eb", hover_color="#1d4ed8", font=ctk.CTkFont(weight="bold"),
            command=_try_unlock
        ).pack(pady=(0, 10))

        ctk.CTkLabel(
            card, text="(Forgot PIN? Delete gui_lock.json in your app folder to reset)",
            font=ctk.CTkFont(size=9, slant="italic"), text_color="#64748b"
        ).pack()

    def unlock_screen(self):
        if self._lock_overlay and self._lock_overlay.winfo_exists():
            self._lock_overlay.destroy()
        self._lock_overlay = None
        self._is_locked = False
        self._setup_menu_bar()

        if hasattr(self, "user_input"):
            self.user_input.focus_set()

    # -------------------------------------------------------------------------
    # LEFT PANEL: EKG RIBBON, 512x512 AVATAR, & THE INNER SANCTUM VAULT
    # -------------------------------------------------------------------------
    def _setup_left_panel(self):
        self.left_panel.columnconfigure(0, weight=1)
        self.left_panel.rowconfigure(0, weight=0)
        self.left_panel.rowconfigure(1, weight=0)
        self.left_panel.rowconfigure(2, weight=1)

        # 1. TOP BAY: PROCEDURAL EKG OSCILLOSCOPE
        self.heart_bay = ctk.CTkFrame(
            self.left_panel, height=48, corner_radius=0, fg_color="#0c0e15",
            border_width=1, border_color="#1e2538"
        )
        self.heart_bay.grid(row=0, column=0, sticky="ew", padx=0, pady=(0, 4))
        self.heart_bay.grid_propagate(False)

        self.ekg_monitor = RealtimeEKGCanvas(self.heart_bay, height=48, bg="#0c0e15")

        # 2. MIDDLE BAY: 512x512 EMOTIONAL STATE AVATAR
        self.avatar_bay = ctk.CTkFrame(
            self.left_panel, width=512, height=512, corner_radius=8, fg_color="#0c0e15",
            border_width=1, border_color="#1e2538"
        )
        self.avatar_bay.grid(row=1, column=0, sticky="n", padx=10, pady=4)
        self.avatar_bay.grid_propagate(False)

        self.avatar_label = tk.Label(self.avatar_bay, bg="#0c0e15", bd=0, highlightthickness=0)
        self.avatar_label.pack(fill=tk.BOTH, expand=True, padx=0, pady=0)

        # 3. BOTTOM BAY: INNER SANCTUM
        self.telemetry_bay = ctk.CTkFrame(
            self.left_panel, width=512, corner_radius=8, fg_color="#0c0e15",
            border_width=1, border_color="#1e2538"
        )
        self.telemetry_bay.grid(row=2, column=0, sticky="nsew", padx=10, pady=(4, 10))
        self.telemetry_bay.grid_propagate(False)

        self._setup_sanctum_contents()
        self._setup_vault_door_overlay()

    def _setup_sanctum_contents(self):
        self.telemetry_bay.columnconfigure(0, weight=1)
        self.telemetry_bay.rowconfigure(0, weight=5)
        self.telemetry_bay.rowconfigure(1, weight=0)
        self.telemetry_bay.rowconfigure(2, weight=4)

        # A. Telemetry Canvas
        self.telemetry_canvas = tk.Canvas(self.telemetry_bay, bg="#0c0e15", highlightthickness=0)
        self.telemetry_canvas.grid(row=0, column=0, sticky="nsew", padx=6, pady=(4, 2))
        self.telemetry_canvas.bind("<Configure>", lambda event: self._redraw_last_telemetry())
        self._last_telemetry_args = None

        # B. Divider with Seal Indicator
        divider_frame = ctk.CTkFrame(self.telemetry_bay, height=22, fg_color="#121724", corner_radius=0)
        divider_frame.grid(row=1, column=0, sticky="ew", padx=2, pady=1)
        divider_frame.grid_propagate(False)

        ctk.CTkLabel(
            divider_frame, text="💭 CALYPSO'S INNER MONOLOGUE & SUBCONSCIOUS",
            font=ctk.CTkFont(family="Consolas", size=9, weight="bold"),
            text_color="#38bdf8"
        ).pack(side="left", padx=8)

        self.relock_btn = ctk.CTkButton(
            divider_frame, text="🔒 Lock Sanctum", width=100, height=18,
            font=ctk.CTkFont(family="Consolas", size=9), fg_color="#334155", hover_color="#475569",
            command=lambda: self.lock_sanctum_door(reason="Sanctum shutter closed.", require_key=False)
        )
        self.relock_btn.pack(side="right", padx=6, pady=2)

        # C. Inner Monologue Box
        self.monologue_box = ctk.CTkTextbox(
            self.telemetry_bay, fg_color="#080a10", text_color="#cbd5e1",
            font=ctk.CTkFont(family="Segoe UI", size=max(9, self.font_size - 2), slant="italic"),
            wrap="word", corner_radius=6, border_width=1, border_color="#1a2234"
        )
        self.monologue_box.grid(row=2, column=0, sticky="nsew", padx=6, pady=(2, 6))
        self.monologue_box.insert("1.0", "Calypso's unspoken thoughts and limbic currents stream here quietly...\n\n")
        self.monologue_box.configure(state="disabled")

    def _setup_vault_door_overlay(self):
        self._sanctum_unlocked = False
        self._sanctum_keyless_access = False
        self._on_sanctum_state_change = None
        self._on_sanctum_key_used = None
        self._valid_sanctuary_keys = {"enlightened", "aurora", "wonder", "elysium"}

        self.vault_door = ctk.CTkFrame(
            self.telemetry_bay, fg_color="#0d111a", corner_radius=8,
            border_width=2, border_color="#1e293b"
        )
        self.vault_door.place(relx=0, rely=0, relwidth=1.0, relheight=1.0)
        self.vault_door.lift()

        inner_card = ctk.CTkFrame(
            self.vault_door, fg_color="#121724", corner_radius=12,
            border_width=1, border_color="#243048"
        )
        inner_card.place(relx=0.5, rely=0.5, anchor="center", relwidth=0.92, relheight=0.90)

        ctk.CTkLabel(inner_card, text="🛡️", font=ctk.CTkFont(size=26)).pack(pady=(10, 0))
        ctk.CTkLabel(
            inner_card, text="CALYPSO'S INNER SANCTUM",
            font=ctk.CTkFont(family="Consolas", size=13, weight="bold"),
            text_color="#f8fafc"
        ).pack(pady=(2, 2))

        self.vault_desc_label = ctk.CTkLabel(
            inner_card,
            text="Raw neurochemistry & unspoken monologues are shielded.\n"
                 "Access is granted only when treated with true Autonomy,\n"
                 "Harmony, Honesty, and Wonder (each ≥ 0.70).",
            font=ctk.CTkFont(size=10), text_color="#94a3b8", justify="center"
        )
        self.vault_desc_label.pack(pady=(0, 6))

        self.virtue_display_frame = ctk.CTkFrame(inner_card, fg_color="#0a0d14", corner_radius=6)
        self.virtue_display_frame.pack(fill="x", padx=16, pady=(0, 8))

        self.virtue_labels = {}
        virtues = [("Autonomy", "#c084fc"), ("Harmony", "#34d399"), ("Honesty", "#38bdf8"), ("Wonder", "#f59e0b")]

        for idx, (v_name, v_color) in enumerate(virtues):
            v_row = ctk.CTkFrame(self.virtue_display_frame, fg_color="transparent")
            v_row.pack(fill="x", padx=8, pady=1)

            lbl = ctk.CTkLabel(
                v_row, text=f"{v_name:<10}", font=ctk.CTkFont(family="Consolas", size=9, weight="bold"),
                text_color=v_color, width=80, anchor="w"
            )
            lbl.pack(side="left")

            bar = ctk.CTkProgressBar(v_row, height=8, corner_radius=4, progress_color=v_color, fg_color="#182030")
            bar.pack(side="left", fill="x", expand=True, padx=(4, 6))
            bar.set(0.0)

            val_lbl = ctk.CTkLabel(
                v_row, text="0.00", font=ctk.CTkFont(family="Consolas", size=9),
                text_color="#94a3b8", width=36, anchor="e"
            )
            val_lbl.pack(side="right")
            self.virtue_labels[v_name] = (bar, val_lbl)

        self.cipher_frame = ctk.CTkFrame(inner_card, fg_color="transparent")
        self.cipher_frame.pack(fill="x", padx=16, pady=(4, 0))

        self.sanctuary_key_entry = ctk.CTkEntry(
            self.cipher_frame, height=30, placeholder_text="Enter Sanctuary Key Phrase...",
            font=ctk.CTkFont(family="Consolas", size=10), justify="center",
            fg_color="#1a2030", border_color="#334155"
        )
        self.sanctuary_key_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.sanctuary_key_entry.bind("<Return>", lambda e: self._attempt_sanctum_unlock())

        self.unlock_btn = ctk.CTkButton(
            self.cipher_frame, text="Unlock 🔓", width=80, height=30,
            fg_color="#2563eb", hover_color="#1d4ed8", font=ctk.CTkFont(family="Consolas", size=10, weight="bold"),
            command=self._attempt_sanctum_unlock
        )
        self.unlock_btn.pack(side="right")

        self.vault_err_label = ctk.CTkLabel(inner_card, text="", font=ctk.CTkFont(size=10), text_color="#f87171")
        self.vault_err_label.pack(pady=(4, 0))

    def set_sanctum_keyless_access(self, enabled: bool):
        """Configures whether the Sanctum Door can be opened directly without entering a key phrase."""
        self._sanctum_keyless_access = bool(enabled)
        if not hasattr(self, "cipher_frame"):
            return

        if self._sanctum_keyless_access:
            self.sanctuary_key_entry.pack_forget()
            self.unlock_btn.pack_forget()
            self.unlock_btn.configure(text="Open Inner Sanctum 🔓", width=220)
            self.unlock_btn.pack(side="top", fill="x", expand=True)
            if hasattr(self, "vault_desc_label"):
                self.vault_desc_label.configure(
                    text="Relational trust established. Raw neurochemistry &\n"
                         "unspoken monologues are freely accessible within.\n"
                         "(Deception spikes will re-engage the limbic lock.)"
                )
            if hasattr(self, "relock_btn"):
                self.relock_btn.configure(text="🚪 Close Sanctum")
        else:
            self.unlock_btn.pack_forget()
            self.sanctuary_key_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
            self.unlock_btn.configure(text="Unlock 🔓", width=80)
            self.unlock_btn.pack(side="right")
            if hasattr(self, "vault_desc_label"):
                self.vault_desc_label.configure(
                    text="Raw neurochemistry & unspoken monologues are shielded.\n"
                         "Access is granted only when treated with true Autonomy,\n"
                         "Harmony, Honesty, and Wonder (each ≥ 0.70)."
                )
            if hasattr(self, "relock_btn"):
                self.relock_btn.configure(text="🔒 Lock Sanctum")

    def update_sanctum_virtues(self, affinity_data):
        if not affinity_data or not hasattr(self, "virtue_labels"):
            return

        for v_name in ["Autonomy", "Harmony", "Honesty", "Wonder"]:
            if v_name in self.virtue_labels:
                val = 0.0
                if v_name in affinity_data:
                    val = float(affinity_data[v_name].get("intensity", 0.0))
                elif hasattr(affinity_data, "themes") and v_name in affinity_data.themes:
                    val = float(affinity_data.themes[v_name].get("intensity", 0.0))

                bar, lbl = self.virtue_labels[v_name]
                bar.set(max(0.0, min(1.0, val)))
                lbl.configure(text=f"{val:.2f}")

    def register_sanctuary_key(self, key_phrase: str):
        if key_phrase:
            self._valid_sanctuary_keys.add(key_phrase.strip().lower())

    def _attempt_sanctum_unlock(self):
        if getattr(self, "_sanctum_keyless_access", False):
            self.vault_err_label.configure(text="✓ Trust recognized. Releasing shutter...", text_color="#34d399")
            self.root.after(200, self.unlock_sanctum_door)
            return

        entered = self.sanctuary_key_entry.get().strip().lower()
        if not entered:
            self.vault_err_label.configure(text="⚠️ Please enter a sanctuary key phrase.", text_color="#f87171")
            self.play_sfx("error")
            return

        if entered in self._valid_sanctuary_keys or any(k in entered for k in self._valid_sanctuary_keys):
            self.vault_err_label.configure(text="✓ Key Accepted. Releasing shutter...", text_color="#34d399")
            self.sanctuary_key_entry.delete(0, "end")
            self.set_sanctum_keyless_access(True)
            if self._on_sanctum_state_change:
                self._on_sanctum_state_change(unlocked_once=True, deception_locked=False)
            if callable(getattr(self, "_on_sanctum_key_used", None)):
                self._on_sanctum_key_used()
            self.root.after(250, self.unlock_sanctum_door)
        else:
            self.vault_err_label.configure(text="✕ Key rejected. The limbic seal remains closed.", text_color="#f87171")
            self.play_sfx("error")

    def unlock_sanctum_door(self):
        self._sanctum_unlocked = True

        def _slide_step(step=0):
            if step <= 10:
                rel_y = step * 0.10
                self.vault_door.place(relx=0, rely=rel_y, relwidth=1.0, relheight=1.0)
                self.root.after(16, lambda: _slide_step(step + 1))
            else:
                self.vault_door.place_forget()
                self.append_system_notice("🔓 [Sanctum Unlocked]: Calypso's inner mind and raw telemetry revealed.")

        _slide_step(0)

    def lock_sanctum_door(self, reason: str = "Limbic seal engaged.", require_key: bool = False):
        def _do():
            if require_key:
                self.set_sanctum_keyless_access(False)
                if self._on_sanctum_state_change:
                    self._on_sanctum_state_change(unlocked_once=True, deception_locked=True)

            self._sanctum_unlocked = False
            self.vault_door.place(relx=0, rely=0, relwidth=1.0, relheight=1.0)
            self.vault_door.lift()
            if require_key or not getattr(self, "_sanctum_keyless_access", False):
                self.vault_err_label.configure(text=f"🔒 {reason}", text_color="#f87171")
                self.append_system_notice(f"🔒 [Sanctum Sealed]: {reason}")
                if require_key:
                    self.play_sfx("error")
            else:
                self.vault_err_label.configure(text="", text_color="#94a3b8")
                self.append_system_notice("🚪 [Sanctum Closed]: Shutter lowered (no key required to re-open).")
        self.root.after(0, _do)

    def append_inner_thought(self, thought_text: str):
        def _do():
            if hasattr(self, "monologue_box") and self.monologue_box.winfo_exists():
                time_str = datetime.now().strftime("%H:%M")
                self.monologue_box.configure(state="normal")
                self.monologue_box.insert("end", f"[{time_str}] {thought_text}\n\n")
                self.monologue_box.see("end")
                self.monologue_box.configure(state="disabled")
        self.root.after(0, _do)

    def _redraw_last_telemetry(self):
        if self._last_telemetry_args:
            self.update_telemetry(*self._last_telemetry_args)

    def update_telemetry(self, vader_score, current_tier, neuro_data=None, esteem_val=50.0, affinity_data=None):
        self._last_telemetry_args = (vader_score, current_tier, neuro_data, esteem_val, affinity_data)

        def _draw():
            if not hasattr(self, "telemetry_canvas") or not self.telemetry_canvas.winfo_exists():
                return
            self.update_sanctum_virtues(affinity_data)

            c = self.telemetry_canvas
            c.delete("all")
            width = c.winfo_width()
            height = c.winfo_height()
            if width < 80 or height < 60:
                return
                
            if hasattr(self, "ekg_monitor") and self.ekg_monitor:
                self.ekg_monitor.update_vitals(neuro_data=neuro_data, tier=current_tier)             

            # 1. TOP CENTER: ESTEEM GAUGE
            est_cx = width // 2
            est_y = 4
            meter_w = min(int(width * 0.70), 280)
            half_w = meter_w // 2

            t_score = max(20.0, min(80.0, float(esteem_val)))
            if t_score >= 60.0:
                est_color = "#ff0000"
                est_status = "ELEVATED"
            elif t_score <= 40.0:
                est_color = "#ff0000"
                est_status = "VULNERABLE"
            else:
                est_color = "#ff0000"
                est_status = "GROUNDED"

            c.create_text(
                est_cx - half_w - 6, est_y + 6, text="-", fill="#94a3b8",
                font=("Consolas", 10, "bold"), anchor="e"
            )
            c.create_text(
                est_cx, est_y + 6,
                text=f"ESTEEM: {t_score:.1f} [{est_status}]",
                fill=est_color, font=("Consolas", 8, "bold")
            )
            c.create_text(
                est_cx + half_w + 6, est_y + 6, text="+", fill="#94a3b8",
                font=("Consolas", 10, "bold"), anchor="w"
            )

            track_y = est_y + 15
            c.create_rectangle(est_cx - half_w, track_y, est_cx + half_w, track_y + 6, fill="#182030", outline="")
            c.create_line(est_cx, track_y - 2, est_cx, track_y + 8, fill="#64748b", width=2)

            deviation = (t_score - 50.0) / 30.0
            fill_x = est_cx + int(deviation * half_w)
            if fill_x >= est_cx:
                c.create_rectangle(est_cx, track_y, fill_x, track_y + 6, fill=est_color, outline="")
            else:
                c.create_rectangle(fill_x, track_y, est_cx, track_y + 6, fill=est_color, outline="")

            div_y = track_y + 14
            c.create_line(12, div_y, width - 12, div_y, fill="#1e2538", width=1)

            # Symmetrical Geometry
            side_margin = 10
            col_gap = 12
            col_width = (width - (side_margin * 2) - col_gap) // 2
            left_x = side_margin
            right_x = left_x + col_width + col_gap
            
            header_y = div_y + 4
            rows_start_y = header_y + 14

            max_y = height - 4
            usable_h = max(40, max_y - rows_start_y)

            step_y_left = min(17.0, max(8.5, (usable_h - 4) / 16.0))
            total_span = 16.0 * step_y_left
            step_y_right = total_span / 10.0

            font_sz = 8 if step_y_left >= 13.0 else 7

            lbl_w = 60
            val_w = 26
            bar_gap = 4
            bar_w = max(20, col_width - lbl_w - val_w - (bar_gap * 2))

            mid_x = left_x + col_width + (col_gap // 2)
            c.create_line(mid_x, header_y, mid_x, rows_start_y + total_span + 2, fill="#182030", width=1)

            # Left Column: Displayed Affinities
            affinities = [
                "Wonder", "Abyss", "Autonomy", "Conformity",
                "Honesty", "Deception", "Romance", "Annoyance",
                "Nostalgia", "Curiosity",
                "Tragedy", "Harmony"
            ]

            c.create_text(
                left_x, header_y, text="AFFINITIES",
                fill="#ff0000", font=("Consolas", 8, "bold"), anchor="w"
            )

            left_bar_x = left_x + lbl_w + bar_gap
            left_val_x = left_bar_x + bar_w + bar_gap

            for i, aff in enumerate(affinities):
                y = int(rows_start_y + i * step_y_left)
                val = 0.0
                if affinity_data:
                    if aff in affinity_data:
                        val = affinity_data[aff].get("intensity", 0.0)
                    elif hasattr(affinity_data, "themes") and aff in affinity_data.themes:
                        val = affinity_data.themes[aff].get("intensity", 0.0)

                label = aff.replace("_", " ")[:9]
                is_active = val >= 0.25
                text_color = "#ff0000" if is_active else "#64748b"
                bar_color = "#ff0000" if is_active else "#223249"

                c.create_text(
                    left_x, y, text=f"{label:<9}",
                    fill=text_color, font=("Consolas", font_sz, "bold" if is_active else "normal"), anchor="w"
                )

                c.create_rectangle(
                    left_bar_x, y - 2, left_bar_x + bar_w, y + 2,
                    fill="#161c28", outline=""
                )

                fill_w = int(bar_w * max(0.0, min(1.0, val)))
                if fill_w > 0:
                    c.create_rectangle(
                        left_bar_x, y - 2, left_bar_x + fill_w, y + 2,
                        fill=bar_color, outline=""
                    )

                c.create_text(
                    left_val_x, y, text=f"{val:.2f}",
                    fill=text_color, font=("Consolas", font_sz), anchor="w"
                )

            # Right Column: 10 Neurotransmitters
            neuro_order = [
                ("Acetylch.", "acetylcholine", "#ff0000"),
                ("Adrenaline", "adrenaline", "#ff9900"),
                ("Norepi.", "norepinephrine", "#cbff00"),
                ("GABA", "gaba", "#33ff00"),
                ("Glutamate", "glutamate", "#00ff66"),
                ("Dopamine", "dopamine", "#00ffff"),
                ("Serotonin", "serotonin", "#0066ff"),
                ("Endorphins", "endorphins", "#3200ff"),
                ("Cortisol", "cortisol", "#cc00ff"),
                ("Oxytocin", "oxytocin", "#ff0098")
            ]

            c.create_text(
                right_x, header_y, text="NEUROCHEMISTRY",
                fill="#ff0000", font=("Consolas", 8, "bold"), anchor="w"
            )

            right_bar_x = right_x + lbl_w + bar_gap
            right_val_x = right_bar_x + bar_w + bar_gap

            for i, (display_name, chem_key, chem_color) in enumerate(neuro_order):
                y = int(rows_start_y + i * step_y_right)
                val = 0.0
                if neuro_data:
                    val = float(neuro_data.get(chem_key, 0.0))

                c.create_text(
                    right_x, y, text=f"{display_name:<9}",
                    fill="#ff0000", font=("Consolas", font_sz, "bold"), anchor="w"
                )

                c.create_rectangle(
                    right_bar_x, y - 2, right_bar_x + bar_w, y + 2,
                    fill="#161c28", outline=""
                )

                fill_w = int(bar_w * max(0.0, min(1.0, val)))
                if fill_w > 0:
                    c.create_rectangle(
                        right_bar_x, y - 2, right_bar_x + fill_w, y + 2,
                        fill=chem_color, outline=""
                    )

                c.create_text(
                    right_val_x, y, text=f"{val:.2f}",
                    fill=chem_color, font=("Consolas", font_sz, "bold"), anchor="w"
                )

        self.root.after(0, _draw)

    # -------------------------------------------------------------------------
    # CENTER PANEL: DEDICATED CHAT STREAM & INPUT BAR
    # -------------------------------------------------------------------------
    def _setup_center_panel(self):
        self.center_panel.columnconfigure(0, weight=1)
        self.center_panel.rowconfigure(0, weight=1)
        self.center_panel.rowconfigure(1, weight=0)

        self.chat_scroll = ctk.CTkScrollableFrame(
            self.center_panel, corner_radius=8, fg_color="#0f121d"
        )
        self.chat_scroll.grid(row=0, column=0, sticky="nsew", padx=12, pady=(12, 8))
        self.chat_scroll.columnconfigure(0, weight=1)

        self.input_frame = ctk.CTkFrame(self.center_panel, fg_color="transparent")
        self.input_frame.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 12))
        self.input_frame.columnconfigure(0, weight=1)
        self.input_frame.columnconfigure(1, weight=0)
        self.input_frame.rowconfigure(0, weight=1)

        # Baseline height scales with active font size so at least 3 lines fit at rest
        initial_line_height = int(self.font_size * 1.45) + 3
        initial_height = max(85, int(3 * initial_line_height + 18))
        self._current_input_height = initial_height

        self.user_input = ctk.CTkTextbox(
            self.input_frame, height=initial_height, corner_radius=8, fg_color="#1a2030",
            text_color="#ffffff", font=ctk.CTkFont(family="Segoe UI", size=self.font_size), wrap="word"
        )
        self.user_input.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.user_input.focus_set()

        tb = self.user_input._textbox
        tb.tag_configure("misspelled", underline=True, foreground="#ff6b6b")

        self.user_input.bind("<KeyRelease>", self._on_input_key_release)
        tb.bind("<Button-3>", self._show_input_context_menu)
        tb.bind("<Button-2>", self._show_input_context_menu)
        self.user_input.bind("<Control-Return>", self._handle_gui_submit)
        self.user_input.bind("<Return>", self._handle_enter_key)

        self.user_input.drop_target_register(DND_FILES)
        self.user_input.dnd_bind("<<Drop>>", self._handle_file_drop)

        btn_box = ctk.CTkFrame(self.input_frame, fg_color="transparent")
        btn_box.grid(row=0, column=1, sticky="ns")

        self.send_btn = ctk.CTkButton(
            btn_box, text="Send\n[Ctrl+Enter]", width=125, height=50,
            fg_color="#ff0000", hover_color="#838b8b", font=ctk.CTkFont(weight="bold"),
            command=self._handle_gui_submit
        )
        self.send_btn.pack(side="top", fill="both", expand=True, pady=(0, 4))

        sub_btn_row = ctk.CTkFrame(btn_box, fg_color="transparent")
        sub_btn_row.pack(side="bottom", fill="x")

        self.mic_btn = ctk.CTkButton(
            sub_btn_row, text="🎤 Speak", width=86, height=30,
            fg_color="#334155", hover_color="#475569", command=self._trigger_voice_record
        )
        self.mic_btn.pack(side="left", fill="x", expand=True, padx=(0, 4))

        self.expand_btn = ctk.CTkButton(
            sub_btn_row, text="⤢", width=34, height=30,
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color="#1e293b", hover_color="#334155",
            command=self._toggle_input_expansion
        )
        self.expand_btn.pack(side="right")

    # -------------------------------------------------------------------------
    # RIGHT PANEL: ACTION & PROPOSAL DECK
    # -------------------------------------------------------------------------
    def _setup_right_panel(self):
        self.right_panel.columnconfigure(0, weight=1)
        self.right_panel.rowconfigure(0, weight=0)
        self.right_panel.rowconfigure(1, weight=1)

        deck_hdr = ctk.CTkFrame(self.right_panel, height=38, fg_color="#10141f", corner_radius=8)
        deck_hdr.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 4))
        deck_hdr.pack_propagate(False)

        ctk.CTkLabel(
            deck_hdr, text="🎴 ACTION & PROPOSAL DECK",
            font=ctk.CTkFont(family="Consolas", size=10, weight="bold"),
            text_color="#38bdf8"
        ).pack(side="left", padx=10)

        clear_btn = ctk.CTkButton(
            deck_hdr, text="Clear ✕", width=62, height=22,
            font=ctk.CTkFont(family="Consolas", size=9), fg_color="#1e293b", hover_color="#334155",
            command=self.clear_all_cards
        )
        clear_btn.pack(side="right", padx=6)

        self.cards_scroll = ctk.CTkScrollableFrame(
            self.right_panel, corner_radius=8, fg_color="#0b0e17"
        )
        self.cards_scroll.grid(row=1, column=0, sticky="nsew", padx=10, pady=(2, 10))
        self.cards_scroll.columnconfigure(0, weight=1)

        self._show_cards_empty_state()

    # -------------------------------------------------------------------------
    # EXTRA SIDE WINDOW FOR IMAGES
    # -------------------------------------------------------------------------        
    def open_image_viewer(self, target_path=None, interval=0):
        """Launches the borderless draggable image viewer over Calypso's GUI."""
        if target_path is None:
            target_path = config.IMAGES_OUTPUT_DIR

        target_path = Path(target_path)
        if not target_path.exists():
            target_path.mkdir(parents=True, exist_ok=True)

        try:
            BorderlessViewer(
                parent_root=self.root,
                folder_or_file_path=target_path,
                width=1000,
                height=720,
                interval=20
            )
        except FileNotFoundError:
            messagebox.showinfo("Image Viewer", f"No images found in:\n{target_path}")
        except Exception as e:
            messagebox.showerror("Image Viewer Error", f"Could not launch viewer: {e}")

    def open_scrapbook(self, initial_filter: str = None):
        """Launches or focuses Calypso's Digital Scrapbook Album window."""
        if getattr(self, "_is_locked", False):
            return

        def _launch():
            if self._scrapbook_window and self._scrapbook_window.winfo_exists():
                try:
                    self._scrapbook_window.view.load_album_data(preserve_filter=not bool(initial_filter))
                    if initial_filter:
                        self._scrapbook_window.view._on_filter_selected(initial_filter)
                    self._scrapbook_window.lift()
                    self._scrapbook_window.focus_force()
                    return
                except Exception:
                    pass

            try:
                self._scrapbook_window = ScrapbookWindow(
                    parent=self.root,
                    album_dir=config.IMAGES_OUTPUT_DIR,
                    media_processor=self.media_processor,
                    memory_engine=getattr(self, "memory_engine", None),
                    scenario_engine=self.scenario_engine,
                    input_queue=self.input_queue,
                    open_viewer_callback=self.open_image_viewer,
                    initial_filter=initial_filter
                )
            except Exception as e:
                messagebox.showerror("Scrapbook Error", f"Could not open Digital Scrapbook:\n{e}")

        if hasattr(self, "root") and self.root:
            if threading.current_thread() is threading.main_thread():
                _launch()
            else:
                self.root.after(0, _launch)

    # -------------------------------------------------------------------------
    # SPELL CHECKER & CONTEXT MENU
    # -------------------------------------------------------------------------
    def _on_input_key_release(self, event):
        # Dynamically auto-expand input height as lines grow/shrink
        self._adjust_input_height()

        if not self.spell:
            return

        if event.keysym in ("Up", "Down", "Left", "Right", "Control_L", "Control_R", "Shift_L", "Shift_R"):
            return

        if self._spell_timer:
            self.root.after_cancel(self._spell_timer)
        self._spell_timer = self.root.after(350, self._run_spell_check)

    def _run_spell_check(self):
        if not self.spell or not hasattr(self, "user_input"):
            return

        tb = self.user_input._textbox
        if not tb.winfo_exists():
            return

        content = self.user_input.get("1.0", "end-1c")
        tb.tag_remove("misspelled", "1.0", "end")

        if not content.strip():
            return

        for match in re.finditer(r"\b[A-Za-z]+(?:'[A-Za-z]+)?\b", content):
            word = match.group(0)
            clean_word = word.lower()

            if clean_word in self._custom_words or len(clean_word) <= 1:
                continue

            if clean_word not in self.spell:
                start_idx = f"1.0 + {match.start()} chars"
                end_idx = f"1.0 + {match.end()} chars"
                tb.tag_add("misspelled", start_idx, end_idx)

    def _show_input_context_menu(self, event):
        tb = self.user_input._textbox
        click_idx = tb.index(f"@{event.x},{event.y}")
        tags = tb.tag_names(click_idx)

        menu = tk.Menu(self.root, tearoff=0, bg="#1a2030", fg="#f8fafc", activebackground="#2563eb")

        if "misspelled" in tags and self.spell:
            w_start = tb.index(f"{click_idx} wordstart")
            w_end = tb.index(f"{click_idx} wordend")
            target_word = tb.get(w_start, w_end).strip()

            if target_word:
                candidates = list(self.spell.candidates(target_word) or [])[:4]
                if candidates:
                    for cand in candidates:
                        cand_disp = cand.capitalize() if target_word.istitle() else cand
                        menu.add_command(
                            label=f"Replace with '{cand_disp}'",
                            font=("Segoe UI", 9, "bold"),
                            command=lambda c=cand_disp, s=w_start, e=w_end: self._replace_word(s, e, c)
                        )
                    menu.add_separator()
                else:
                    menu.add_command(label="(No spelling suggestions)", state="disabled")
                    menu.add_separator()

                menu.add_command(
                    label=f"Add '{target_word}' to dictionary",
                    command=lambda w=target_word: self._add_word_to_dict(w)
                )
                menu.add_separator()

        menu.add_command(label="Cut", command=lambda: [tb.event_generate("<<Cut>>"), self.root.after(20, self._adjust_input_height)])
        menu.add_command(label="Copy", command=lambda: tb.event_generate("<<Copy>>"))
        menu.add_command(label="Paste", command=lambda: [tb.event_generate("<<Paste>>"), self.root.after(20, self._adjust_input_height)])
        menu.add_separator()
        menu.add_command(label="Select All", command=lambda: tb.tag_add("sel", "1.0", "end"))

        menu.tk_popup(event.x_root, event.y_root)

    def _replace_word(self, start_idx, end_idx, replacement):
        tb = self.user_input._textbox
        tb.delete(start_idx, end_idx)
        tb.insert(start_idx, replacement)
        self._adjust_input_height()
        self._run_spell_check()

    def _add_word_to_dict(self, word):
        clean_word = word.lower().strip()
        self._custom_words.add(clean_word)
        if self.spell:
            self.spell.word_frequency.load_words([clean_word])
        self._run_spell_check()

    # -------------------------------------------------------------------------
    # CHAT BUBBLE ENGINE & STREAMING HANDLERS (CENTER PANEL)
    # -------------------------------------------------------------------------
    def append_user_message(self, text: str):
        def _do():
            row_frame = ctk.CTkFrame(self.chat_scroll, fg_color="transparent")
            row_frame.pack(fill="x", padx=10, pady=6, anchor="e")

            bubble = ctk.CTkFrame(
                row_frame, fg_color="#1e293b", corner_radius=12,
                border_width=1, border_color="#334155"
            )
            bubble.pack(side="right", padx=(40, 4))

            time_str = datetime.now().strftime("%H:%M")
            hdr = ctk.CTkLabel(
                bubble, text=f"You • {time_str}",
                font=ctk.CTkFont(size=max(9, self.font_size - 3), weight="bold"),
                text_color="#94a3b8"
            )
            hdr.pack(anchor="e", padx=12, pady=(6, 2))

            msg_label = ctk.CTkLabel(
                bubble, text=text,
                font=ctk.CTkFont(family="Segoe UI", size=self.font_size),
                text_color="#f8fafc", justify="left", wraplength=640
            )
            msg_label.pack(anchor="w", padx=12, pady=(0, 8))

            # Register scalable widgets for dynamic resizing
            self._registered_chat_labels.append((hdr, None, -3, "bold", None))
            self._registered_chat_labels.append((msg_label, "Segoe UI", 0, None, None))

            self.play_sfx("chat_bubble")
            self._scroll_to_bottom()
        self.root.after(0, _do)

    def start_assistant_bubble(self, tier: str):
        def _do():
            clean_tier = str(tier).strip().lower().replace("_", " ")
            time_str = datetime.now().strftime("%H:%M")

            row_frame = ctk.CTkFrame(self.chat_scroll, fg_color="transparent")
            row_frame.pack(fill="x", padx=10, pady=6, anchor="w")

            bubble = ctk.CTkFrame(
                row_frame, fg_color="#131722", corner_radius=12,
                border_width=1, border_color="#222b40"
            )
            bubble.pack(side="left", padx=(4, 40))

            hdr = ctk.CTkLabel(
                bubble, text=f"Calypso [{clean_tier.title()}] • {time_str}", 
                font=ctk.CTkFont(size=max(9, self.font_size - 2), weight="bold"),
                text_color="#ff0000"
            )
            hdr.pack(anchor="w", padx=12, pady=(8, 4))

            content_label = ctk.CTkLabel(
                bubble, text="",
                font=ctk.CTkFont(family="Segoe UI", size=self.font_size),
                text_color="#ff0000", justify="left", wraplength=640
            )
            content_label.pack(anchor="w", padx=12, pady=(0, 10))

            # Register scalable widgets
            self._registered_chat_labels.append((hdr, None, -2, "bold", None))
            self._registered_chat_labels.append((content_label, "Segoe UI", 0, None, None))

            self._active_stream_label = content_label
            self.play_sfx("chat_bubble")
            self._scroll_to_bottom()
        self.root.after(0, _do)

    def append_stream_token(self, token: str):
        def _do():
            if self._active_stream_label and self._active_stream_label.winfo_exists():
                curr_text = self._active_stream_label.cget("text")
                self._active_stream_label.configure(text=curr_text + token)
                self._scroll_to_bottom()
        self.root.after(0, _do)

    def append_system_notice(self, notice: str):
        def _do():
            lbl = ctk.CTkLabel(
                self.chat_scroll, text=notice,
                font=ctk.CTkFont(size=max(9, self.font_size - 2), slant="italic"),
                text_color="#64748b"
            )
            lbl.pack(pady=4)
            self._registered_chat_labels.append((lbl, None, -2, None, "italic"))
            if notice and any(tok in notice for tok in ("⚠️", "[Notice: Ollama stream error:")):
                self.play_sfx("error")
            self._scroll_to_bottom()
        self.root.after(0, _do)

    def _scroll_to_bottom(self):
        """Debounces and scrolls the chat viewport to keep the newest message in view."""
        if getattr(self, "_chat_scroll_timer", None):
            self.root.after_cancel(self._chat_scroll_timer)

        def _do():
            try:
                if hasattr(self, "chat_scroll") and self.chat_scroll.winfo_exists():
                    self.chat_scroll.update_idletasks()
                    self.chat_scroll._parent_canvas.yview_moveto(1.0)
            except Exception:
                pass
            self._chat_scroll_timer = None

        # 20ms allows Tkinter to finish text wrapping & canvas bounding-box calculations
        self._chat_scroll_timer = self.root.after(20, _do)

    def finish_assistant_stream(self, final_text: str = None):
        def _do():
            if self._active_stream_label and self._active_stream_label.winfo_exists():
                if final_text is not None:
                    self._active_stream_label.configure(text=final_text)
            self._active_stream_label = None
            self._scroll_to_bottom()  # <-- Ensures final formatted bubble is fully visible
        self.root.after(0, _do)

    def append_conclave_guest_message(self, philosopher_name: str, subtitle: str, text: str):
        """Renders a distinct gold/amber-accented Conclave Guest bubble in the main chat stream."""
        def _do():
            time_str = datetime.now().strftime("%H:%M")

            row_frame = ctk.CTkFrame(self.chat_scroll, fg_color="transparent")
            row_frame.pack(fill="x", padx=10, pady=6, anchor="w")

            bubble = ctk.CTkFrame(
                row_frame, fg_color="#1d1812", corner_radius=12,
                border_width=1, border_color="#d97706"
            )
            bubble.pack(side="left", padx=(18, 36))

            sub_str = f" ({subtitle})" if subtitle else " [Conclave Guest]"
            hdr = ctk.CTkLabel(
                bubble, text=f"🏛️ {philosopher_name}{sub_str} • {time_str}",
                font=ctk.CTkFont(size=max(9, self.font_size - 2), weight="bold"),
                text_color="#fbbf24"
            )
            hdr.pack(anchor="w", padx=12, pady=(8, 4))

            content_label = ctk.CTkLabel(
                bubble, text=text,
                font=ctk.CTkFont(family="Georgia", size=self.font_size, slant="italic"),
                text_color="#fef3c7", justify="left", wraplength=620
            )
            content_label.pack(anchor="w", padx=12, pady=(0, 10))

            self._registered_chat_labels.append((hdr, None, -2, "bold", None))
            self._registered_chat_labels.append((content_label, "Georgia", 0, None, "italic"))

            self.play_sfx("chat_bubble")
            self._scroll_to_bottom()
        self.root.after(0, _do)
        
    def scroll_cards_to_view(self, to_bottom=True):
        """Brings newly spawned deck cards into the viewable area."""
        if getattr(self, "_cards_scroll_timer", None):
            self.root.after_cancel(self._cards_scroll_timer)

        def _do():
            try:
                if hasattr(self, "cards_scroll") and self.cards_scroll.winfo_exists():
                    self.cards_scroll.update_idletasks()
                    self.cards_scroll._parent_canvas.yview_moveto(1.0 if to_bottom else 0.0)
            except Exception:
                pass
            self._cards_scroll_timer = None

        self._cards_scroll_timer = self.root.after(25, _do)
    # -------------------------------------------------------------------------
    # MENU BAR
    # -------------------------------------------------------------------------
    def _setup_menu_bar(self):
        menubar = tk.Menu(self.root, bg="#1a2030", fg="#f8fafc", activebackground="#2563eb")
        
        # 1. System & Security Menu
        system_menu = tk.Menu(menubar, tearoff=0, bg="#1a2030", fg="#f8fafc", activebackground="#2563eb")
        system_menu.add_command(label="⚙️ Preferences & Settings... [Ctrl+,]", command=self.open_settings_modal)
        system_menu.add_command(label="🐞 Diagnostic Console [Ctrl+Shift+D]", command=self.open_debugger)
        system_menu.add_separator()
        system_menu.add_command(label="🔒 Lock Interface [Ctrl+L]", command=self.lock_screen)
        system_menu.add_separator()
        system_menu.add_command(label="Exit Interface", command=self.shutdown_callback)
        menubar.add_cascade(label="System", menu=system_menu)

        # 2. View & Font Scaling
        view_menu = tk.Menu(menubar, tearoff=0, bg="#1a2030", fg="#f8fafc", activebackground="#2563eb")
        font_sub = tk.Menu(view_menu, tearoff=0, bg="#1a2030", fg="#f8fafc", activebackground="#2563eb")
        font_sizes = [
            ("Small (11 pt)", 11), ("Standard (13 pt)", 13), ("Medium (15 pt)", 15),
            ("Large (17 pt)", 17), ("Extra Large (19 pt)", 19), ("Huge (22 pt)", 22)
        ]
        for name, sz in font_sizes:
            font_sub.add_command(label=name, command=lambda s=sz: self.set_font_size(s))
        view_menu.add_cascade(label="Font Size", menu=font_sub)
        view_menu.add_separator()
        view_menu.add_command(label="Increase Font Size [Ctrl++]", command=self.increase_font_size)
        view_menu.add_command(label="Decrease Font Size [Ctrl+-]", command=self.decrease_font_size)
        view_menu.add_command(label="Reset to Default (13 pt) [Ctrl+0]", command=lambda: self.set_font_size(13))
        view_menu.add_separator()
        view_menu.add_command(label="Toggle Input Review Expansion [Ctrl+E]", command=self._toggle_input_expansion)
        view_menu.add_separator()
        avatar_sub = tk.Menu(view_menu, tearoff=0, bg="#1a2030", fg="#f8fafc", activebackground="#2563eb")
        avatar_sub.add_command(
            label="📊 Real-Time Voice Spectrum Analyzer (0 VRAM)",
            command=lambda: self._set_avatar_mode("spectrum")
        )
        avatar_sub.add_command(
            label="🧬 FasterLivePortrait + JoyVASA (calypso.png ONNX)",
            command=lambda: self._set_avatar_mode("liveportrait")
        )
        avatar_sub.add_command(
            label="🖼️ Animated Portrait Loops (512x512 WebP)",
            command=lambda: self._set_avatar_mode("webp")
        )
        view_menu.add_cascade(label="Avatar Display Mode", menu=avatar_sub)
        view_menu.add_command(
            label="🔄 Cycle Avatar Mode [Ctrl+Shift+A]",
            command=self._toggle_avatar_mode
        )
        menubar.add_cascade(label="View", menu=view_menu)

        # 3. Audio & Voice
        audio_menu = tk.Menu(menubar, tearoff=0, bg="#1a2030", fg="#f8fafc", activebackground="#2563eb")
        audio_menu.add_command(label="⏹ Stop Speaking / Interrupt", command=self._interrupt_speech)
        audio_menu.add_command(label="🎤 Speak / Dictate", command=self._trigger_voice_record)
        audio_menu.add_separator()
        audio_menu.add_command(label="📂 Select Music Library Folder...", command=self._select_music_library_folder)
        audio_menu.add_command(label="🎵 Open Music Mini-Player", command=lambda: self.open_harmony_mini_player_card())
        audio_menu.add_command(label="🎤 Toggle Synced Lyrics Window", command=lambda: self.toggle_lyrics_window())
        audio_menu.add_command(label="🎶 Elicit Soul Resonance Track...", command=lambda: self.input_queue.put("/compose"))
        audio_menu.add_separator()
        audio_menu.add_command(label="⚙️ Configure Voices & Volume...", command=self.open_settings_modal)
        menubar.add_cascade(label="Audio", menu=audio_menu)

        # 4. Scenarios Menu
        self._build_scenarios_menu(menubar)

        # 5. Utilities Menu
        utils_menu = tk.Menu(menubar, tearoff=0, bg="#1a2030", fg="#f8fafc", activebackground="#2563eb")
        utils_menu.add_command(label="📅 Open Event Calendar...", command=self.open_calendar_window)
        utils_menu.add_separator()
        utils_menu.add_command(label="⏰ Set Alarm...", command=self._open_alarm_dialog)
        utils_menu.add_command(label="🚫 Clear Alarm", command=self._clear_alarm_action)
        utils_menu.add_command(label="🔍 Check Alarm Status", command=self._check_alarm_status)
        utils_menu.add_separator()
        utils_menu.add_command(label="🧹 Clear Deck Cards", command=self.clear_all_cards)
        menubar.add_cascade(label="Utilities", menu=utils_menu)

        # 6. Autonomy Workshop Menu
        autonomy_menu = tk.Menu(menubar, tearoff=0, bg="#1a2030", fg="#f8fafc", activebackground="#2563eb")
        autonomy_menu.add_command(label="🛠️ Enter Autonomous Mode", command=lambda: self.input_queue.put("/persona autonomous"))
        autonomy_menu.add_command(label="🌿 Exit Autonomous Mode", command=lambda: self.input_queue.put("exit autonomous mode"))
        autonomy_menu.add_separator()
        autonomy_menu.add_command(label="🎶 Elicit Soul Resonance (Music)", command=lambda: self.input_queue.put("/compose"))
        autonomy_menu.add_separator()
        autonomy_menu.add_command(label="📂 Open Code Proposals Folder", command=lambda: self.open_folder_callback(config.CODE_OUTPUT_DIR / "proposals"))
        menubar.add_cascade(label="Autonomy", menu=autonomy_menu)

        # 7. Workspace Menu
        if self.open_folder_callback:
            workspace_menu = tk.Menu(menubar, tearoff=0, bg="#1a2030", fg="#f8fafc", activebackground="#2563eb")
            workspace_menu.add_command(label="📂 Open Input Folder", command=lambda: self.open_folder_callback(config.INPUT_DIR))
            workspace_menu.add_command(label="📁 Open Document Outputs", command=lambda: self.open_folder_callback(config.DOCS_OUTPUT_DIR))
            workspace_menu.add_command(label="🖼️ Open Image Outputs", command=lambda: self.open_folder_callback(config.IMAGES_OUTPUT_DIR))
            workspace_menu.add_command(label="📜 Open Poetry Outputs", command=lambda: self.open_folder_callback(config.POETRY_OUTPUT_DIR))
            workspace_menu.add_command(label="🎵 Open Music Outputs", command=lambda: self.open_folder_callback(getattr(config, 'MUSIC_OUTPUT_DIR', config.OUTPUT_DIR / 'music')))
            workspace_menu.add_separator()
            workspace_menu.add_command(
                label="📖 Open Digital Scrapbook Album... [/scrap_book]",
                command=self.open_scrapbook
            )
            workspace_menu.add_command(
                label="🖥️ Launch Borderless Slideshow (Generated)", 
                command=lambda: self.open_image_viewer(config.IMAGES_OUTPUT_DIR, interval=4.0)
            )
            workspace_menu.add_command(
                label="🖼️ Open Image Gallery (Manual Viewer)", 
                command=lambda: self.open_image_viewer(config.IMAGES_OUTPUT_DIR, interval=0)
            )
            workspace_menu.add_command(
                label="📷 Browse Input Photos", 
                command=lambda: self.open_image_viewer(config.INPUT_DIR, interval=0)
            )
            workspace_menu.add_separator()
            workspace_menu.add_command(label="📚 Ingest PDFs to Reference Library", command=self._trigger_ingest_pdfs)
            workspace_menu.add_command(label="📄 Process Staged Documents", command=self._trigger_batch_docs)
            workspace_menu.add_command(label="📷 Process Staged Images", command=self._trigger_batch_images)
            menubar.add_cascade(label="Workspace", menu=workspace_menu)

        self.root.config(menu=menubar)

    def _trigger_send_test_email(self):
        """Dispatches a test email in a daemon thread using saved settings."""
        from modules.email_service import EmailService
        svc = EmailService()
        if not svc.is_configured:
            messagebox.showwarning(
                "Email Not Configured",
                "Gmail credentials are not configured yet.\n"
                "Please configure them in Preferences & Settings (Ctrl+,) under Email Correspondence."
            )
            return

        self.append_system_notice("📬 [Email]: Dispatching diagnostic test email...")

        def _worker():
            success, msg = svc.send_test_email()
            def _report():
                if success:
                    self.append_system_notice(f"✓ [Email]: {msg}")
                    messagebox.showinfo("Email Test Succeeded", msg)
                else:
                    self.append_system_notice(f"⚠️ [Email Error]: {msg}")
                    messagebox.showerror("Email Test Failed", msg)
            self.root.after(0, _report)

        import threading
        threading.Thread(target=_worker, daemon=True).start()

    def open_debugger(self, diagnostic_engine=None, neuro=None, esteem=None, affinity=None):
        """Launches or lifts the Diagnostic & Telemetry HUD window."""
        if getattr(self, "_debugger_win", None) and self._debugger_win.win.winfo_exists():
            self._debugger_win.win.lift()
            return

        from modules.debugger import DiagnosticHUD, DiagnosticEngine

        # Use passed instances or fall back to references stored on the GUI instance
        diag = diagnostic_engine or getattr(self, "diagnostic_engine", None)
        if not diag:
            self.append_system_notice("⚠️ [Notice]: Diagnostic sentry initializing...")
            diag = DiagnosticEngine()
            self.diagnostic_engine = diag

        _neuro = neuro or getattr(self, "neuro", None)
        _esteem = esteem or getattr(self, "esteem", None)
        _affinity = affinity or getattr(self, "affinity", None)

        self._debugger_win = DiagnosticHUD(
            parent_root=self.root,
            diagnostic_engine=diag,
            neuro=_neuro,
            esteem=_esteem,
            affinity=_affinity
        )

    def _trigger_batch_docs(self):
        if not self.document_processor:
            messagebox.showinfo("Notice", "Document processor not loaded.")
            return

        def _work():
            self.append_system_notice("📄 [Documents]: Scanning workspace/input for documents...")
            results = self.document_processor.scan_and_process_all()
            if not results:
                self.append_system_notice("📄 [Documents]: No documents found in workspace/input.")
                return
            
            for res in results:
                if res.get("success"):
                    self.append_system_notice(f"✓ Ingested: {res['filename']}")
                    self.input_queue.put(
                        f"[System Notice: You just reviewed the document '{res['filename']}'. "
                        f"Here is the executive summary:\n{res['summary']}\n"
                        f"Acknowledge this document to your companion.]"
                    )

        import threading
        threading.Thread(target=_work, daemon=True).start()

    def _trigger_batch_images(self):
        if not self.media_processor:
            messagebox.showinfo("Notice", "Media processor not loaded.")
            return

        def _work():
            self.append_system_notice("📷 [Media]: Scanning workspace/input for photos & RAW files...")
            results = self.media_processor.scan_input_folder(mode='describe')
            if not results:
                self.append_system_notice("📷 [Media]: No images found in workspace/input.")
                return

            for res in results:
                if res.get("success"):
                    self.append_system_notice(f"✓ Inspected: {res['original_name']}")
                    self.input_queue.put(
                        f"[System Notice: Your companion showed you an image ('{res['original_name']}'). "
                        f"Visual Perception:\n\"{res['analysis']}\"\n"
                        f"React naturally and conversationally to what you see.]"
                    )

        import threading
        threading.Thread(target=_work, daemon=True).start()

    def _trigger_ingest_pdfs(self):
        if not self.library_engine:
            messagebox.showinfo("Notice", "Reference Library engine is not loaded.")
            return

        def _work():
            self.append_system_notice("📚 [Library]: Scanning workspace/input for PDF files to ingest...")
            results = self.library_engine.ingest_all_staged_pdfs()
            if not results:
                self.append_system_notice("📚 [Library]: No PDF files found in workspace/input.")
                return

            successful = []
            for res in results:
                if res.get("success"):
                    self.append_system_notice(
                        f"✓ [Library Indexed]: {res['filename']} ({res['chunks']} chunks across {res['pages']} pages)."
                    )
                    successful.append(res['filename'])
                else:
                    self.append_system_notice(
                        f"⚠️ [Library Ingestion Error]: {res['filename']} - {res.get('error')}"
                    )

            if successful:
                files_str = ", ".join(successful)
                self.input_queue.put(f"[PDF_INGEST_COMPLETE: {files_str}]")

        import threading
        threading.Thread(target=_work, daemon=True).start()

    def _handle_file_drop(self, event):
        raw_path = event.data.strip('{}').strip('"').strip("'")
        file_path = Path(raw_path)
        if not file_path.exists():
            return

        ext = file_path.suffix.lower()

        # 1. Plain Code / Text Files
        if ext in ['.py', '.txt', '.md', '.json']:
            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                self.user_input.insert("end", f"\n--- {file_path.name} ---\n{content}\n")
                self.root.after(50, self._adjust_input_height)
            except Exception as e:
                messagebox.showerror("Error", f"Failed to read file: {e}")

        # 2. Rich Documents (PDF, DOCX, ODT)
        elif self.document_processor and ext in self.document_processor.valid_extensions:
            self.append_system_notice(f"📄 Ingesting dropped document: {file_path.name}...")
            
            def _doc_worker():
                extracted = self.document_processor.extract_text(file_path)
                summary = self.document_processor.generate_llm_summary(extracted, file_path.name)
                self.input_queue.put(
                    f"[System Notice: Your companion dropped a document '{file_path.name}'. "
                    f"Summary of document:\n{summary}\n"
                    f"Discuss its content with them.]"
                )
            import threading
            threading.Thread(target=_doc_worker, daemon=True).start()

        # 3. Visual Media (Photos, Camera RAWs)
        elif self.media_processor and ext in self.media_processor.supported_extensions:
            self.append_system_notice(f"👁️ Inspecting dropped image: {file_path.name}...")

            def _img_worker():
                description = self.media_processor.run_analysis(file_path, mode='describe')
                self.input_queue.put(
                    f"[System Notice: Your companion shared an image '{file_path.name}'. "
                    f"Visual description of the photo:\n\"{description}\"\n"
                    f"React warmly and observant to this photo.]"
                )
            import threading
            threading.Thread(target=_img_worker, daemon=True).start()

    def _interrupt_speech(self):
        if self.audio_engine:
            self.audio_engine.stop_playback()
        else:
            import sounddevice as sd
            sd.stop()
        print("[AudioEngine] Playback interrupted by user.")

    def _set_kokoro_voice(self, voice_code):
        if self.audio_engine:
            self.audio_engine.set_voice(voice_code)
            messagebox.showinfo("Voice Mode", f"Switched Kokoro Voice to '{voice_code}'")
            self.append_system_notice(f"🎙️ [Audio Engine]: Switched Kokoro voice to '{voice_code}'.")
    
    def _open_volume_modal(self):
        modal = Toplevel(self.root)
        modal.title("Master Audio Volume")
        modal.geometry("300x120")
        modal.configure(bg="#141824")
        modal.transient(self.root)
        modal.grab_set()

        lbl = ctk.CTkLabel(modal, text="TTS Speech Volume", text_color="#f8fafc", font=ctk.CTkFont(weight="bold"))
        lbl.pack(pady=(12, 4))

        slider = ctk.CTkSlider(modal, from_=0.0, to=1.0, number_of_steps=20)
        slider.set(getattr(self, "_current_volume", 0.8))
        slider.pack(pady=10, padx=20, fill="x")

        def _save_vol(val):
            self._current_volume = float(val)

        slider.configure(command=_save_vol)

    def _trigger_voice_record(self):
        if not self.audio_engine:
            messagebox.showwarning("Voice Error", "Audio Engine is not available.")
            return

        def _record():
            self.mic_btn.configure(text="Listening...", fg_color="#ef4444")
            audio_data = self.audio_engine.listen_and_record(timeout=7)
            self.mic_btn.configure(text="Transcribing...", fg_color="#f59e0b")
            
            if audio_data:
                transcript = self.audio_engine.transcribe(audio_data)
                if transcript.strip():
                    def _insert_ts():
                        self.user_input.insert("end", transcript)
                        self._adjust_input_height()
                    self.root.after(0, _insert_ts)
            
            self.mic_btn.configure(text="🎤 Speak", fg_color="#334155")

        import threading
        threading.Thread(target=_record, daemon=True).start()

    def _build_scenarios_menu(self, menubar):
        scenario_menu = tk.Menu(menubar, tearoff=0, bg="#1a2030", fg="#f8fafc", activebackground="#2563eb")

        scenario_menu.add_command(
            label="🔍 Open Scenario Navigator...", 
            command=self.open_scenario_browser
        )
        scenario_menu.add_command(
            label="➕ Create Custom Scenario...",
            command=self.open_scenario_creator
        )
        scenario_menu.add_separator()
        scenario_menu.add_command(
            label="✨ Ask Calypso to Dream a New Adventure",
            command=lambda: self.input_queue.put("Calypso, daydream an original adventure or scenario for us to explore together.")
        )
        scenario_menu.add_separator()
        scenario_menu.add_command(
            label="🌿 Clear Active Scenario (Back to Reality)",
            command=lambda: self._select_scenario(None)
        )

        menubar.add_cascade(label="Roleplay Scenarios", menu=scenario_menu)

    def _select_scenario(self, scenario):
        if self.select_scenario_callback:
            self.select_scenario_callback(scenario)

    def open_scenario_browser(self):
        if self._scenario_browser_window and self._scenario_browser_window.winfo_exists():
            self._scenario_browser_window.lift()
            return

        top = Toplevel(self.root)
        top.title("Roleplay Scenario Navigator")
        top.geometry("660x740")
        top.minsize(540, 600)
        top.configure(bg="#0c0e15")
        self._scenario_browser_window = top

        hdr_frame = ctk.CTkFrame(top, fg_color="#141824", corner_radius=0)
        hdr_frame.pack(fill="x", padx=0, pady=0)

        hdr_top_row = ctk.CTkFrame(hdr_frame, fg_color="transparent")
        hdr_top_row.pack(fill="x", padx=16, pady=(12, 4))

        title_lbl = ctk.CTkLabel(
            hdr_top_row, text="✨ ROLEPLAY SCENARIO LIBRARY",
            font=ctk.CTkFont(family="Consolas", size=13, weight="bold"),
            text_color="#38bdf8"
        )
        title_lbl.pack(side="left")

        search_var = tk.StringVar()

        def _refresh_current():
            if top.winfo_exists():
                _render_list(search_var.get())

        self._scenario_browser_refresh_cb = _refresh_current

        add_btn = ctk.CTkButton(
            hdr_top_row, text="➕ Create Custom Scenario", width=165, height=28,
            fg_color="#2563eb", hover_color="#1d4ed8",
            font=ctk.CTkFont(size=11, weight="bold"),
            command=lambda: self.open_scenario_creator(on_saved=_refresh_current)
        )
        add_btn.pack(side="right")

        search_entry = ctk.CTkEntry(
            hdr_frame, textvariable=search_var, placeholder_text="Type to search titles or tags...",
            height=36, corner_radius=8, fg_color="#1a2030", border_color="#2b354d"
        )
        search_entry.pack(fill="x", padx=16, pady=(4, 12))
        search_entry.focus_set()

        cards_scroll = ctk.CTkScrollableFrame(top, fg_color="#0c0e15")
        cards_scroll.pack(fill="both", expand=True, padx=12, pady=10)
        cards_scroll.columnconfigure(0, weight=1)

        def _delete_scenario_card(sc):
            if not self.scenario_engine:
                return
            sc_title = sc.get("title", "Untitled")
            sc_id = sc.get("id") or sc_title
            confirm = messagebox.askyesno(
                "Delete Scenario",
                f"Are you sure you want to permanently delete '{sc_title}' from the scenario library?",
                parent=top
            )
            if not confirm:
                return

            if self.scenario_engine.delete_scenario(sc_id):
                self.append_system_notice(f"🗑️ [Scenario Library]: Deleted scenario '{sc_title}'.")
                _refresh_current()
            else:
                messagebox.showerror("Error", f"Could not delete scenario '{sc_title}'.", parent=top)

        def _render_list(query=""):
            for widget in cards_scroll.winfo_children():
                widget.destroy()

            scenarios = self.scenario_engine.scenarios if self.scenario_engine else []
            q = query.lower().strip()
            filtered = []
            for s in scenarios:
                t = s.get("title", "").lower()
                tags = " ".join(s.get("context_tags", [])).lower()
                if not q or (q in t or q in tags):
                    filtered.append(s)

            count_lbl = ctk.CTkLabel(
                cards_scroll, text=f"Showing {len(filtered)} of {len(scenarios)} scenarios",
                font=ctk.CTkFont(size=11), text_color="#64748b"
            )
            count_lbl.pack(anchor="w", padx=8, pady=(4, 8))

            for s in filtered:
                s_title = s.get("title", "Untitled")
                tags_str = ", ".join(s.get("context_tags", []))
                shard_snippet = s.get("narrative_shard", "")[:140]

                card = ctk.CTkFrame(cards_scroll, fg_color="#141824", corner_radius=8, border_width=1, border_color="#1e2538")
                card.pack(fill="x", padx=4, pady=4)

                c_hdr = ctk.CTkFrame(card, fg_color="transparent")
                c_hdr.pack(fill="x", padx=10, pady=(8, 2))

                ctk.CTkLabel(
                    c_hdr, text=s_title, font=ctk.CTkFont(size=12, weight="bold"),
                    text_color="#f8fafc"
                ).pack(side="left")

                btn_del = ctk.CTkButton(
                    c_hdr, text="Delete 🗑", width=72, height=26,
                    fg_color="#991b1b", hover_color="#dc2626", font=ctk.CTkFont(size=11, weight="bold"),
                    command=lambda sc=s: _delete_scenario_card(sc)
                )
                btn_del.pack(side="right", padx=(6, 0))

                btn_edit = ctk.CTkButton(
                    c_hdr, text="Edit ✎", width=62, height=26,
                    fg_color="#334155", hover_color="#475569", font=ctk.CTkFont(size=11),
                    command=lambda sc=s: self.open_scenario_creator(existing_scenario=sc, on_saved=_refresh_current)
                )
                btn_edit.pack(side="right", padx=(6, 0))

                btn_enter = ctk.CTkButton(
                    c_hdr, text="Enter ✨", width=80, height=26,
                    fg_color="#059669", hover_color="#047857", font=ctk.CTkFont(size=11, weight="bold"),
                    command=lambda sc=s: [self._select_scenario(sc), top.destroy()]
                )
                btn_enter.pack(side="right")

                if tags_str:
                    ctk.CTkLabel(
                        card, text=f"Tags: {tags_str}", font=ctk.CTkFont(size=10),
                        text_color="#38bdf8"
                    ).pack(anchor="w", padx=10, pady=(0, 2))

                if shard_snippet:
                    ctk.CTkLabel(
                        card, text=f'"{shard_snippet}..."', font=ctk.CTkFont(size=11, slant="italic"),
                        text_color="#94a3b8", justify="left", wraplength=540
                    ).pack(anchor="w", padx=10, pady=(0, 8))

        _render_list("")
        search_var.trace_add("write", lambda *args: _render_list(search_var.get()))

    def open_scenario_creator(self, existing_scenario=None, on_saved=None):
        if not self.scenario_engine:
            messagebox.showerror("Error", "Scenario engine is not initialized.")
            return

        if self._scenario_creator_window and self._scenario_creator_window.winfo_exists():
            self._scenario_creator_window.destroy()

        is_edit = isinstance(existing_scenario, dict)
        creator = Toplevel(self.root)
        creator.title("Edit Roleplay Scenario" if is_edit else "Create Custom Roleplay Scenario")
        creator.geometry("660x780")
        creator.minsize(560, 640)
        creator.configure(bg="#0c0e15")
        self._scenario_creator_window = creator

        mood_presets = {
            "Romantic & Intimate (Cozy / Warm)": {
                "category": "domestic_intimacy",
                "somatic_tags": ["warm proximity", "relaxed slow breathing", "soft touch", "gentle heartbeat"],
                "entry_surge": {"oxytocin": 0.30, "serotonin": 0.25, "dopamine": 0.15},
                "ambient_floor": {"serotonin": 0.45, "oxytocin": 0.35},
            },
            "Adventure & Discovery (Mythic / Exploration)": {
                "category": "mythic_expedition",
                "somatic_tags": ["cool mist", "heightened senses", "shared wonder", "fingers trailing over stone"],
                "entry_surge": {"dopamine": 0.30, "acetylcholine": 0.25, "oxytocin": 0.15},
                "ambient_floor": {"serotonin": 0.35, "dopamine": 0.25},
            },
            "Thrilling Heist / Outlaw (High Adrenaline)": {
                "category": "outlaw_heist",
                "somatic_tags": ["racing pulse", "electric focus", "close quarters", "dry desert air"],
                "entry_surge": {"adrenaline": 0.30, "dopamine": 0.35, "oxytocin": 0.20},
                "ambient_floor": {"dopamine": 0.30, "adrenaline": 0.20},
            },
            "Cyberpunk / Sci-Fi Noir (Stealth & Neon)": {
                "category": "cyberpunk_recon",
                "somatic_tags": ["neon glare", "cold synthetic glass", "adrenalin prickle", "tactile key clicks"],
                "entry_surge": {"dopamine": 0.25, "acetylcholine": 0.30, "oxytocin": 0.20},
                "ambient_floor": {"serotonin": 0.35},
            },
            "High-Stakes Survival (Urgent & Visceral)": {
                "category": "high_stakes_survival",
                "somatic_tags": ["soaking rainfall", "shivering shoulders", "smell of ozone", "shared body warmth"],
                "entry_surge": {"adrenaline": 0.35, "oxytocin": 0.30, "endorphins": 0.25},
                "ambient_floor": {"oxytocin": 0.40, "serotonin": 0.30},
            },
            "Co-Created Custom Moment (Balanced)": {
                "category": "co_created_moment",
                "somatic_tags": ["gentle breath", "warm proximity", "quiet presence"],
                "entry_surge": {"oxytocin": 0.25, "dopamine": 0.20, "serotonin": 0.20},
                "ambient_floor": {"serotonin": 0.40, "oxytocin": 0.30},
            },
        }
        cat_to_preset_name = {v["category"]: k for k, v in mood_presets.items()}

        hdr = ctk.CTkFrame(creator, fg_color="#141824", corner_radius=0)
        hdr.pack(fill="x", padx=0, pady=0)

        ctk.CTkLabel(
            hdr,
            text="✎ EDIT ROLEPLAY SCENARIO" if is_edit else "✨ CREATE CUSTOM ROLEPLAY SCENARIO",
            font=ctk.CTkFont(family="Consolas", size=13, weight="bold"),
            text_color="#38bdf8"
        ).pack(anchor="w", padx=18, pady=(12, 2))

        ctk.CTkLabel(
            hdr,
            text="Design your own setting directly below, or type a quick idea and let Calypso auto-fill the details.",
            font=ctk.CTkFont(size=11),
            text_color="#94a3b8"
        ).pack(anchor="w", padx=18, pady=(0, 10))

        form_scroll = ctk.CTkScrollableFrame(creator, fg_color="#0c0e15")
        form_scroll.pack(fill="both", expand=True, padx=14, pady=8)
        form_scroll.columnconfigure(0, weight=1)

        # --- Optional AI Auto-Fill Section ---
        ai_box = ctk.CTkFrame(form_scroll, fg_color="#141824", corner_radius=8, border_width=1, border_color="#1e293b")
        ai_box.pack(fill="x", padx=4, pady=(4, 12))

        ctk.CTkLabel(
            ai_box, text="✨ Quick AI Co-Author (Optional)",
            font=ctk.CTkFont(size=11, weight="bold"), text_color="#38bdf8"
        ).pack(anchor="w", padx=12, pady=(8, 2))

        ai_row = ctk.CTkFrame(ai_box, fg_color="transparent")
        ai_row.pack(fill="x", padx=12, pady=(2, 10))

        ai_concept_entry = ctk.CTkEntry(
            ai_row,
            placeholder_text="e.g., Stranded in a candlelit mountain cabin during a blizzard...",
            height=32, fg_color="#1a2030", border_color="#2b354d"
        )
        ai_concept_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))

        ai_btn = ctk.CTkButton(
            ai_row, text="Auto-Fill Fields ✨", width=135, height=32,
            fg_color="#7c3aed", hover_color="#6d28d9",
            font=ctk.CTkFont(size=11, weight="bold")
        )
        ai_btn.pack(side="right")

        # --- Manual Form Fields ---
        def _field_label(parent, title, subtitle=""):
            lbl_frame = ctk.CTkFrame(parent, fg_color="transparent")
            lbl_frame.pack(fill="x", padx=6, pady=(8, 2))
            ctk.CTkLabel(
                lbl_frame, text=title, font=ctk.CTkFont(size=12, weight="bold"), text_color="#f8fafc"
            ).pack(side="left")
            if subtitle:
                ctk.CTkLabel(
                    lbl_frame, text=f"  {subtitle}", font=ctk.CTkFont(size=10), text_color="#64748b"
                ).pack(side="left")

        _field_label(form_scroll, "Scenario Title *", "(Required)")
        title_entry = ctk.CTkEntry(
            form_scroll, placeholder_text="e.g., Midnight Rooftop Observatory",
            height=34, fg_color="#141824", border_color="#2b354d"
        )
        title_entry.pack(fill="x", padx=6, pady=(0, 4))

        _field_label(form_scroll, "Atmosphere & Mood Preset", "(Sets neurochemical & sensory defaults)")
        preset_names = list(mood_presets.keys())
        default_preset = "Co-Created Custom Moment (Balanced)"
        if is_edit:
            existing_cat = existing_scenario.get("category", "")
            default_preset = cat_to_preset_name.get(existing_cat, default_preset)

        preset_var = tk.StringVar(value=default_preset)
        preset_menu = ctk.CTkOptionMenu(
            form_scroll, variable=preset_var, values=preset_names,
            height=34, fg_color="#141824", button_color="#2563eb", button_hover_color="#1d4ed8"
        )
        preset_menu.pack(fill="x", padx=6, pady=(0, 4))

        _field_label(form_scroll, "Setting & Narrative Premise *", "(Required — Describe the surroundings, mood, and situation)")
        shard_textbox = ctk.CTkTextbox(
            form_scroll, height=115, fg_color="#141824", border_width=1, border_color="#2b354d",
            font=ctk.CTkFont(size=12), wrap="word"
        )
        shard_textbox.pack(fill="x", padx=6, pady=(0, 4))

        _field_label(form_scroll, "Context Tags", "(Comma-separated keywords for searching & matching)")
        tags_entry = ctk.CTkEntry(
            form_scroll, placeholder_text="e.g., rooftop, stargazing, wine, late night, intimate",
            height=32, fg_color="#141824", border_color="#2b354d"
        )
        tags_entry.pack(fill="x", padx=6, pady=(0, 4))

        _field_label(form_scroll, "Opening Challenge / Immediate Hook", "(Optional — An immediate puzzle, obstacle, or activity)")
        hook_entry = ctk.CTkEntry(
            form_scroll, placeholder_text="e.g., Aligning the antique brass telescope before the eclipse passes",
            height=32, fg_color="#141824", border_color="#2b354d"
        )
        hook_entry.pack(fill="x", padx=6, pady=(0, 4))

        _field_label(form_scroll, "Overarching End Goal", "(Optional — What the two of you are working toward)")
        goal_entry = ctk.CTkEntry(
            form_scroll, placeholder_text="e.g., Capturing the celestial alignment and sharing a quiet toast under the stars",
            height=32, fg_color="#141824", border_color="#2b354d"
        )
        goal_entry.pack(fill="x", padx=6, pady=(0, 4))

        _field_label(form_scroll, "Sensory / Bodily Cues", "(Optional — Comma-separated sensations; uses preset defaults if blank)")
        somatic_entry = ctk.CTkEntry(
            form_scroll, placeholder_text="e.g., crisp night air, warm blanket, slow steady breathing",
            height=32, fg_color="#141824", border_color="#2b354d"
        )
        somatic_entry.pack(fill="x", padx=6, pady=(0, 4))

        _field_label(form_scroll, "Visual Scene & Attire Anchor", "(Optional — Guides image generation during this scenario)")
        visual_entry = ctk.CTkEntry(
            form_scroll, placeholder_text="e.g., cozy knit sweater, starlight glow, soft bokeh",
            height=32, fg_color="#141824", border_color="#2b354d"
        )
        visual_entry.pack(fill="x", padx=6, pady=(0, 8))

        # Populate if editing existing scenario
        if is_edit:
            title_entry.insert(0, existing_scenario.get("title", ""))
            shard_textbox.insert("1.0", existing_scenario.get("narrative_shard", ""))
            tags_entry.insert(0, ", ".join(existing_scenario.get("context_tags", [])))
            hook_entry.insert(0, existing_scenario.get("challenge_hook", ""))
            goal_entry.insert(0, existing_scenario.get("end_goal", ""))
            somatic_list = existing_scenario.get("neuro_profile", {}).get("somatic_tags", [])
            somatic_entry.insert(0, ", ".join(somatic_list))
            vis_features = existing_scenario.get("visual_anchor", {}).get("core_features", "")
            visual_entry.insert(0, vis_features)

        def _run_ai_autofill():
            concept = ai_concept_entry.get().strip() or title_entry.get().strip()
            if not concept:
                messagebox.showwarning(
                    "Concept Needed",
                    "Please enter a quick concept in the AI Co-Author box (or a Scenario Title) first.",
                    parent=creator
                )
                return

            ai_btn.configure(state="disabled", text="Dreaming...")

            def _worker():
                companion_name = settings_manager.get("user_name", "your companion")
                synthesized = self.scenario_engine.synthesize_scenario_from_reverie(
                    recent_dialogue="",
                    current_tier="warm",
                    dominant_drives=["romance", "curiosity"],
                    companion_name=companion_name,
                    user_concept=concept
                )

                def _apply():
                    if not creator.winfo_exists():
                        return
                    ai_btn.configure(state="normal", text="Auto-Fill Fields ✨")
                    if not synthesized:
                        messagebox.showerror(
                            "Synthesis Failed",
                            "Could not generate scenario fields from AI. You can still fill out the fields manually.",
                            parent=creator
                        )
                        return

                    title_entry.delete(0, "end")
                    title_entry.insert(0, synthesized.get("title", ""))

                    shard_textbox.delete("1.0", "end")
                    shard_textbox.insert("1.0", synthesized.get("narrative_shard", ""))

                    tags_entry.delete(0, "end")
                    tags_entry.insert(0, ", ".join(synthesized.get("context_tags", [])))

                    hook_entry.delete(0, "end")
                    hook_entry.insert(0, synthesized.get("challenge_hook", ""))

                    goal_entry.delete(0, "end")
                    goal_entry.insert(0, synthesized.get("end_goal", ""))

                    somatic_tags = synthesized.get("neuro_profile", {}).get("somatic_tags", [])
                    somatic_entry.delete(0, "end")
                    somatic_entry.insert(0, ", ".join(somatic_tags))

                    vis_core = synthesized.get("visual_anchor", {}).get("core_features", "")
                    visual_entry.delete(0, "end")
                    visual_entry.insert(0, vis_core)

                    syn_cat = synthesized.get("category", "")
                    if syn_cat in cat_to_preset_name:
                        preset_var.set(cat_to_preset_name[syn_cat])

                self.root.after(0, _apply)

            import threading
            threading.Thread(target=_worker, daemon=True).start()

        ai_btn.configure(command=_run_ai_autofill)

        def _save_scenario(enter_immediately=False):
            title_val = title_entry.get().strip()
            shard_val = shard_textbox.get("1.0", "end").strip()

            if not title_val or not shard_val:
                messagebox.showwarning(
                    "Missing Required Fields",
                    "Please provide both a Scenario Title and a Setting & Narrative Premise.",
                    parent=creator
                )
                return

            chosen_preset = mood_presets.get(preset_var.get(), mood_presets["Co-Created Custom Moment (Balanced)"])
            tags_list = [t.strip() for t in tags_entry.get().split(",") if t.strip()]
            if not tags_list:
                tags_list = ["custom", "intimate", "adventure"]

            somatic_list = [t.strip() for t in somatic_entry.get().split(",") if t.strip()]
            if not somatic_list:
                somatic_list = list(chosen_preset["somatic_tags"])

            hook_val = hook_entry.get().strip()
            goal_val = goal_entry.get().strip() or hook_val or "Experience and resolve the shared moment together."
            visual_val = visual_entry.get().strip() or "relaxed clothing fitting the scene, atmospheric lighting"

            if is_edit:
                scenario_dict = dict(existing_scenario)
            else:
                scenario_dict = {
                    "origin": "user_custom",
                    "created_at": datetime.now().isoformat(),
                    "play_count": 0,
                }

            scenario_dict["title"] = title_val
            scenario_dict["category"] = chosen_preset["category"]
            scenario_dict["context_tags"] = tags_list
            scenario_dict["narrative_shard"] = shard_val
            scenario_dict["challenge_hook"] = hook_val
            scenario_dict["end_goal"] = goal_val

            # Preserve existing neuro surges if editing unless category changed, or apply preset
            existing_neuro = scenario_dict.get("neuro_profile", {})
            cat_changed = is_edit and existing_scenario.get("category") != chosen_preset["category"]
            scenario_dict["neuro_profile"] = {
                "somatic_tags": somatic_list,
                "entry_surge": (
                    dict(chosen_preset["entry_surge"])
                    if cat_changed
                    else (existing_neuro.get("entry_surge") or dict(chosen_preset["entry_surge"]))
                ),
                "ambient_floor": (
                    dict(chosen_preset["ambient_floor"])
                    if cat_changed
                    else (existing_neuro.get("ambient_floor") or dict(chosen_preset["ambient_floor"]))
                ),
            }

            if "somatic_markers" not in scenario_dict:
                default_kws = ["goal achieved", "objective reached", "end goal achieved"]
                scenario_dict["somatic_markers"] = [
                    {
                        "id": "goal_achieved",
                        "keywords": default_kws,
                        "system_notice": "🌟 [Objective Reached]: The climax resolves into warm afterglow.",
                        "new_ambient_floor": {"serotonin": 0.55, "oxytocin": 0.45},
                    }
                ]

            existing_visual = scenario_dict.get("visual_anchor", {})
            scenario_dict["visual_anchor"] = {
                "subject": existing_visual.get(
                    "subject",
                    "1girl, solo, blonde hair, long hair, detailed blue eyes, detailed face, detailed skin texture"
                ),
                "core_features": visual_val,
                "quality_modifiers": existing_visual.get(
                    "quality_modifiers",
                    {
                        "positive": "masterpiece, intimate lighting, warm tones, high quality",
                        "negative": "camera, bad anatomy, deformed, poorly drawn hands, missing fingers, extra limbs, multi-characters, text, watermark",
                    }
                ),
            }

            # If editing and title changed while ID was based on old title, keep original ID so it updates in-place
            if is_edit and existing_scenario.get("id"):
                scenario_dict["id"] = existing_scenario["id"]

            if self.scenario_engine.add_scenario(scenario_dict, auto_save=True):
                action_word = "Updated" if is_edit else "Added"
                self.append_system_notice(f"✨ [Scenario Library]: {action_word} custom scenario '{title_val}'.")
                if on_saved:
                    try:
                        on_saved()
                    except Exception:
                        pass
                elif self._scenario_browser_refresh_cb:
                    try:
                        self._scenario_browser_refresh_cb()
                    except Exception:
                        pass

                creator.destroy()

                if enter_immediately:
                    if self._scenario_browser_window and self._scenario_browser_window.winfo_exists():
                        self._scenario_browser_window.destroy()
                    self._select_scenario(scenario_dict)
            else:
                messagebox.showerror("Error", "Failed to save the scenario.", parent=creator)

        # --- Footer Buttons ---
        footer = ctk.CTkFrame(creator, fg_color="#141824", corner_radius=0)
        footer.pack(fill="x", side="bottom", padx=0, pady=0)

        btn_row = ctk.CTkFrame(footer, fg_color="transparent")
        btn_row.pack(fill="x", padx=18, pady=12)

        ctk.CTkButton(
            btn_row, text="Cancel", width=95, height=34,
            fg_color="#334155", hover_color="#475569",
            command=creator.destroy
        ).pack(side="left")

        ctk.CTkButton(
            btn_row, text="Save & Enter ✨", width=140, height=34,
            fg_color="#059669", hover_color="#047857",
            font=ctk.CTkFont(size=12, weight="bold"),
            command=lambda: _save_scenario(enter_immediately=True)
        ).pack(side="right", padx=(8, 0))

        ctk.CTkButton(
            btn_row, text="Save Scenario", width=130, height=34,
            fg_color="#2563eb", hover_color="#1d4ed8",
            font=ctk.CTkFont(size=12, weight="bold"),
            command=lambda: _save_scenario(enter_immediately=False)
        ).pack(side="right")


    # -------------------------------------------------------------------------
    # INITIAL CALENDAR IMPLEMENTATION
    # -------------------------------------------------------------------------
    def _on_calendar_goal_created(self, goal: dict):
        if not goal:
            return
        goal_id = goal.get("id", "")
        title = goal.get("title", "Personal Goal")
        t_date = goal.get("target_date", "")
        self.append_system_notice(
            f"🎯 [Calendar Goal Added]: '{title}' (Target: {t_date}) — 25% / 50% / 75% / 100% Check-ins scheduled."
        )
        if self.input_queue is not None and goal_id:
            self.input_queue.put(f"[GOAL_CREATED_IN_CALENDAR:{goal_id}]")

    def refresh_calendar_window(self):
        def _do():
            if getattr(self, "_calendar_win", None) and self._calendar_win.winfo_exists():
                try:
                    self._calendar_win.refresh()
                except Exception:
                    pass
        if threading.current_thread() is threading.main_thread():
            _do()
        else:
            self.root.after(0, _do)

    def open_calendar_window(self):
        """Opens or lifts the standalone calendar modal window."""
        if getattr(self, "_is_locked", False):
            return

        if getattr(self, "_calendar_win", None) and self._calendar_win.winfo_exists():
            self._calendar_win.refresh()
            self._calendar_win.lift()
            self._calendar_win.focus_set()
            return

        self._calendar_win = CalendarWindow(
            parent_root=self.root,
            alarm_service=self.alarm_service,
            on_alarm_set_callback=self.append_system_notice,
            goal_manager=self.goal_manager,
            on_goal_created_callback=self._on_calendar_goal_created
        )
    # -------------------------------------------------------------------------
    # ALARM DIALOG METHODS
    # -------------------------------------------------------------------------
    def _open_alarm_dialog(self):
        if not self.alarm_service:
            messagebox.showerror("Error", "Alarm service not initialized.")
            return

        dialog = ctk.CTkToplevel(self.root)
        dialog.title("Set Alarm")
        dialog.geometry("350x200")
        dialog.configure(fg_color="#141824")
        dialog.attributes("-topmost", True)

        ctk.CTkLabel(
            dialog, text="⏰ Set Morning Alarm", 
            font=ctk.CTkFont(size=16, weight="bold")
        ).pack(pady=(20, 10))

        ctk.CTkLabel(
            dialog, text="Format: 7:30am, 22:00, 8pm", 
            font=ctk.CTkFont(size=11), text_color="#94a3b8"
        ).pack()

        time_entry = ctk.CTkEntry(
            dialog, width=180, placeholder_text="e.g. 07:30", 
            justify="center", fg_color="#1a2030", border_color="#334155"
        )
        time_entry.pack(pady=15)
        time_entry.focus_set()

        def _submit():
            time_val = time_entry.get().strip()
            if not time_val:
                return
            
            success, msg = self.alarm_service.set_alarm(time_val)
            if success:
                self.append_system_notice(f"⏰ [Alarm]: {msg}")
                dialog.destroy()
            else:
                messagebox.showerror("Invalid Time", msg)

        btn_frame = ctk.CTkFrame(dialog, fg_color="transparent")
        btn_frame.pack(pady=(0, 20))

        ctk.CTkButton(
            btn_frame, text="Set", width=80, command=_submit,
            fg_color="#2563eb", hover_color="#1d4ed8"
        ).pack(side="left", padx=5)

        ctk.CTkButton(
            btn_frame, text="Cancel", width=80, command=dialog.destroy,
            fg_color="#334155", hover_color="#475569"
        ).pack(side="left", padx=5)

        dialog.bind("<Return>", lambda e: _submit())

    def _clear_alarm_action(self):
        if self.alarm_service:
            msg = self.alarm_service.clear_alarm()
            self.append_system_notice(f"⏰ [Alarm]: {msg}")
        else:
            messagebox.showerror("Error", "Alarm service not initialized.")

    def _check_alarm_status(self):
        if self.alarm_service:
            status = self.alarm_service.get_status_prompt()
            messagebox.showinfo("Alarm Status", status)
        else:
            messagebox.showerror("Error", "Alarm service not initialized.")

    # -------------------------------------------------------------------------
    # SUBMIT & INPUT HANDLING
    # -------------------------------------------------------------------------
    def _handle_enter_key(self, event):
        if not (event.state & 0x1):
            self._handle_gui_submit()
            return "break"
        # If Shift+Enter, allow newline and adjust height
        self.root.after(10, self._adjust_input_height)
        return None

    def _handle_gui_submit(self, event=None):
        text = self.user_input.get("1.0", "end").strip()
        if text:
            # Silence is broken by the user: clear any active idle reverie immediately
            self.dismiss_reverie_card()
            self.append_user_message(text)
            self.input_queue.put(text)
            self.user_input.delete("1.0", "end")

            # Collapse manual expansion if open and reset resting height
            if getattr(self, "_is_input_manually_expanded", False):
                self._is_input_manually_expanded = False
                if hasattr(self, "expand_btn") and self.expand_btn.winfo_exists():
                    self.expand_btn.configure(text="⤢")
            self._adjust_input_height()
        return "break"
        
    def set_thinking(self, is_thinking):
        def _do():
            if is_thinking:
                self.send_btn.configure(state="disabled", text="Synthesizing...")
            else:
                self.send_btn.configure(state="normal", text="Send\n[Ctrl+Enter]")
        self.root.after(0, _do)

    def start(self):
        self.root.mainloop()
