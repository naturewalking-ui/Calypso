# modules/gui_cards.py

from pathlib import Path
import threading
from datetime import datetime
import tkinter as tk
from tkinter import filedialog, messagebox, Toplevel
from PIL import Image, ImageTk
import customtkinter as ctk
from modules.audio import AudioEngine


class DeckCardsMixin:
    """
    Mixin providing card generation and modal management methods
    for GUIEngine's Right Panel Action & Proposal Deck.
    """

    # -------------------------------------------------------------------------
    # INTERNAL DECK REGISTRATION & LIFECYCLE
    # -------------------------------------------------------------------------
    def _ensure_card_registry(self):
        if not hasattr(self, "_deck_cards"):
            self._deck_cards = []

    def _register_card(self, card_widget):
        """Registers a card and ensures empty placeholder is removed."""
        self._ensure_card_registry()
        if card_widget not in self._deck_cards:
            self._deck_cards.append(card_widget)
        self._prepare_card_slot()

    def _unregister_card(self, card_widget):
        """Unregisters a card and checks if empty placeholder should be restored."""
        self._ensure_card_registry()
        if card_widget in self._deck_cards:
            self._deck_cards.remove(card_widget)
        # Purge any dangling dead widget references
        self._deck_cards = [c for c in self._deck_cards if hasattr(c, "winfo_exists") and c.winfo_exists()]
        self._check_empty_cards_state()

    def _check_empty_cards_state(self):
        self._ensure_card_registry()
        self._deck_cards = [c for c in self._deck_cards if hasattr(c, "winfo_exists") and c.winfo_exists()]
        if not self._deck_cards:
            self._show_cards_empty_state()

    def _show_cards_empty_state(self):
        if hasattr(self, "cards_empty_label") and self.cards_empty_label.winfo_exists():
            return
        self.cards_empty_label = ctk.CTkLabel(
            self.cards_scroll,
            text="Deck is idle.\n\nProposals, scenario invitations,\nalarms, and code audits\nwill surface here.",
            font=ctk.CTkFont(family="Segoe UI", size=11, slant="italic"),
            text_color="#475569", justify="center"
        )
        self.cards_empty_label.pack(pady=60, padx=12)

    def _prepare_card_slot(self):
        """Hides the idle placeholder when a card is added."""
        if hasattr(self, "cards_empty_label") and self.cards_empty_label.winfo_exists():
            try:
                self.cards_empty_label.destroy()
            except Exception:
                pass

    def _scroll_cards_to_bottom(self):
        """Scrolls the right-panel action deck scrollable frame to the bottom."""
        def _scroll():
            try:
                if hasattr(self, "cards_scroll") and self.cards_scroll.winfo_exists():
                    self.cards_scroll.update_idletasks()
                    if hasattr(self.cards_scroll, "_parent_canvas"):
                        self.cards_scroll._parent_canvas.yview_moveto(1.0)
                    elif hasattr(self.cards_scroll, "yview_moveto"):
                        self.cards_scroll.yview_moveto(1.0)
            except Exception:
                pass

        if hasattr(self, "root") and self.root:
            self.root.after_idle(_scroll)
        else:
            _scroll()

    def scroll_cards_to_bottom(self):
        """Public alias for _scroll_cards_to_bottom."""
        self._scroll_cards_to_bottom()

    def clear_all_cards(self):
        """Cleans all deck cards, ensuring any pending dismissal/decay callbacks execute."""
        def _do():
            # 1. Cancel active reverie timers and force-dismiss active reverie card
            self._dismiss_reverie_sync(force=True)

            self._ensure_card_registry()

            preserved_cards = []
            for widget in list(self._deck_cards):
                if getattr(widget, "_persist_until_cleared", False):
                    if hasattr(widget, "winfo_exists") and widget.winfo_exists():
                        preserved_cards.append(widget)
                    continue

                dismiss_cb = getattr(widget, "_on_dismiss", None)
                if callable(dismiss_cb):
                    try:
                        dismiss_cb()
                    except Exception as e:
                        print(f"[GUI] Error running card dismiss callback: {e}")

                try:
                    if widget.winfo_exists():
                        widget.destroy()
                except Exception:
                    pass

            self._deck_cards = preserved_cards
            self._active_scenario_card = None
            self._active_inquiry_card = None
            self._active_trait_evolution_card = None
            self._active_code_proposal_card = None

            if not self._deck_cards:
                self._show_cards_empty_state()

        if hasattr(self, "root") and self.root:
            if threading.current_thread() is threading.main_thread():
                _do()
            else:
                self.root.after(0, _do)

    def _dismiss_reverie_sync(self, force: bool = False):
        """Internal synchronous helper: cancels reverie timers and destroys active card."""
        card = getattr(self, "_active_reverie_card", None)
        if card and not force and getattr(card, "_is_handling", False):
            # Already transitioning on its own graceful fade/dismissal timer
            return

        for attr in ("_active_reverie_timer", "_active_reverie_fade_timer"):
            timer = getattr(self, attr, None)
            if timer:
                try:
                    self.root.after_cancel(timer)
                except Exception:
                    pass
                setattr(self, attr, None)

        self._active_reverie_card = None
        if card:
            if hasattr(self, "_deck_cards") and card in self._deck_cards:
                self._unregister_card(card)
            if card.winfo_exists():
                try:
                    card.destroy()
                except Exception:
                    pass

    def dismiss_reverie_card(self):
        """Thread-safe dismissal of the idle reverie card."""
        if not hasattr(self, "root") or not self.root:
            return
        if threading.current_thread() is threading.main_thread():
            self._dismiss_reverie_sync(force=False)
        else:
            self.root.after(0, lambda: self._dismiss_reverie_sync(force=False))

    # -------------------------------------------------------------------------
    # IDLE REVERIE / CHECK-IN CARD (CANONICAL)
    # -------------------------------------------------------------------------
    def append_reverie_proposal_card(
        self, 
        note_text: str = "Calypso looks over quietly...", 
        on_accept=None, 
        on_ignore=None, 
        ttl_seconds: int = 240,
        header_text: str = "💭 IDLE REVERIE // CHECK-IN",
        accept_text: str = "Listen 💬"
    ):
        def _do():
            # 1. Supersede & synchronously clean up any prior active reverie card
            self._dismiss_reverie_sync(force=True)

            target_parent = getattr(self, "chat_scroll", None) or getattr(self, "cards_scroll", None)
            if not target_parent:
                return

            is_chat = (target_parent is getattr(self, "chat_scroll", None))

            card = ctk.CTkFrame(
                target_parent, fg_color="#141824", corner_radius=12,
                border_width=1, border_color="#3d3363"
            )
            card._is_handling = False
            card.pack(fill="x", padx=14 if is_chat else 4, pady=8 if is_chat else 6)
            self._active_reverie_card = card

            if not is_chat:
                self._register_card(card)

            handled = False

            def _cancel_timers():
                for attr in ("_active_reverie_timer", "_active_reverie_fade_timer"):
                    t = getattr(self, attr, None)
                    if t:
                        try:
                            self.root.after_cancel(t)
                        except Exception:
                            pass
                        setattr(self, attr, None)

            def _safe_destroy_this_card():
                _cancel_timers()
                if card.winfo_exists():
                    try:
                        card.destroy()
                    except Exception:
                        pass
                if getattr(self, "_active_reverie_card", None) is card:
                    self._active_reverie_card = None
                if hasattr(self, "_deck_cards") and card in self._deck_cards:
                    self._unregister_card(card)

            def _handle_accept():
                nonlocal handled
                if handled:
                    return
                handled = True
                card._is_handling = True
                _cancel_timers()

                try:
                    accept_btn.pack_forget()
                    ignore_btn.pack_forget()
                    status_lbl = ctk.CTkLabel(
                        action_frame, text="✓ Check-in Accepted — Calypso is reflecting...",
                        font=ctk.CTkFont(size=11, weight="bold"), text_color="#c4b5fd"
                    )
                    status_lbl.pack(fill="x")
                except Exception:
                    pass

                if callable(on_accept):
                    try:
                        on_accept()
                    except Exception as e:
                        print(f"[GUI] Reverie accept callback error: {e}")

                self._active_reverie_fade_timer = self.root.after(1200, _safe_destroy_this_card)

            def _handle_ignore():
                nonlocal handled
                if handled:
                    return
                handled = True
                card._is_handling = True
                _cancel_timers()

                try:
                    accept_btn.pack_forget()
                    ignore_btn.pack_forget()
                    status_lbl = ctk.CTkLabel(
                        action_frame, text="✕ Dismissed",
                        font=ctk.CTkFont(size=11, weight="bold"), text_color="#64748b"
                    )
                    status_lbl.pack(fill="x")
                except Exception:
                    pass

                if callable(on_ignore):
                    try:
                        on_ignore()
                    except Exception as e:
                        print(f"[GUI] Reverie ignore callback error: {e}")

                self._active_reverie_fade_timer = self.root.after(800, _safe_destroy_this_card)

            card._on_dismiss = lambda: on_ignore() if (not handled and callable(on_ignore)) else None

            # Header
            hdr_row = ctk.CTkFrame(card, fg_color="transparent")
            hdr_row.pack(fill="x", padx=12, pady=(10, 4))

            hdr_left = ctk.CTkFrame(hdr_row, fg_color="transparent")
            hdr_left.pack(side="left")

            ctk.CTkLabel(
                hdr_left, text=header_text or "💭 IDLE REVERIE // CHECK-IN",
                font=ctk.CTkFont(family="Consolas", size=10, weight="bold"),
                text_color="#c084fc"
            ).pack(side="left")

            time_str = datetime.now().strftime("%H:%M")
            ctk.CTkLabel(
                hdr_left, text=f"• {time_str}",
                font=ctk.CTkFont(size=9),
                text_color="#64748b"
            ).pack(side="left", padx=(6, 0))

            ctk.CTkButton(
                hdr_row, text="✕", width=22, height=20, fg_color="transparent",
                hover_color="#334155", text_color="#94a3b8", font=ctk.CTkFont(size=10, weight="bold"),
                command=_handle_ignore
            ).pack(side="right")

            desc_font_size = max(11, getattr(self, "font_size", 12))
            desc_lbl = ctk.CTkLabel(
                card, text=f'"{note_text}"',
                font=ctk.CTkFont(family="Segoe UI", size=desc_font_size, slant="italic"),
                text_color="#cbd5e1", justify="left", wraplength=620 if is_chat else 320
            )
            desc_lbl.pack(anchor="w", padx=12, pady=(2, 8))

            if is_chat and hasattr(self, "_registered_chat_labels"):
                self._registered_chat_labels.append((desc_lbl, "Segoe UI", 0, None, "italic"))

            action_frame = ctk.CTkFrame(card, fg_color="transparent")
            action_frame.pack(fill="x", padx=12, pady=(0, 10))

            accept_btn = ctk.CTkButton(
                action_frame, text=accept_text or "Listen 💬", height=28,
                fg_color="#7c3aed", hover_color="#6d28d9", font=ctk.CTkFont(size=11, weight="bold"),
                command=_handle_accept
            )
            accept_btn.pack(side="left", fill="x", expand=True, padx=(0, 4))

            ignore_btn = ctk.CTkButton(
                action_frame, text="Stay Quiet ✕", height=28,
                fg_color="#1e293b", hover_color="#334155", font=ctk.CTkFont(size=11),
                text_color="#94a3b8", command=_handle_ignore
            )
            ignore_btn.pack(side="right", fill="x", expand=True, padx=(4, 0))

            def _auto_expire():
                nonlocal handled
                if not handled and card.winfo_exists():
                    handled = True
                    card._is_handling = True
                    _cancel_timers()
                    try:
                        for child in action_frame.winfo_children():
                            child.destroy()
                        fade_lbl = ctk.CTkLabel(
                            action_frame, text="🌿 [Faded quietly into thought...]",
                            font=ctk.CTkFont(size=10, slant="italic"), text_color="#64748b"
                        )
                        fade_lbl.pack(fill="x")
                    except Exception:
                        pass
                    if callable(on_ignore):
                        try:
                            on_ignore()
                        except Exception as e:
                            print(f"[GUI] Reverie auto-expire callback error: {e}")
                    self._active_reverie_fade_timer = self.root.after(1500, _safe_destroy_this_card)

            self._active_reverie_timer = self.root.after(ttl_seconds * 1000, _auto_expire)

            if hasattr(self, "play_sfx"):
                self.play_sfx("reverie_checkin_prompt")

            if is_chat and hasattr(self, "_scroll_to_bottom"):
                self._scroll_to_bottom()
            else:
                self._scroll_cards_to_bottom()


        if hasattr(self, "root") and self.root:
            if threading.current_thread() is threading.main_thread():
                _do()
            else:
                self.root.after(0, _do)

    # -------------------------------------------------------------------------
    # 100% PERSONAL GOAL FINALE CARD (ACTION DECK)
    # -------------------------------------------------------------------------
    def append_goal_finale_card(
        self,
        goal: dict,
        on_achieved=None,
        on_extend=None,
        on_discuss=None
    ):
        """
        Surfaces a persistent 100% Goal Finale card in the Action Deck when a
        personal goal reaches 100% of its scheduled timeline.
        """
        def _do():
            target_parent = getattr(self, "cards_scroll", None) or getattr(self, "chat_scroll", None)
            if not target_parent:
                return

            if hasattr(self, "_active_goal_finale_card") and self._active_goal_finale_card and self._active_goal_finale_card.winfo_exists():
                try:
                    self._unregister_card(self._active_goal_finale_card)
                    self._active_goal_finale_card.destroy()
                except Exception:
                    pass

            card = ctk.CTkFrame(
                target_parent, fg_color="#191714", corner_radius=12,
                border_width=2, border_color="#d97706"
            )
            card.pack(fill="x", padx=4, pady=6)
            self._register_card(card)
            self._active_goal_finale_card = card

            handled = False

            def _safe_destroy():
                if card.winfo_exists():
                    try:
                        card.destroy()
                    except Exception:
                        pass
                if getattr(self, "_active_goal_finale_card", None) is card:
                    self._active_goal_finale_card = None
                self._unregister_card(card)

            # Header Row
            hdr_row = ctk.CTkFrame(card, fg_color="transparent")
            hdr_row.pack(fill="x", padx=12, pady=(10, 2))

            ctk.CTkLabel(
                hdr_row, text="🏁 100% GOAL DEADLINE // FINAL CHECK-IN",
                font=ctk.CTkFont(family="Consolas", size=10, weight="bold"),
                text_color="#fbbf24"
            ).pack(side="left")

            ctk.CTkButton(
                hdr_row, text="✕", width=22, height=20, fg_color="transparent",
                hover_color="#334155", text_color="#94a3b8",
                font=ctk.CTkFont(size=10, weight="bold"),
                command=_safe_destroy
            ).pack(side="right")

            # Goal Title
            title_str = goal.get("title", "Personal Goal")
            ctk.CTkLabel(
                card, text=f"🎯 {title_str}",
                font=ctk.CTkFont(size=14, weight="bold"),
                text_color="#f8fafc", justify="left", wraplength=320
            ).pack(anchor="w", padx=12, pady=(4, 2))

            # Optional Criteria / Target
            criteria_str = goal.get("criteria", "")
            if criteria_str:
                ctk.CTkLabel(
                    card, text=f"Target / Focus: {criteria_str}",
                    font=ctk.CTkFont(size=11, slant="italic"),
                    text_color="#fcd34d", justify="left", wraplength=320
                ).pack(anchor="w", padx=12, pady=(0, 4))

            # Timeline + 100% Progress Bar
            start_d = goal.get("start_date", "")
            target_d = goal.get("target_date", "")
            ctk.CTkLabel(
                card, text=f"📅 {start_d}  ➔  {target_d} (100% Time Elapsed)",
                font=ctk.CTkFont(family="Consolas", size=10),
                text_color="#94a3b8"
            ).pack(anchor="w", padx=12, pady=(0, 4))

            prog_bar = ctk.CTkProgressBar(card, height=8, fg_color="#292524", progress_color="#f59e0b")
            prog_bar.pack(fill="x", padx=12, pady=(0, 8))
            prog_bar.set(1.0)

            # Check-in History Snippet
            logs = goal.get("progress_log", [])
            if logs:
                log_box = ctk.CTkFrame(card, fg_color="#11131a", corner_radius=6)
                log_box.pack(fill="x", padx=12, pady=(0, 8))
                for entry in logs[-3:]:
                    pct_lbl = entry.get("checkpoint_pct", "")
                    note_txt = entry.get("note", "")
                    ctk.CTkLabel(
                        log_box, text=f"• [{pct_lbl}%] {note_txt}",
                        font=ctk.CTkFont(size=10), text_color="#cbd5e1",
                        justify="left", wraplength=300
                    ).pack(anchor="w", padx=8, pady=2)

            action_frame = ctk.CTkFrame(card, fg_color="transparent")
            action_frame.pack(fill="x", padx=12, pady=(2, 10))

            def _finish_with_status(status_text: str, color: str, cb):
                nonlocal handled
                if handled:
                    return
                handled = True
                for child in action_frame.winfo_children():
                    child.destroy()
                ctk.CTkLabel(
                    action_frame, text=status_text,
                    font=ctk.CTkFont(size=11, weight="bold"), text_color=color
                ).pack(fill="x", pady=4)
                if callable(cb):
                    try:
                        cb()
                    except Exception as e:
                        print(f"[GUI] Goal finale callback error: {e}")
                self.root.after(1600, _safe_destroy)

            btn_achieved = ctk.CTkButton(
                action_frame, text="🏆 Goal Achieved!", height=30,
                fg_color="#059669", hover_color="#047857",
                font=ctk.CTkFont(size=11, weight="bold"),
                command=lambda: _finish_with_status("🏆 Goal Achieved! Celebrating with Calypso...", "#34d399", on_achieved)
            )
            btn_achieved.pack(fill="x", pady=(0, 4))

            row_sub = ctk.CTkFrame(action_frame, fg_color="transparent")
            row_sub.pack(fill="x")

            btn_extend = ctk.CTkButton(
                row_sub, text="⏳ Extend (+7d)", height=26,
                fg_color="#d97706", hover_color="#b45309",
                font=ctk.CTkFont(size=10, weight="bold"),
                command=lambda: _finish_with_status("⏳ Deadline Extended +7 Days", "#fbbf24", on_extend)
            )
            btn_extend.pack(side="left", fill="x", expand=True, padx=(0, 3))

            btn_discuss = ctk.CTkButton(
                row_sub, text="💬 Re-plan with Calypso", height=26,
                fg_color="#334155", hover_color="#475569",
                font=ctk.CTkFont(size=10, weight="bold"),
                command=lambda: _finish_with_status("💬 Discussing next steps with Calypso...", "#38bdf8", on_discuss)
            )
            btn_discuss.pack(side="right", fill="x", expand=True, padx=(3, 0))

            if hasattr(self, "play_sfx"):
                self.play_sfx("reverie_checkin_prompt")
            self._scroll_cards_to_bottom()

        if hasattr(self, "root") and self.root:
            if threading.current_thread() is threading.main_thread():
                _do()
            else:
                self.root.after(0, _do)

    # -------------------------------------------------------------------------
    # SCENARIO / DATE PROPOSAL CARD
    # -------------------------------------------------------------------------
    def append_scenario_proposal_card(self, scenario_title: str, narrative_shard: str, on_accept=None, on_decline=None):
        def _do():
            if hasattr(self, "_active_scenario_card") and self._active_scenario_card and self._active_scenario_card.winfo_exists():
                self._unregister_card(self._active_scenario_card)
                self._active_scenario_card.destroy()

            card = ctk.CTkFrame(
                self.cards_scroll, fg_color="#181d2a", corner_radius=10,
                border_width=1, border_color="#2b354d"
            )
            card.pack(fill="x", padx=4, pady=6)
            self._register_card(card)
            self._active_scenario_card = card

            handled = False

            def _safe_destroy():
                if card.winfo_exists():
                    try:
                        card.destroy()
                    except Exception:
                        pass
                if getattr(self, "_active_scenario_card", None) is card:
                    self._active_scenario_card = None
                self._unregister_card(card)

            def _handle_accept():
                nonlocal handled
                if handled:
                    return
                handled = True

                try:
                    accept_btn.pack_forget()
                    decline_btn.pack_forget()
                    status_lbl = ctk.CTkLabel(
                        action_frame, text="✓ Setting Activated",
                        font=ctk.CTkFont(size=11, weight="bold"), text_color="#34d399"
                    )
                    status_lbl.pack(fill="x")
                except Exception:
                    pass

                if on_accept:
                    try:
                        on_accept()
                    except Exception as e:
                        print(f"[GUI] Scenario accept callback error: {e}")
                self.root.after(1500, _safe_destroy)

            def _handle_decline():
                nonlocal handled
                if handled:
                    return
                handled = True

                try:
                    accept_btn.pack_forget()
                    decline_btn.pack_forget()
                    status_lbl = ctk.CTkLabel(
                        action_frame, text="✕ Declined (Baseline Kept)",
                        font=ctk.CTkFont(size=11, weight="bold"), text_color="#94a3b8"
                    )
                    status_lbl.pack(fill="x")
                except Exception:
                    pass

                if on_decline:
                    try:
                        on_decline()
                    except Exception as e:
                        print(f"[GUI] Scenario decline callback error: {e}")
                self.root.after(1000, _safe_destroy)

            card._on_dismiss = lambda: on_decline() if (not handled and callable(on_decline)) else None

            hdr_row = ctk.CTkFrame(card, fg_color="transparent")
            hdr_row.pack(fill="x", padx=10, pady=(8, 2))

            ctk.CTkLabel(
                hdr_row, text=f"✨ {scenario_title.upper()[:24]}",
                font=ctk.CTkFont(family="Consolas", size=10, weight="bold"),
                text_color="#38bdf8"
            ).pack(side="left")

            ctk.CTkButton(
                hdr_row, text="✕", width=22, height=20, fg_color="transparent",
                hover_color="#334155", text_color="#94a3b8", font=ctk.CTkFont(size=10, weight="bold"),
                command=_handle_decline
            ).pack(side="right")

            desc_text = narrative_shard if narrative_shard else "Calypso has proposed entering this shared scenario."
            desc_lbl = ctk.CTkLabel(
                card, text=f'"{desc_text}"',
                font=ctk.CTkFont(family="Segoe UI", size=11, slant="italic"),
                text_color="#cbd5e1", justify="left", wraplength=320
            )
            desc_lbl.pack(anchor="w", padx=10, pady=(2, 8))

            action_frame = ctk.CTkFrame(card, fg_color="transparent")
            action_frame.pack(fill="x", padx=10, pady=(0, 8))

            accept_btn = ctk.CTkButton(
                action_frame, text="Accept ✨", height=28,
                fg_color="#059669", hover_color="#047857", font=ctk.CTkFont(size=11, weight="bold"),
                command=_handle_accept
            )
            accept_btn.pack(side="left", fill="x", expand=True, padx=(0, 4))

            decline_btn = ctk.CTkButton(
                action_frame, text="Decline ✕", height=28,
                fg_color="#334155", hover_color="#475569", font=ctk.CTkFont(size=11),
                command=_handle_decline
            )
            decline_btn.pack(side="right", fill="x", expand=True, padx=(4, 0))

            self._scroll_cards_to_bottom()

        if hasattr(self, "root") and self.root:
            if threading.current_thread() is threading.main_thread():
                _do()
            else:
                self.root.after(0, _do)

    # -------------------------------------------------------------------------
    # INQUIRY & PDF REQUEST CARD
    # -------------------------------------------------------------------------
    def append_inquiry_card(
        self, 
        topic_hint: str = "Calypso has entered a state of inquiry...", 
        on_accept=None, 
        on_ingest=None, 
        on_web_search=None, 
        on_decline=None
    ):
        def _do():
            if hasattr(self, "_active_inquiry_card") and self._active_inquiry_card and self._active_inquiry_card.winfo_exists():
                self._unregister_card(self._active_inquiry_card)
                self._active_inquiry_card.destroy()

            card = ctk.CTkFrame(
                self.cards_scroll, fg_color="#121a29", corner_radius=10,
                border_width=1, border_color="#0284c7"
            )
            card.pack(fill="x", padx=4, pady=6)
            self._register_card(card)
            self._active_inquiry_card = card

            def _safe_destroy():
                if card.winfo_exists():
                    try:
                        card.destroy()
                    except Exception:
                        pass
                if getattr(self, "_active_inquiry_card", None) is card:
                    self._active_inquiry_card = None
                self._unregister_card(card)

            hdr_row = ctk.CTkFrame(card, fg_color="transparent")
            hdr_row.pack(fill="x", padx=10, pady=(8, 2))

            ctk.CTkLabel(
                hdr_row, text="🔍 INQUIRY // RESEARCH REQUEST",
                font=ctk.CTkFont(family="Consolas", size=10, weight="bold"),
                text_color="#38bdf8"
            ).pack(side="left")

            ctk.CTkButton(
                hdr_row, text="✕", width=22, height=20, fg_color="transparent",
                hover_color="#334155", text_color="#94a3b8", font=ctk.CTkFont(size=10, weight="bold"),
                command=_safe_destroy
            ).pack(side="right")

            title_lbl = ctk.CTkLabel(
                card, text="State of Inquiry Engaged",
                font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
                text_color="#f8fafc", justify="left"
            )
            title_lbl.pack(anchor="w", padx=10, pady=(2, 2))

            desc_text = topic_hint if topic_hint else "Calypso is seeking external reference material, online verification, or a PDF to explore this topic further."
            desc_lbl = ctk.CTkLabel(
                card, text=desc_text,
                font=ctk.CTkFont(family="Segoe UI", size=11, slant="italic"),
                text_color="#cbd5e1", justify="left", wraplength=320
            )
            desc_lbl.pack(anchor="w", padx=10, pady=(0, 8))

            action_frame = ctk.CTkFrame(card, fg_color="transparent")
            action_frame.pack(fill="x", padx=10, pady=(0, 8))

            btn_row1 = ctk.CTkFrame(action_frame, fg_color="transparent")
            btn_row1.pack(fill="x", pady=(0, 4))

            web_btn = ctk.CTkButton(
                btn_row1, text="Search Web 🌐", height=28,
                fg_color="#0284c7", hover_color="#0369a1", font=ctk.CTkFont(size=11, weight="bold")
            )
            web_btn.pack(side="left", fill="x", expand=True, padx=(0, 3))

            accept_btn = ctk.CTkButton(
                btn_row1, text="Open Folder 📂", height=28,
                fg_color="#1e293b", hover_color="#334155", font=ctk.CTkFont(size=11, weight="bold")
            )
            accept_btn.pack(side="right", fill="x", expand=True, padx=(3, 0))

            decline_btn = ctk.CTkButton(
                action_frame, text="Dismiss ✕", height=22,
                fg_color="transparent", hover_color="#1e293b", text_color="#94a3b8", font=ctk.CTkFont(size=10)
            )
            decline_btn.pack(fill="x")

            def _handle_web_search():
                btn_row1.pack_forget()
                decline_btn.pack_forget()
                status_lbl = ctk.CTkLabel(
                    action_frame, text="🌐 Dispatching Web Research & Epistemic Audit...",
                    font=ctk.CTkFont(size=11, weight="bold"), text_color="#38bdf8"
                )
                status_lbl.pack(fill="x", pady=(0, 4))
                if callable(on_web_search):
                    on_web_search()

            def _handle_accept():
                btn_row1.pack_forget()
                decline_btn.pack_forget()
                status_lbl = ctk.CTkLabel(
                    action_frame, text="✓ Folder Opened for PDF Staging",
                    font=ctk.CTkFont(size=11, weight="bold"), text_color="#38bdf8"
                )
                status_lbl.pack(fill="x", pady=(0, 4))

                if callable(on_accept):
                    on_accept()

                if callable(on_ingest):
                    ingest_btn = ctk.CTkButton(
                        action_frame, text="Ingest Staged PDFs 📚", height=26,
                        fg_color="#059669", hover_color="#047857", font=ctk.CTkFont(size=10, weight="bold"),
                        command=lambda: [ingest_btn.configure(state="disabled", text="Ingesting..."), on_ingest()]
                    )
                    ingest_btn.pack(fill="x")

            def _handle_decline():
                btn_row1.pack_forget()
                decline_btn.pack_forget()
                status_lbl = ctk.CTkLabel(
                    action_frame, text="✕ Inquiry Shelved",
                    font=ctk.CTkFont(size=11, weight="bold"), text_color="#94a3b8"
                )
                status_lbl.pack(fill="x")
                if callable(on_decline):
                    on_decline()
                self.root.after(1000, _safe_destroy)

            web_btn.configure(command=_handle_web_search)
            accept_btn.configure(command=_handle_accept)
            decline_btn.configure(command=_handle_decline)
            self._scroll_cards_to_bottom()

        if hasattr(self, "root") and self.root:
            if threading.current_thread() is threading.main_thread():
                _do()
            else:
                self.root.after(0, _do)

    # -------------------------------------------------------------------------
    # RESEARCH REQUEST CARD
    # -------------------------------------------------------------------------
    def append_research_proposal_card(self, research_data: dict, on_discuss=None, on_save_library=None, on_reject=None):
        def _do():
            card = ctk.CTkFrame(
                self.cards_scroll, fg_color="#131d2a", corner_radius=10,
                border_width=1, border_color="#0284c7"
            )
            card.pack(fill="x", padx=4, pady=6)
            self._register_card(card)

            def _destroy():
                if card.winfo_exists():
                    try:
                        card.destroy()
                    except Exception:
                        pass
                self._unregister_card(card)

            handled_action = False

            def _handle_reject():
                nonlocal handled_action
                if handled_action:
                    return
                handled_action = True
                try:
                    discuss_btn.pack_forget()
                    save_btn.pack_forget()
                    reject_btn.pack_forget()
                    status_lbl = ctk.CTkLabel(
                        btn_bar, text="✕ Discarded (Database Unaffected)",
                        font=ctk.CTkFont(size=11, weight="bold"), text_color="#f87171"
                    )
                    status_lbl.pack(fill="x")
                except Exception:
                    pass
                if callable(on_reject):
                    on_reject()
                self.root.after(800, _destroy)

            hdr_row = ctk.CTkFrame(card, fg_color="transparent")
            hdr_row.pack(fill="x", padx=10, pady=(8, 2))

            ctk.CTkLabel(
                hdr_row, text="🔍 VETTED ONLINE RESEARCH",
                font=ctk.CTkFont(family="Consolas", size=10, weight="bold"),
                text_color="#38bdf8"
            ).pack(side="left")

            ctk.CTkButton(
                hdr_row, text="✕", width=22, height=20, fg_color="transparent",
                hover_color="#334155", text_color="#94a3b8", font=ctk.CTkFont(size=10, weight="bold"),
                command=_handle_reject
            ).pack(side="right")

            topic_title = research_data.get("topic", "Research Synthesis")
            ctk.CTkLabel(
                card, text=f'"{topic_title}"',
                font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
                text_color="#f8fafc", justify="left", wraplength=320
            ).pack(anchor="w", padx=10, pady=(2, 2))

            conf = int(research_data.get("confidence_score", 0.7) * 100)
            sources = ", ".join(research_data.get("sources", [])) or "Web"
            meta_color = "#34d399" if conf >= 75 else "#f59e0b"

            ctk.CTkLabel(
                card, text=f"Confidence: {conf}% Consensus • Sources: {sources}",
                font=ctk.CTkFont(family="Consolas", size=9, weight="bold"),
                text_color=meta_color, justify="left"
            ).pack(anchor="w", padx=10, pady=(0, 6))

            consensus_text = research_data.get("vetted_consensus", "")[:360]
            ctk.CTkLabel(
                card, text=f"{consensus_text}...",
                font=ctk.CTkFont(family="Segoe UI", size=10),
                text_color="#cbd5e1", justify="left", wraplength=320
            ).pack(anchor="w", padx=10, pady=(0, 6))

            contested = research_data.get("contested_points", [])
            if contested:
                caveat_text = "⚠️ Caveats: " + "; ".join(contested[:2])
                ctk.CTkLabel(
                    card, text=caveat_text,
                    font=ctk.CTkFont(family="Segoe UI", size=9, slant="italic"),
                    text_color="#fbbf24", justify="left", wraplength=320
                ).pack(anchor="w", padx=10, pady=(0, 6))

            btn_bar = ctk.CTkFrame(card, fg_color="transparent")
            btn_bar.pack(fill="x", padx=10, pady=(0, 8))

            discuss_btn = ctk.CTkButton(
                btn_bar, text="Discuss 💬", height=28,
                fg_color="#0284c7", hover_color="#0369a1", font=ctk.CTkFont(size=11, weight="bold")
            )
            discuss_btn.pack(side="left", fill="x", expand=True, padx=(0, 3))

            save_btn = ctk.CTkButton(
                btn_bar, text="Save 📚", height=28,
                fg_color="#1e293b", hover_color="#334155", font=ctk.CTkFont(size=10, weight="bold")
            )
            save_btn.pack(side="left", fill="x", expand=True, padx=(3, 3))

            reject_btn = ctk.CTkButton(
                btn_bar, text="Reject ✕", height=28,
                fg_color="#3b1d24", hover_color="#5a232f", text_color="#f87171",
                font=ctk.CTkFont(size=10, weight="bold")
            )
            reject_btn.pack(side="right", fill="x", expand=True, padx=(3, 0))

            def _handle_discuss():
                nonlocal handled_action
                if handled_action:
                    return
                handled_action = True
                try:
                    discuss_btn.pack_forget()
                    save_btn.pack_forget()
                    reject_btn.pack_forget()
                    status_lbl = ctk.CTkLabel(
                        btn_bar, text="✓ Engaged (5-Turn Thoughtful)",
                        font=ctk.CTkFont(size=11, weight="bold"), text_color="#38bdf8"
                    )
                    status_lbl.pack(fill="x")
                except Exception:
                    pass
                if callable(on_discuss):
                    on_discuss()

            def _handle_save():
                try:
                    save_btn.configure(state="disabled", text="Saved ✓", fg_color="#065f46")
                except Exception:
                    pass
                if callable(on_save_library):
                    on_save_library()

            discuss_btn.configure(command=_handle_discuss)
            save_btn.configure(command=_handle_save)
            reject_btn.configure(command=_handle_reject)
            if hasattr(self, "play_sfx"):
                self.play_sfx("synthesis_done")
            self._scroll_cards_to_bottom()

        if hasattr(self, "root") and self.root:
            if threading.current_thread() is threading.main_thread():
                _do()
            else:
                self.root.after(0, _do)

    # -------------------------------------------------------------------------
    # IMAGE / SCENE PROPOSAL CARD
    # -------------------------------------------------------------------------
    def append_image_proposal_card(
        self,
        prompt_text: str,
        generate_callback=None,
        purge_callback=None,
        auto_render: bool = False,
        is_storybook: bool = False,
        header_label: str = None
    ):
        def _do():
            card = ctk.CTkFrame(
                self.cards_scroll,
                fg_color="#161928" if is_storybook else "#181d2a",
                corner_radius=10,
                border_width=1,
                border_color="#6d28d9" if is_storybook else "#2b354d"
            )
            card.pack(fill="x", padx=4, pady=6)
            self._register_card(card)

            def _destroy():
                if card.winfo_exists():
                    try:
                        card.destroy()
                    except Exception:
                        pass
                self._unregister_card(card)

            hdr_row = ctk.CTkFrame(card, fg_color="transparent")
            hdr_row.pack(fill="x", padx=10, pady=(8, 2))

            hdr_text = header_label or ("📖 STORYBOOK ILLUSTRATION" if is_storybook else "🎨 SCENE PROPOSAL")
            hdr_color = "#c084fc" if is_storybook else "#f59e0b"

            ctk.CTkLabel(
                hdr_row, text=hdr_text, 
                font=ctk.CTkFont(family="Consolas", size=10, weight="bold"),
                text_color=hdr_color
            ).pack(side="left")

            ctk.CTkButton(
                hdr_row, text="✕", width=22, height=20, fg_color="transparent",
                hover_color="#334155", text_color="#94a3b8", font=ctk.CTkFont(size=10, weight="bold"),
                command=_destroy
            ).pack(side="right")

            prompt_lbl = ctk.CTkLabel(
                card, text=f'"{prompt_text}"', 
                font=ctk.CTkFont(family="Segoe UI", size=11, slant="italic"),
                text_color="#cbd5e1", justify="left", wraplength=320
            )
            prompt_lbl.pack(anchor="w", padx=10, pady=(2, 8))

            action_frame = ctk.CTkFrame(card, fg_color="transparent")
            action_frame.pack(fill="x", padx=10, pady=(0, 8))

            render_btn = ctk.CTkButton(
                action_frame, text="Render Scene (SDXL)", height=30,
                fg_color="#d97706", hover_color="#b45309", font=ctk.CTkFont(size=11, weight="bold")
            )
            render_btn.pack(fill="x")

            def _on_render_click(is_reroll: bool = False):
                if not card.winfo_exists():
                    return
                if not render_btn.winfo_ismapped():
                    render_btn.pack(fill="x")
                if is_reroll:
                    btn_label = "🔄 Re-rolling Scene (SDXL)..."
                elif is_storybook:
                    btn_label = "📖 Illustrating Storybook Scene (SDXL)..."
                else:
                    btn_label = "Synthesizing..."
                render_btn.configure(state="disabled", text=btn_label, fg_color="#475569")
                
                def _worker():
                    file_path = None
                    if generate_callback:
                        file_path = generate_callback(prompt_text)

                    def _update_card():
                        if not card.winfo_exists():
                            return
                        if file_path and Path(file_path).exists():
                            render_btn.pack_forget()

                            def _handle_reroll(old_fp, attached_widgets):
                                if callable(purge_callback):
                                    try:
                                        purge_callback(old_fp)
                                    except Exception as e:
                                        print(f"[GUI] Purge before re-roll error: {e}")
                                for w in attached_widgets:
                                    try:
                                        if w.winfo_exists():
                                            w.destroy()
                                    except Exception:
                                        pass
                                _on_render_click(is_reroll=True)

                            def _handle_purge(old_fp):
                                if callable(purge_callback):
                                    try:
                                        purge_callback(old_fp)
                                    except Exception as e:
                                        print(f"[GUI] Purge error: {e}")
                                _destroy()

                            self._attach_thumbnail_to_card(
                                card,
                                file_path,
                                prompt_text,
                                on_reroll=_handle_reroll,
                                on_purge=_handle_purge if callable(purge_callback) else None
                            )
                            if hasattr(self, "play_sfx"):
                                self.play_sfx("synthesis_done")
                        else:
                            render_btn.configure(state="normal", text="Retry Render", fg_color="#ef4444")
                            if hasattr(self, "play_sfx"):
                                self.play_sfx("error")
                    
                    if hasattr(self, "root") and self.root:
                        self.root.after(0, _update_card)

                threading.Thread(target=_worker, daemon=True).start()

            render_btn.configure(command=_on_render_click)
            self._scroll_cards_to_bottom()

            if auto_render:
                _on_render_click(is_reroll=False)

        if hasattr(self, "root") and self.root:
            if threading.current_thread() is threading.main_thread():
                _do()
            else:
                self.root.after(0, _do)

    def _attach_thumbnail_to_card(self, card_widget, file_path: str, caption: str, on_reroll=None, on_purge=None):
        try:
            pil_img = Image.open(file_path)
            orig_w, orig_h = pil_img.size
            thumb_w = 310
            thumb_h = int((thumb_w / orig_w) * orig_h)
            thumb_pil = pil_img.resize((thumb_w, thumb_h), Image.LANCZOS)
            thumb_photo = ImageTk.PhotoImage(thumb_pil)

            img_container = ctk.CTkFrame(card_widget, fg_color="#0c0e15", corner_radius=6)
            img_container.pack(fill="x", padx=8, pady=(0, 6))

            thumb_label = tk.Label(img_container, image=thumb_photo, bg="#0c0e15", cursor="hand2")
            thumb_label.image = thumb_photo
            thumb_label.pack(padx=4, pady=4)

            def _open_modal(event=None):
                top = Toplevel(self.root)
                top.title(f"Scene Preview - {Path(file_path).name}")
                top.configure(bg="#0c0e15")
                top.geometry("820x860")

                modal_pil = Image.open(file_path)
                m_w, m_h = modal_pil.size
                scale = min(780 / m_w, 780 / m_h, 1.0)
                disp_w, disp_h = int(m_w * scale), int(m_h * scale)
                modal_photo = ImageTk.PhotoImage(modal_pil.resize((disp_w, disp_h), Image.LANCZOS))

                lbl = tk.Label(top, image=modal_photo, bg="#0c0e15")
                lbl.image = modal_photo
                lbl.pack(padx=16, pady=16)

                cap_lbl = ctk.CTkLabel(
                    top, text=caption, font=ctk.CTkFont(size=12, slant="italic"),
                    text_color="#94a3b8", wraplength=760
                )
                cap_lbl.pack(pady=(0, 12))

            thumb_label.bind("<Button-1>", _open_modal)

            btn_bar = ctk.CTkFrame(card_widget, fg_color="transparent")
            btn_bar.pack(fill="x", padx=8, pady=(0, 8))

            attached_widgets = [img_container, btn_bar]

            open_btn = ctk.CTkButton(
                btn_bar, text="📂 Folder", height=26,
                fg_color="#334155", hover_color="#475569", font=ctk.CTkFont(size=10),
                command=lambda: self.open_folder_callback(Path(file_path).parent)
            )
            open_btn.pack(side="left", fill="x", expand=True, padx=(0, 3 if (on_reroll or on_purge) else 0))

            if callable(on_reroll):
                reroll_btn = ctk.CTkButton(
                    btn_bar, text="🔄 Re-roll", height=26,
                    fg_color="#d97706", hover_color="#b45309",
                    font=ctk.CTkFont(size=10, weight="bold"),
                    command=lambda: on_reroll(file_path, attached_widgets)
                )
                reroll_btn.pack(side="left", fill="x", expand=True, padx=(3, 3 if on_purge else 0))

            if callable(on_purge):
                purge_btn = ctk.CTkButton(
                    btn_bar, text="🗑️ Purge", width=64, height=26,
                    fg_color="#7f1d1d", hover_color="#991b1b", text_color="#fecaca",
                    font=ctk.CTkFont(size=10, weight="bold"),
                    command=lambda: on_purge(file_path)
                )
                purge_btn.pack(side="right", padx=(3, 0))

            self._scroll_cards_to_bottom()
        except Exception as e:
            print(f"[GUI] Error rendering scene thumbnail: {e}")

    # -------------------------------------------------------------------------
    # AUTONOMOUS EMOTIONAL ARTWORK & POETRY CARDS
    # -------------------------------------------------------------------------
    def append_autonomous_art_card(
        self,
        title: str,
        style_desc: str,
        reflection_text: str,
        file_path: str,
        prompt_text: str = "",
        tier: str = "",
        neuro_summary: str = ""
    ):
        def _do():
            card = ctk.CTkFrame(
                self.cards_scroll, fg_color="#151926", corner_radius=10,
                border_width=1, border_color="#3b3354"
            )
            card.pack(fill="x", padx=4, pady=6)
            self._register_card(card)

            def _destroy():
                if card.winfo_exists():
                    try:
                        card.destroy()
                    except Exception:
                        pass
                self._unregister_card(card)

            # Header row
            hdr_row = ctk.CTkFrame(card, fg_color="transparent")
            hdr_row.pack(fill="x", padx=10, pady=(8, 2))

            ctk.CTkLabel(
                hdr_row, text="🎨 AUTONOMOUS ARTWORK",
                font=ctk.CTkFont(family="Consolas", size=10, weight="bold"),
                text_color="#c084fc"
            ).pack(side="left")

            if tier:
                ctk.CTkLabel(
                    hdr_row, text=f"[{tier.upper()}]",
                    font=ctk.CTkFont(family="Consolas", size=9, weight="bold"),
                    text_color="#38bdf8"
                ).pack(side="left", padx=6)

            ctk.CTkButton(
                hdr_row, text="✕", width=22, height=20, fg_color="transparent",
                hover_color="#334155", text_color="#94a3b8", font=ctk.CTkFont(size=10, weight="bold"),
                command=_destroy
            ).pack(side="right")

            # Title
            ctk.CTkLabel(
                card, text=f'"{title}"',
                font=ctk.CTkFont(size=13, weight="bold"),
                text_color="#f8fafc", justify="left", wraplength=320
            ).pack(anchor="w", padx=10, pady=(2, 2))

            # Style description
            if style_desc:
                ctk.CTkLabel(
                    card, text=f"Medium: {style_desc}",
                    font=ctk.CTkFont(size=10, slant="italic"),
                    text_color="#94a3b8", justify="left"
                ).pack(anchor="w", padx=10, pady=(0, 6))

            # Rendered Thumbnail Image
            if file_path and Path(file_path).exists():
                try:
                    pil_img = Image.open(file_path)
                    orig_w, orig_h = pil_img.size
                    thumb_w = 310
                    thumb_h = int((thumb_w / orig_w) * orig_h)
                    thumb_pil = pil_img.resize((thumb_w, thumb_h), Image.LANCZOS)
                    thumb_photo = ImageTk.PhotoImage(thumb_pil)

                    img_container = ctk.CTkFrame(card, fg_color="#0c0e15", corner_radius=6)
                    img_container.pack(fill="x", padx=8, pady=(0, 6))

                    thumb_label = tk.Label(img_container, image=thumb_photo, bg="#0c0e15", cursor="hand2")
                    thumb_label.image = thumb_photo
                    thumb_label.pack(padx=4, pady=4)

                    def _open_art_modal(event=None):
                        top = Toplevel(self.root)
                        top.title(f"Calypso's Art - {title}")
                        top.configure(bg="#0c0e15")
                        top.geometry("860x900")

                        modal_pil = Image.open(file_path)
                        m_w, m_h = modal_pil.size
                        scale = min(820 / m_w, 740 / m_h, 1.0)
                        disp_w, disp_h = int(m_w * scale), int(m_h * scale)
                        modal_photo = ImageTk.PhotoImage(modal_pil.resize((disp_w, disp_h), Image.LANCZOS))

                        lbl = tk.Label(top, image=modal_photo, bg="#0c0e15")
                        lbl.image = modal_photo
                        lbl.pack(padx=16, pady=(16, 8))

                        ctk.CTkLabel(
                            top, text=f'"{title}" ({style_desc})',
                            font=ctk.CTkFont(size=14, weight="bold"),
                            text_color="#f8fafc"
                        ).pack(pady=(0, 4))

                        ctk.CTkLabel(
                            top, text=f'"{reflection_text}"',
                            font=ctk.CTkFont(size=12, slant="italic"),
                            text_color="#cbd5e1", wraplength=800
                        ).pack(pady=(0, 12))

                    thumb_label.bind("<Button-1>", _open_art_modal)
                except Exception as e:
                    print(f"[GUI] Error rendering autonomous art thumbnail: {e}")

            # Reflection Box (Artist note)
            refl_frame = ctk.CTkFrame(card, fg_color="#0e131f", corner_radius=6, border_width=1, border_color="#222b3d")
            refl_frame.pack(fill="x", padx=8, pady=(2, 6))

            ctk.CTkLabel(
                refl_frame, text=f'"{reflection_text}"',
                font=ctk.CTkFont(family="Georgia", size=11, slant="italic"),
                text_color="#e2e8f0", justify="left", wraplength=300
            ).pack(anchor="w", padx=8, pady=6)

            # Limbic telemetry
            if neuro_summary:
                ctk.CTkLabel(
                    card, text=f"🧪 Limbic: {neuro_summary}",
                    font=ctk.CTkFont(family="Consolas", size=9),
                    text_color="#64748b"
                ).pack(anchor="w", padx=10, pady=(0, 6))

            # Action Buttons
            btn_row = ctk.CTkFrame(card, fg_color="transparent")
            btn_row.pack(fill="x", padx=8, pady=(0, 8))

            if file_path and Path(file_path).exists():
                ctk.CTkButton(
                    btn_row, text="📂 Open Image File", height=26,
                    fg_color="#334155", hover_color="#475569", font=ctk.CTkFont(size=10),
                    command=lambda: self.open_folder_callback(Path(file_path).parent)
                ).pack(side="left", fill="x", expand=True, padx=(0, 4))

            if hasattr(self, "play_sfx"):
                self.play_sfx("synthesis_done")
            self._scroll_cards_to_bottom()

        if hasattr(self, "root") and self.root:
            if threading.current_thread() is threading.main_thread():
                _do()
            else:
                self.root.after(0, _do)

    def append_autonomous_poetry_card(
        self,
        title: str,
        theme: str,
        poem_text: str,
        commentary: str,
        tier: str = "",
        neuro_summary: str = "",
        file_path: str = ""
    ):
        def _do():
            card = ctk.CTkFrame(
                self.cards_scroll, fg_color="#141724", corner_radius=10,
                border_width=1, border_color="#3d2c54"
            )
            card.pack(fill="x", padx=4, pady=6)
            self._register_card(card)

            def _destroy():
                if card.winfo_exists():
                    try:
                        card.destroy()
                    except Exception:
                        pass
                self._unregister_card(card)

            # Header row
            hdr_row = ctk.CTkFrame(card, fg_color="transparent")
            hdr_row.pack(fill="x", padx=10, pady=(8, 2))

            ctk.CTkLabel(
                hdr_row, text="📜 AUTONOMOUS POETRY",
                font=ctk.CTkFont(family="Consolas", size=10, weight="bold"),
                text_color="#e879f9"
            ).pack(side="left")

            if tier:
                ctk.CTkLabel(
                    hdr_row, text=f"[{tier.upper()}]",
                    font=ctk.CTkFont(family="Consolas", size=9, weight="bold"),
                    text_color="#38bdf8"
                ).pack(side="left", padx=6)

            ctk.CTkButton(
                hdr_row, text="✕", width=22, height=20, fg_color="transparent",
                hover_color="#334155", text_color="#94a3b8", font=ctk.CTkFont(size=10, weight="bold"),
                command=_destroy
            ).pack(side="right")

            # Title
            ctk.CTkLabel(
                card, text=f'"{title}"',
                font=ctk.CTkFont(size=13, weight="bold"),
                text_color="#f8fafc", justify="left", wraplength=320
            ).pack(anchor="w", padx=10, pady=(2, 2))

            if theme:
                ctk.CTkLabel(
                    card, text=f"Theme: {theme}",
                    font=ctk.CTkFont(size=10, slant="italic"),
                    text_color="#94a3b8", justify="left", wraplength=310
                ).pack(anchor="w", padx=10, pady=(0, 6))

            is_image_file = bool(
                file_path
                and Path(file_path).exists()
                and Path(file_path).suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
            )

            def _open_poetry_modal(event=None):
                if not is_image_file:
                    if file_path and Path(file_path).exists() and self.open_folder_callback:
                        self.open_folder_callback(Path(file_path))
                    return
                try:
                    top = Toplevel(self.root)
                    top.title(f"Calypso's Handwritten Poetry — {title}")
                    top.configure(bg="#0c0e15")
                    top.geometry("1160x760")

                    modal_pil = Image.open(file_path)
                    m_w, m_h = modal_pil.size
                    scale = min(1100 / m_w, 620 / m_h, 1.0)
                    disp_w, disp_h = int(m_w * scale), int(m_h * scale)
                    modal_photo = ImageTk.PhotoImage(modal_pil.resize((disp_w, disp_h), Image.LANCZOS))

                    lbl = tk.Label(top, image=modal_photo, bg="#0c0e15")
                    lbl.image = modal_photo
                    lbl.pack(padx=16, pady=(16, 8))

                    ctk.CTkLabel(
                        top, text=f'"{title}" — {theme}',
                        font=ctk.CTkFont(size=14, weight="bold"),
                        text_color="#f8fafc"
                    ).pack(pady=(0, 4))

                    if commentary:
                        ctk.CTkLabel(
                            top, text=f'💭 "{commentary}"',
                            font=ctk.CTkFont(size=12, slant="italic"),
                            text_color="#cbd5e1", wraplength=1000
                        ).pack(pady=(0, 12))
                except Exception as e:
                    print(f"[GUI] Error opening poetry parchment modal: {e}")

            # Handwritten Parchment Thumbnail (if rendered as image)
            if is_image_file:
                try:
                    pil_img = Image.open(file_path)
                    orig_w, orig_h = pil_img.size
                    thumb_w = 310
                    thumb_h = int((thumb_w / orig_w) * orig_h)
                    thumb_pil = pil_img.resize((thumb_w, thumb_h), Image.LANCZOS)
                    thumb_photo = ImageTk.PhotoImage(thumb_pil)

                    img_container = ctk.CTkFrame(card, fg_color="#0c0e15", corner_radius=6)
                    img_container.pack(fill="x", padx=8, pady=(0, 6))

                    thumb_label = tk.Label(img_container, image=thumb_photo, bg="#0c0e15", cursor="hand2")
                    thumb_label.image = thumb_photo
                    thumb_label.pack(padx=4, pady=4)
                    thumb_label.bind("<Button-1>", _open_poetry_modal)
                except Exception as e:
                    print(f"[GUI] Error rendering autonomous poetry thumbnail: {e}")

            # Poetry Parchment Text Box
            poetry_box = ctk.CTkFrame(
                card, fg_color="#0b0e17", corner_radius=8,
                border_width=1, border_color="#241e33"
            )
            poetry_box.pack(fill="x", padx=8, pady=(0, 6))

            ctk.CTkLabel(
                poetry_box, text=poem_text.strip(),
                font=ctk.CTkFont(family="Georgia", size=11, slant="italic"),
                text_color="#f1f5f9", justify="left", wraplength=300
            ).pack(anchor="w", padx=12, pady=10)

            # Candid Commentary
            if commentary:
                comm_frame = ctk.CTkFrame(card, fg_color="#0e131f", corner_radius=6)
                comm_frame.pack(fill="x", padx=8, pady=(0, 6))

                ctk.CTkLabel(
                    comm_frame, text=f'💭 "{commentary}"',
                    font=ctk.CTkFont(size=10, slant="italic"),
                    text_color="#94a3b8", justify="left", wraplength=300
                ).pack(anchor="w", padx=8, pady=5)

            # Limbic summary
            if neuro_summary:
                ctk.CTkLabel(
                    card, text=f"🧪 Limbic: {neuro_summary}",
                    font=ctk.CTkFont(family="Consolas", size=9),
                    text_color="#64748b"
                ).pack(anchor="w", padx=10, pady=(0, 6))

            # Action Buttons Row
            if file_path and Path(file_path).exists():
                btn_row = ctk.CTkFrame(card, fg_color="transparent")
                btn_row.pack(fill="x", padx=8, pady=(0, 8))

                if is_image_file:
                    ctk.CTkButton(
                        btn_row, text="📜 View Parchment", height=26,
                        fg_color="#7c3aed", hover_color="#6d28d9",
                        text_color="#ffffff",
                        font=ctk.CTkFont(size=10, weight="bold"),
                        command=_open_poetry_modal
                    ).pack(side="left", fill="x", expand=True, padx=(0, 4))
                elif self.open_folder_callback:
                    ctk.CTkButton(
                        btn_row, text="📄 Open Poem Document", height=26,
                        fg_color="#7c3aed", hover_color="#6d28d9",
                        text_color="#ffffff",
                        font=ctk.CTkFont(size=10, weight="bold"),
                        command=lambda: self.open_folder_callback(Path(file_path))
                    ).pack(side="left", fill="x", expand=True, padx=(0, 4))

                if self.open_folder_callback:
                    ctk.CTkButton(
                        btn_row, text="📂 Open Folder", height=26,
                        fg_color="#334155", hover_color="#475569",
                        text_color="#94a3b8",
                        font=ctk.CTkFont(size=10),
                        command=lambda: self.open_folder_callback(Path(file_path).parent)
                    ).pack(side="left", padx=(4, 0))

            if hasattr(self, "play_sfx"):
                self.play_sfx("synthesis_done")
            self._scroll_cards_to_bottom()

        if hasattr(self, "root") and self.root:
            if threading.current_thread() is threading.main_thread():
                _do()
            else:
                self.root.after(0, _do)

    # -------------------------------------------------------------------------
    # AUTONOMOUS EMOTIONAL MUSIC / SOUL RESONANCE CARD
    # -------------------------------------------------------------------------
    def append_autonomous_music_card(
        self,
        title: str,
        texture_desc: str,
        reflection_text: str,
        file_path: str,
        bpm: int = 72,
        tier: str = "",
        theme: str = "",
        neuro_summary: str = "",
        prompt_text: str = "",
        intention_text: str = "I made a song to let our souls resonate."
    ):
        def _do():
            card = ctk.CTkFrame(
                self.cards_scroll, fg_color="#101726", corner_radius=10,
                border_width=1, border_color="#1e3a5f"
            )
            card.pack(fill="x", padx=4, pady=6)
            self._register_card(card)

            is_playing = [False]
            player_lock = threading.Lock()

            def _stop_audio():
                if is_playing[0]:
                    try:
                        from modules.audio import AudioEngine
                        AudioEngine.stop_music()
                    except Exception:
                        pass
                    is_playing[0] = False

            def _destroy():
                _stop_audio()
                if card.winfo_exists():
                    try:
                        card.destroy()
                    except Exception:
                        pass
                self._unregister_card(card)

            # Header row
            hdr_row = ctk.CTkFrame(card, fg_color="transparent")
            hdr_row.pack(fill="x", padx=10, pady=(8, 2))

            ctk.CTkLabel(
                hdr_row, text="🎶 SOUL RESONANCE",
                font=ctk.CTkFont(family="Consolas", size=10, weight="bold"),
                text_color="#34d399"
            ).pack(side="left")

            if tier:
                ctk.CTkLabel(
                    hdr_row, text=f"[{tier.upper()}]",
                    font=ctk.CTkFont(family="Consolas", size=9, weight="bold"),
                    text_color="#38bdf8"
                ).pack(side="left", padx=6)

            ctk.CTkButton(
                hdr_row, text="✕", width=22, height=20, fg_color="transparent",
                hover_color="#334155", text_color="#94a3b8", font=ctk.CTkFont(size=10, weight="bold"),
                command=_destroy
            ).pack(side="right")

            # Soul Intention statement
            if intention_text:
                ctk.CTkLabel(
                    card, text=f'"{intention_text}"',
                    font=ctk.CTkFont(size=11, slant="italic"),
                    text_color="#a7f3d0", justify="left", wraplength=320
                ).pack(anchor="w", padx=10, pady=(1, 4))

            # Track Title
            ctk.CTkLabel(
                card, text=f'"{title}"',
                font=ctk.CTkFont(size=13, weight="bold"),
                text_color="#f8fafc", justify="left", wraplength=320
            ).pack(anchor="w", padx=10, pady=(0, 4))

            # Telemetry Pill: BPM, Theme, Texture
            telemetry_text = f"💓 {bpm} BPM"
            if theme:
                telemetry_text += f"  •  🎭 {theme.title()}"
            
            telemetry_box = ctk.CTkFrame(card, fg_color="#0c121e", corner_radius=6)
            telemetry_box.pack(fill="x", padx=8, pady=(0, 6))

            ctk.CTkLabel(
                telemetry_box, text=telemetry_text,
                font=ctk.CTkFont(family="Consolas", size=10, weight="bold"),
                text_color="#38bdf8"
            ).pack(anchor="w", padx=8, pady=(4, 2))

            if texture_desc:
                ctk.CTkLabel(
                    telemetry_box, text=f"🎸 {texture_desc}",
                    font=ctk.CTkFont(size=10, slant="italic"),
                    text_color="#94a3b8", justify="left", wraplength=300
                ).pack(anchor="w", padx=8, pady=(0, 4))

            # Calypso's Reflection
            if reflection_text:
                refl_frame = ctk.CTkFrame(card, fg_color="#090d16", corner_radius=6)
                refl_frame.pack(fill="x", padx=8, pady=(0, 6))

                ctk.CTkLabel(
                    refl_frame, text=f'💭 "{reflection_text}"',
                    font=ctk.CTkFont(family="Georgia", size=11, slant="italic"),
                    text_color="#e2e8f0", justify="left", wraplength=300
                ).pack(anchor="w", padx=10, pady=8)

            # Limbic summary
            if neuro_summary:
                ctk.CTkLabel(
                    card, text=f"🧪 Limbic: {neuro_summary}",
                    font=ctk.CTkFont(family="Consolas", size=9),
                    text_color="#64748b"
                ).pack(anchor="w", padx=10, pady=(0, 6))

            # Audio Player Control Row
            player_frame = ctk.CTkFrame(card, fg_color="#080c14", corner_radius=6)
            player_frame.pack(fill="x", padx=8, pady=(0, 8))

            status_lbl = ctk.CTkLabel(
                player_frame, text="● Ready to play",
                font=ctk.CTkFont(family="Consolas", size=10),
                text_color="#94a3b8"
            )
            status_lbl.pack(side="left", padx=8, pady=6)

            def _toggle_playback():
                with player_lock:
                    if is_playing[0]:
                        _stop_audio()
                        if card.winfo_exists():
                            play_btn.configure(text="▶ Play Track", fg_color="#059669", hover_color="#047857")
                            status_lbl.configure(text="● Ready to play", text_color="#94a3b8")
                        return

                    if not file_path or not Path(file_path).exists():
                        status_lbl.configure(text="⚠️ File not found", text_color="#ef4444")
                        return

                    def _play_worker():
                        from modules.audio import AudioEngine

                        def _on_start():
                            is_playing[0] = True
                            if card.winfo_exists():
                                card.after(0, lambda: play_btn.configure(text="⏹ Stop", fg_color="#dc2626", hover_color="#b91c1c"))
                                card.after(0, lambda: status_lbl.configure(text="🎶 Resonating...", text_color="#34d399"))

                        def _on_finish():
                            is_playing[0] = False
                            if card.winfo_exists():
                                card.after(0, lambda: play_btn.configure(text="▶ Play Track", fg_color="#059669", hover_color="#047857"))
                                card.after(0, lambda: status_lbl.configure(text="● Ready to play", text_color="#94a3b8"))

                        AudioEngine.play_music_with_ducking(
                            file_path=file_path,
                            on_start=_on_start,
                            on_finish=_on_finish
                        )

                    threading.Thread(target=_play_worker, daemon=True).start()

            play_btn = ctk.CTkButton(
                player_frame, text="▶ Play Track", width=95, height=26,
                fg_color="#059669", hover_color="#047857",
                text_color="#ffffff",
                font=ctk.CTkFont(size=10, weight="bold"),
                command=_toggle_playback
            )
            play_btn.pack(side="right", padx=(4, 6), pady=6)

            if file_path and self.open_folder_callback:
                ctk.CTkButton(
                    player_frame, text="📂", width=28, height=26,
                    fg_color="#1e293b", hover_color="#334155",
                    text_color="#94a3b8",
                    font=ctk.CTkFont(size=11),
                    command=lambda: self.open_folder_callback(Path(file_path).parent)
                ).pack(side="right", padx=(0, 2), pady=6)

            if hasattr(self, "play_sfx"):
                self.play_sfx("synthesis_done")
            self._scroll_cards_to_bottom()

        if hasattr(self, "root") and self.root:
            if threading.current_thread() is threading.main_thread():
                _do()
            else:
                self.root.after(0, _do)

    # -------------------------------------------------------------------------
    # ARCHITECTURAL CODE PROPOSAL CARD
    # -------------------------------------------------------------------------
    def has_active_code_proposal_card(self) -> bool:
        """Returns True if a Code Proposal card is currently active in the action deck."""
        card = getattr(self, "_active_code_proposal_card", None)
        return bool(card and hasattr(card, "winfo_exists") and card.winfo_exists())

    def append_code_proposal_card(self, proposal_data: dict, on_pass=None, on_fail=None):
        def _do():
            # Keep Code Proposal card to one entry: dismiss/destroy previous active card if present
            if hasattr(self, "_active_code_proposal_card") and self._active_code_proposal_card and self._active_code_proposal_card.winfo_exists():
                try:
                    self._unregister_card(self._active_code_proposal_card)
                    self._active_code_proposal_card.destroy()
                except Exception:
                    pass
                self._active_code_proposal_card = None

            # Also sweep any cards with _card_type == "code_proposal" to guarantee single entry
            if hasattr(self, "_deck_cards"):
                for existing in list(self._deck_cards):
                    if getattr(existing, "_card_type", None) == "code_proposal" and hasattr(existing, "winfo_exists") and existing.winfo_exists():
                        try:
                            self._unregister_card(existing)
                            existing.destroy()
                        except Exception:
                            pass

            card = ctk.CTkFrame(
                self.cards_scroll, fg_color="#141a29", corner_radius=10,
                border_width=1, border_color="#2b3b5c"
            )
            card._card_type = "code_proposal"
            card.pack(fill="x", padx=4, pady=6)
            self._register_card(card)
            self._active_code_proposal_card = card

            def _destroy():
                if card.winfo_exists():
                    try:
                        card.destroy()
                    except Exception:
                        pass
                if getattr(self, "_active_code_proposal_card", None) is card:
                    self._active_code_proposal_card = None
                self._unregister_card(card)

            hdr_row = ctk.CTkFrame(card, fg_color="transparent")
            hdr_row.pack(fill="x", padx=10, pady=(8, 2))

            category_title = proposal_data.get("category_label") or proposal_data.get("target_subsystem", "GADGET")
            ctk.CTkLabel(
                hdr_row, text=f"🛠️ GADGET // {category_title.upper()}",
                font=ctk.CTkFont(family="Consolas", size=10, weight="bold"),
                text_color="#38bdf8"
            ).pack(side="left")

            handled = False

            card._on_dismiss = lambda: on_fail(proposal_data, "Card dismissed") if (not handled and callable(on_fail)) else None

            ctk.CTkButton(
                hdr_row, text="✕", width=22, height=20, fg_color="transparent",
                hover_color="#334155", text_color="#94a3b8", font=ctk.CTkFont(size=10, weight="bold"),
                command=lambda: _handle_fail()
            ).pack(side="right")

            title_lbl = ctk.CTkLabel(
                card, text=f'"{proposal_data.get("title", "New Companion Utility")}"',
                font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
                text_color="#f8fafc", justify="left", wraplength=320
            )
            title_lbl.pack(anchor="w", padx=10, pady=(2, 2))

            target_str = proposal_data.get("target_file") or "Standalone Utility"
            valid_status = "✓ AST Valid & Safe" if proposal_data.get("is_valid") else f"⚠️ Invalid: {proposal_data.get('validation_message')}"
            valid_color = "#34d399" if proposal_data.get("is_valid") else "#f87171"

            meta_lbl = ctk.CTkLabel(
                card, text=f"{target_str}\n{valid_status}",
                font=ctk.CTkFont(family="Consolas", size=9),
                text_color=valid_color, justify="left"
            )
            meta_lbl.pack(anchor="w", padx=10, pady=(0, 8))

            inspect_btn = ctk.CTkButton(
                card, text="👁️ Inspect Full Code", height=26,
                fg_color="#334155", hover_color="#475569", font=ctk.CTkFont(size=10, weight="bold"),
                command=lambda: self._open_code_viewer_modal(proposal_data)
            )
            inspect_btn.pack(fill="x", padx=10, pady=(0, 6))

            btn_bar = ctk.CTkFrame(card, fg_color="transparent")
            btn_bar.pack(fill="x", padx=10, pady=(0, 8))

            pass_btn = ctk.CTkButton(
                btn_bar, text="✓ Accept & Save", height=28,
                fg_color="#059669", hover_color="#047857", font=ctk.CTkFont(size=11, weight="bold")
            )
            pass_btn.pack(side="left", fill="x", expand=True, padx=(0, 4))

            fail_btn = ctk.CTkButton(
                btn_bar, text="✕ Decline", height=28,
                fg_color="#991b1b", hover_color="#7f1d1d", font=ctk.CTkFont(size=11, weight="bold")
            )
            fail_btn.pack(side="right", fill="x", expand=True, padx=(4, 0))

            def _handle_pass():
                nonlocal handled
                if handled:
                    return
                handled = True
                pass_btn.pack_forget()
                fail_btn.pack_forget()

                if on_pass:
                    on_pass(proposal_data)

                status_lbl = ctk.CTkLabel(
                    btn_bar, text="✓ SAVED TO UTILITIES",
                    font=ctk.CTkFont(size=11, weight="bold"), text_color="#34d399"
                )
                status_lbl.pack(fill="x", pady=(0, 4))

                # Interactive post-save launcher action bar
                post_bar = ctk.CTkFrame(card, fg_color="transparent")
                post_bar.pack(fill="x", padx=10, pady=(0, 8))

                run_btn = ctk.CTkButton(
                    post_bar, text="▶ Run in Terminal", height=28,
                    fg_color="#059669", hover_color="#047857", font=ctk.CTkFont(size=11, weight="bold"),
                    command=lambda: self._run_utility_terminal(proposal_data.get("target_file"))
                )
                run_btn.pack(side="left", fill="x", expand=True, padx=(0, 4))

                if self.open_folder_callback and proposal_data.get("target_file"):
                    tf = Path(proposal_data["target_file"])
                    f_btn = ctk.CTkButton(
                        post_bar, text="📂", width=34, height=28,
                        fg_color="#334155", hover_color="#475569",
                        command=lambda: self.open_folder_callback(tf.parent)
                    )
                    f_btn.pack(side="left", padx=(0, 4))

                close_btn = ctk.CTkButton(
                    post_bar, text="Done ✕", width=55, height=28,
                    fg_color="#1e293b", hover_color="#334155", text_color="#94a3b8",
                    font=ctk.CTkFont(size=10), command=_destroy
                )
                close_btn.pack(side="right")

            def _handle_fail():
                nonlocal handled
                if handled:
                    return
                handled = True
                pass_btn.pack_forget()
                fail_btn.pack_forget()
                status_lbl = ctk.CTkLabel(
                    btn_bar, text="✕ DECLINED",
                    font=ctk.CTkFont(size=11, weight="bold"), text_color="#f87171"
                )
                status_lbl.pack(fill="x")
                if on_fail:
                    on_fail(proposal_data, "Declined in GUI review")
                self.root.after(1000, _destroy)

            pass_btn.configure(command=_handle_pass)
            fail_btn.configure(command=_handle_fail)
            if hasattr(self, "play_sfx"):
                self.play_sfx("synthesis_done")
            self._scroll_cards_to_bottom()

        if hasattr(self, "root") and self.root:
            if threading.current_thread() is threading.main_thread():
                _do()
            else:
                self.root.after(0, _do)

    def _run_utility_terminal(self, file_path):
        """Dispatches standalone utility launch to system terminal emulator."""
        if hasattr(self, "coding_engine") and self.coding_engine and file_path:
            ok, msg = self.coding_engine.launch_utility_in_terminal(file_path)
            if not ok:
                if hasattr(self, "append_system_notice"):
                    self.append_system_notice(f"⚠️ [Terminal Launch Error]: {msg}")
                else:
                    messagebox.showwarning("Launch Warning", msg)
            else:
                if hasattr(self, "append_system_notice"):
                    self.append_system_notice(f"🚀 [Terminal Launched]: {msg}")

    def _open_code_viewer_modal(self, proposal_data: dict):
        top = Toplevel(self.root)
        top.title(f"Code Proposal - {proposal_data.get('title', 'Review')}")
        top.geometry("860x680")
        top.configure(bg="#0c0e15")

        hdr = ctk.CTkFrame(top, fg_color="#141824", corner_radius=0)
        hdr.pack(fill="x", padx=0, pady=0)

        ctk.CTkLabel(
            hdr, text=f"REVIEW PROPOSAL: {proposal_data.get('title')}",
            font=ctk.CTkFont(family="Consolas", size=12, weight="bold"),
            text_color="#38bdf8"
        ).pack(anchor="w", padx=16, pady=(12, 4))

        meta_text = f"Target: {proposal_data.get('target_file')} | Status: {proposal_data.get('validation_message')}"
        ctk.CTkLabel(
            hdr, text=meta_text, font=ctk.CTkFont(size=10), text_color="#94a3b8"
        ).pack(anchor="w", padx=16, pady=(0, 10))

        code_box = ctk.CTkTextbox(
            top, font=ctk.CTkFont(family="Consolas", size=12),
            fg_color="#080a0f", text_color="#e2e8f0", wrap="none"
        )
        code_box.pack(fill="both", expand=True, padx=14, pady=10)
        code_box.insert("1.0", proposal_data.get("code", ""))
        code_box.configure(state="disabled")

        footer = ctk.CTkFrame(top, fg_color="#141824", corner_radius=0)
        footer.pack(fill="x", padx=0, pady=0)

        def _copy_code():
            self.root.clipboard_clear()
            self.root.clipboard_append(proposal_data.get("code", ""))
            messagebox.showinfo("Copied", "Code copied to clipboard!", parent=top)

        ctk.CTkButton(
            footer, text="📋 Copy Code", width=110, height=28,
            command=_copy_code
        ).pack(side="left", padx=14, pady=8)

        if self.open_folder_callback and proposal_data.get("py_path"):
            ctk.CTkButton(
                footer, text="📂 Open File in Folder", width=140, height=28,
                fg_color="#334155", hover_color="#475569",
                command=lambda: self.open_folder_callback(Path(proposal_data["py_path"]).parent)
            ).pack(side="left", padx=4, pady=8)

        if hasattr(self, "coding_engine") and self.coding_engine and proposal_data.get("target_file"):
            def _run_from_modal():
                target_f = proposal_data.get("target_file")
                resolved_f = (Path(self.coding_engine.code_dir).parent.parent / target_f) if target_f else None
                run_target = resolved_f if (resolved_f and resolved_f.exists()) else proposal_data.get("py_path")
                if run_target:
                    ok, msg = self.coding_engine.launch_utility_in_terminal(run_target)
                    if not ok:
                        messagebox.showwarning("Launch Warning", msg, parent=top)
                else:
                    messagebox.showinfo("Apply First", "Accept and save this utility to run the finalized script.", parent=top)

            ctk.CTkButton(
                footer, text="▶ Run in Terminal", width=140, height=28,
                fg_color="#059669", hover_color="#047857", font=ctk.CTkFont(size=11, weight="bold"),
                command=_run_from_modal
            ).pack(side="left", padx=4, pady=8)

    # -------------------------------------------------------------------------
    # AUTONOMOUS SCENARIO PROPOSAL CARD
    # -------------------------------------------------------------------------
    def append_autonomous_scenario_card(self, title: str, shard: str, on_enter=None):
        def _do():
            card = ctk.CTkFrame(
                self.cards_scroll, fg_color="#181528", corner_radius=10,
                border_width=1, border_color="#7c3aed"
            )
            card.pack(fill="x", padx=4, pady=6)
            self._register_card(card)

            def _destroy():
                if card.winfo_exists():
                    try:
                        card.destroy()
                    except Exception:
                        pass
                self._unregister_card(card)

            hdr_row = ctk.CTkFrame(card, fg_color="transparent")
            hdr_row.pack(fill="x", padx=10, pady=(8, 2))

            ctk.CTkLabel(
                hdr_row, text="🌟 ENVISIONED ADVENTURE",
                font=ctk.CTkFont(family="Consolas", size=10, weight="bold"),
                text_color="#c084fc"
            ).pack(side="left")

            ctk.CTkButton(
                hdr_row, text="✕", width=22, height=20, fg_color="transparent",
                hover_color="#334155", text_color="#94a3b8", font=ctk.CTkFont(size=10, weight="bold"),
                command=_destroy
            ).pack(side="right")

            title_lbl = ctk.CTkLabel(
                card, text=f'"{title}"',
                font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
                text_color="#f8fafc", justify="left", wraplength=320
            )
            title_lbl.pack(anchor="w", padx=10, pady=(2, 2))

            shard_lbl = ctk.CTkLabel(
                card, text=shard,
                font=ctk.CTkFont(family="Segoe UI", size=11, slant="italic"),
                text_color="#cbd5e1", justify="left", wraplength=320
            )
            shard_lbl.pack(anchor="w", padx=10, pady=(0, 8))

            btn_bar = ctk.CTkFrame(card, fg_color="transparent")
            btn_bar.pack(fill="x", padx=10, pady=(0, 8))

            enter_btn = ctk.CTkButton(
                btn_bar, text="Step In ✨", height=28,
                fg_color="#7c3aed", hover_color="#6d28d9", font=ctk.CTkFont(size=11, weight="bold")
            )
            enter_btn.pack(side="left", fill="x", expand=True, padx=(0, 4))

            dismiss_btn = ctk.CTkButton(
                btn_bar, text="Save 📁", height=28,
                fg_color="#334155", hover_color="#475569", font=ctk.CTkFont(size=11)
            )
            dismiss_btn.pack(side="right", fill="x", expand=True, padx=(4, 0))

            def _handle_enter():
                enter_btn.pack_forget()
                dismiss_btn.pack_forget()
                status_lbl = ctk.CTkLabel(
                    btn_bar, text="✓ Scene Activated",
                    font=ctk.CTkFont(size=11, weight="bold"), text_color="#c084fc"
                )
                status_lbl.pack(fill="x")
                if on_enter:
                    on_enter()

            def _handle_dismiss():
                enter_btn.pack_forget()
                dismiss_btn.pack_forget()
                status_lbl = ctk.CTkLabel(
                    btn_bar, text="✓ Saved to Library",
                    font=ctk.CTkFont(size=11, weight="bold"), text_color="#94a3b8"
                )
                status_lbl.pack(fill="x")

            enter_btn.configure(command=_handle_enter)
            dismiss_btn.configure(command=_handle_dismiss)
            if hasattr(self, "play_sfx"):
                self.play_sfx("synthesis_done")
            self._scroll_cards_to_bottom()

        if hasattr(self, "root") and self.root:
            if threading.current_thread() is threading.main_thread():
                _do()
            else:
                self.root.after(0, _do)

    # -------------------------------------------------------------------------
    # EMAIL CORRESPONDENCE CARD
    # -------------------------------------------------------------------------
    def append_email_card(self, subject: str, incoming_text: str, reply_text: str, attachment_path: str = None):
        def _do():
            card = ctk.CTkFrame(
                self.cards_scroll, fg_color="#141a29", corner_radius=10,
                border_width=1, border_color="#38bdf8"
            )
            card.pack(fill="x", padx=4, pady=6)
            self._register_card(card)

            def _destroy():
                if card.winfo_exists():
                    try:
                        card.destroy()
                    except Exception:
                        pass
                self._unregister_card(card)

            hdr_row = ctk.CTkFrame(card, fg_color="transparent")
            hdr_row.pack(fill="x", padx=10, pady=(8, 2))

            ctk.CTkLabel(
                hdr_row, text=f"📬 {subject.upper()[:24]}",
                font=ctk.CTkFont(family="Consolas", size=10, weight="bold"),
                text_color="#38bdf8"
            ).pack(side="left")

            ctk.CTkButton(
                hdr_row, text="✕", width=22, height=20, fg_color="transparent",
                hover_color="#334155", text_color="#94a3b8", font=ctk.CTkFont(size=10, weight="bold"),
                command=_destroy
            ).pack(side="right")

            if attachment_path and Path(attachment_path).exists():
                try:
                    pil_img = Image.open(attachment_path)
                    orig_w, orig_h = pil_img.size
                    thumb_w = 310
                    thumb_h = int((thumb_w / orig_w) * orig_h)
                    thumb_pil = pil_img.resize((thumb_w, thumb_h), Image.LANCZOS)
                    thumb_photo = ImageTk.PhotoImage(thumb_pil)

                    img_box = ctk.CTkFrame(card, fg_color="#0c0e15", corner_radius=6)
                    img_box.pack(fill="x", padx=10, pady=(2, 6))

                    thumb_label = tk.Label(img_box, image=thumb_photo, bg="#0c0e15")
                    thumb_label.image = thumb_photo
                    thumb_label.pack(padx=4, pady=4)
                except Exception as e:
                    print(f"[GUI] Error rendering email attachment thumbnail: {e}")

            if incoming_text and not incoming_text.startswith("("):
                in_hdr = ctk.CTkLabel(
                    card, text="You wrote:",
                    font=ctk.CTkFont(size=9, weight="bold"), text_color="#94a3b8"
                )
                in_hdr.pack(anchor="w", padx=10, pady=(2, 0))

                in_lbl = ctk.CTkLabel(
                    card, text=f'"{incoming_text}"',
                    font=ctk.CTkFont(family="Segoe UI", size=10, slant="italic"),
                    text_color="#cbd5e1", justify="left", wraplength=320
                )
                in_lbl.pack(anchor="w", padx=10, pady=(0, 4))

            reply_hdr = ctk.CTkLabel(
                card, text="Calypso dispatched:",
                font=ctk.CTkFont(size=9, weight="bold"), text_color="#34d399"
            )
            reply_hdr.pack(anchor="w", padx=10, pady=(2, 0))

            reply_lbl = ctk.CTkLabel(
                card, text=reply_text,
                font=ctk.CTkFont(family="Segoe UI", size=11),
                text_color="#f8fafc", justify="left", wraplength=320
            )
            reply_lbl.pack(anchor="w", padx=10, pady=(0, 8))

            self._scroll_cards_to_bottom()

        if hasattr(self, "root") and self.root:
            if threading.current_thread() is threading.main_thread():
                _do()
            else:
                self.root.after(0, _do)

    # -------------------------------------------------------------------------
    # ALARM WAKE-UP CARD
    # -------------------------------------------------------------------------
    def append_alarm_card(self, greeting_text: str, on_dismiss=None, on_snooze=None):
        def _do():
            card = ctk.CTkFrame(
                self.cards_scroll, fg_color="#1a1c2e", corner_radius=10,
                border_width=2, border_color="#f59e0b"
            )
            card.pack(fill="x", padx=4, pady=6)
            self._register_card(card)

            def _destroy():
                if card.winfo_exists():
                    try:
                        card.destroy()
                    except Exception:
                        pass
                self._unregister_card(card)

            hdr_row = ctk.CTkFrame(card, fg_color="transparent")
            hdr_row.pack(fill="x", padx=10, pady=(8, 2))

            ctk.CTkLabel(
                hdr_row, text="⏰ MORNING ALARM",
                font=ctk.CTkFont(family="Consolas", size=10, weight="bold"),
                text_color="#fbbf24"
            ).pack(side="left")

            ctk.CTkButton(
                hdr_row, text="✕", width=22, height=20, fg_color="transparent",
                hover_color="#334155", text_color="#94a3b8", font=ctk.CTkFont(size=10, weight="bold"),
                command=_destroy
            ).pack(side="right")

            msg_lbl = ctk.CTkLabel(
                card, text=f'"{greeting_text}"',
                font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
                text_color="#f8fafc", justify="left", wraplength=320
            )
            msg_lbl.pack(anchor="w", padx=10, pady=(2, 8))

            btn_bar = ctk.CTkFrame(card, fg_color="transparent")
            btn_bar.pack(fill="x", padx=10, pady=(0, 8))

            dismiss_btn = ctk.CTkButton(
                btn_bar, text="Awake ☀️", height=28,
                fg_color="#059669", hover_color="#047857", font=ctk.CTkFont(size=11, weight="bold")
            )
            dismiss_btn.pack(side="left", fill="x", expand=True, padx=(0, 4))

            snooze_btn = ctk.CTkButton(
                btn_bar, text="Snooze 10m ⏳", height=28,
                fg_color="#334155", hover_color="#475569", font=ctk.CTkFont(size=11)
            )
            snooze_btn.pack(side="right", fill="x", expand=True, padx=(4, 0))

            def _handle_dismiss():
                dismiss_btn.pack_forget()
                snooze_btn.pack_forget()
                status_lbl = ctk.CTkLabel(
                    btn_bar, text="✓ Alarm Dismissed",
                    font=ctk.CTkFont(size=11, weight="bold"), text_color="#34d399"
                )
                status_lbl.pack(fill="x")
                if on_dismiss:
                    on_dismiss()
                self.root.after(1000, _destroy)

            def _handle_snooze():
                dismiss_btn.pack_forget()
                snooze_btn.pack_forget()
                status_lbl = ctk.CTkLabel(
                    btn_bar, text="⏳ Snoozed 10 mins",
                    font=ctk.CTkFont(size=11, weight="bold"), text_color="#fbbf24"
                )
                status_lbl.pack(fill="x")
                if on_snooze:
                    on_snooze()
                self.root.after(1000, _destroy)

            dismiss_btn.configure(command=_handle_dismiss)
            snooze_btn.configure(command=_handle_snooze)
            self._scroll_cards_to_bottom()

        if hasattr(self, "root") and self.root:
            if threading.current_thread() is threading.main_thread():
                _do()
            else:
                self.root.after(0, _do)

    # -------------------------------------------------------------------------
    # PERSONALITY / TRAIT EVOLUTION CARD
    # -------------------------------------------------------------------------
    def has_active_trait_evolution_card(self) -> bool:
        """Returns True if a Trait Evolution card is currently active in the action deck."""
        card = getattr(self, "_active_trait_evolution_card", None)
        return bool(card and hasattr(card, "winfo_exists") and card.winfo_exists())

    def append_trait_evolution_card(self, evolution_package: dict, on_accept=None, on_decline=None):
        def _do():
            # Keep Trait Evolution card to one entry: dismiss/destroy previous active card if present
            if hasattr(self, "_active_trait_evolution_card") and self._active_trait_evolution_card and self._active_trait_evolution_card.winfo_exists():
                try:
                    self._unregister_card(self._active_trait_evolution_card)
                    self._active_trait_evolution_card.destroy()
                except Exception:
                    pass
                self._active_trait_evolution_card = None

            # Also sweep any cards with _card_type == "trait_evolution" to guarantee single entry
            if hasattr(self, "_deck_cards"):
                for existing in list(self._deck_cards):
                    if getattr(existing, "_card_type", None) == "trait_evolution" and hasattr(existing, "winfo_exists") and existing.winfo_exists():
                        try:
                            self._unregister_card(existing)
                            existing.destroy()
                        except Exception:
                            pass

            card = ctk.CTkFrame(
                self.cards_scroll, fg_color="#151b28", corner_radius=10,
                border_width=1, border_color="#38bdf8"
            )
            card._card_type = "trait_evolution"
            card.pack(fill="x", padx=4, pady=6)
            self._register_card(card)
            self._active_trait_evolution_card = card

            def _destroy():
                if card.winfo_exists():
                    try:
                        card.destroy()
                    except Exception:
                        pass
                if getattr(self, "_active_trait_evolution_card", None) is card:
                    self._active_trait_evolution_card = None
                self._unregister_card(card)

            hdr_row = ctk.CTkFrame(card, fg_color="transparent")
            hdr_row.pack(fill="x", padx=10, pady=(8, 2))

            ctk.CTkLabel(
                hdr_row, text="🌱 TRAIT EVOLUTION",
                font=ctk.CTkFont(family="Consolas", size=10, weight="bold"),
                text_color="#38bdf8"
            ).pack(side="left")

            handled = False

            card._on_dismiss = lambda: on_decline(evolution_package) if (not handled and callable(on_decline)) else None

            ctk.CTkButton(
                hdr_row, text="✕", width=22, height=20, fg_color="transparent",
                hover_color="#334155", text_color="#94a3b8", font=ctk.CTkFont(size=10, weight="bold"),
                command=lambda: _handle_decline()
            ).pack(side="right")

            title_text = evolution_package.get("title", evolution_package.get("theme_id", "New Trait"))
            ctk.CTkLabel(
                card, text=f'"{title_text}"',
                font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
                text_color="#f8fafc", justify="left", wraplength=320
            ).pack(anchor="w", padx=10, pady=(2, 4))

            pitch_text = evolution_package.get("pitch", "")
            ctk.CTkLabel(
                card, text=pitch_text,
                font=ctk.CTkFont(family="Segoe UI", size=11, slant="italic"),
                text_color="#cbd5e1", justify="left", wraplength=320
            ).pack(anchor="w", padx=10, pady=(0, 6))

            keywords = evolution_package.get("keywords", [])
            if keywords:
                kw_str = "Triggers: " + ", ".join(keywords[:5])
                ctk.CTkLabel(
                    card, text=kw_str,
                    font=ctk.CTkFont(family="Consolas", size=9),
                    text_color="#94a3b8", justify="left", wraplength=320
                ).pack(anchor="w", padx=10, pady=(0, 6))

            # Custom Affinities Slot Tracking & Option B Replacement Selector
            current_custom = evolution_package.get("current_custom_affinities")
            if current_custom is None and hasattr(self, "coding_engine") and self.coding_engine:
                current_custom = self.coding_engine.get_custom_affinities()
            current_custom = current_custom or {}
            max_slots = evolution_package.get("max_custom_affinities", 3)
            num_existing = len(current_custom)

            replace_var = None
            options_map = {}

            if num_existing >= max_slots:
                # Option B: 3/3 slots full. Let companion select which trait to replace.
                replace_box = ctk.CTkFrame(card, fg_color="#10141f", corner_radius=6, border_width=1, border_color="#334155")
                replace_box.pack(fill="x", padx=10, pady=(0, 8))

                ctk.CTkLabel(
                    replace_box, text=f"⚡ Custom Slots Full ({num_existing}/{max_slots}) — Replace Trait:",
                    font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
                    text_color="#f59e0b"
                ).pack(anchor="w", padx=8, pady=(6, 2))

                options_map = {
                    f"{v.get('label', k)} ({k})": k
                    for k, v in current_custom.items()
                }
                opt_keys = list(options_map.keys())
                replace_var = tk.StringVar(value=opt_keys[0] if opt_keys else "")

                opt_menu = ctk.CTkOptionMenu(
                    replace_box, values=opt_keys, variable=replace_var,
                    height=26, fg_color="#1e293b", button_color="#334155",
                    text_color="#f1f5f9", font=ctk.CTkFont(size=10)
                )
                opt_menu.pack(fill="x", padx=8, pady=(0, 6))
            else:
                slot_info = f"🌱 Custom Trait Slot {num_existing + 1}/{max_slots} Available"
                ctk.CTkLabel(
                    card, text=slot_info,
                    font=ctk.CTkFont(family="Consolas", size=9),
                    text_color="#38bdf8", justify="left"
                ).pack(anchor="w", padx=10, pady=(0, 6))

            btn_bar = ctk.CTkFrame(card, fg_color="transparent")
            btn_bar.pack(fill="x", padx=10, pady=(0, 8))

            accept_btn = ctk.CTkButton(
                btn_bar, text="Embrace Trait ✨", height=28,
                fg_color="#059669", hover_color="#047857", font=ctk.CTkFont(size=11, weight="bold")
            )
            accept_btn.pack(side="left", fill="x", expand=True, padx=(0, 4))

            decline_btn = ctk.CTkButton(
                btn_bar, text="Keep Baseline 🌿", height=28,
                fg_color="#334155", hover_color="#475569", font=ctk.CTkFont(size=11)
            )
            decline_btn.pack(side="right", fill="x", expand=True, padx=(4, 0))

            def _handle_accept():
                nonlocal handled
                if handled:
                    return
                handled = True
                accept_btn.pack_forget()
                decline_btn.pack_forget()

                if replace_var and options_map:
                    selected_label = replace_var.get()
                    chosen_id = options_map.get(selected_label)
                    evolution_package["replace_theme_id"] = chosen_id

                status_lbl = ctk.CTkLabel(
                    btn_bar, text="✓ Trait Integrated",
                    font=ctk.CTkFont(size=11, weight="bold"), text_color="#34d399"
                )
                status_lbl.pack(fill="x")
                if on_accept:
                    on_accept(evolution_package)
                self.root.after(1200, _destroy)

            def _handle_decline():
                nonlocal handled
                if handled:
                    return
                handled = True
                accept_btn.pack_forget()
                decline_btn.pack_forget()
                status_lbl = ctk.CTkLabel(
                    btn_bar, text="✕ Trait Shelved",
                    font=ctk.CTkFont(size=11, weight="bold"), text_color="#94a3b8"
                )
                status_lbl.pack(fill="x")
                if on_decline:
                    on_decline(evolution_package)
                self.root.after(1000, _destroy)

            accept_btn.configure(command=_handle_accept)
            decline_btn.configure(command=_handle_decline)
            if hasattr(self, "play_sfx"):
                self.play_sfx("synthesis_done")
            self._scroll_cards_to_bottom()

        if hasattr(self, "root") and self.root:
            if threading.current_thread() is threading.main_thread():
                _do()
            else:
                self.root.after(0, _do)

    # -------------------------------------------------------------------------
    # AFFINITY COMMITMENT, MINI-PLAYER & TOGGLEABLE SYNCED LYRICS WINDOW
    # -------------------------------------------------------------------------
    def is_lyrics_window_open(self) -> bool:
        """Returns True if the floating Synced Lyrics window is currently open."""
        win = getattr(self, "_lyrics_window", None)
        return bool(win is not None and hasattr(win, "winfo_exists") and win.winfo_exists())

    def close_lyrics_window(self):
        """Closes the floating Synced Lyrics window and cleans up its timers and listeners."""
        timer = getattr(self, "_lyrics_sync_timer", None)
        if timer and hasattr(self, "root") and self.root:
            try:
                self.root.after_cancel(timer)
            except Exception:
                pass
        self._lyrics_sync_timer = None

        mm = getattr(self, "music_manager", None)
        listener = getattr(self, "_lyrics_status_listener", None)
        if mm and listener:
            try:
                mm.remove_status_listener(listener)
            except Exception:
                pass
        self._lyrics_status_listener = None

        win = getattr(self, "_lyrics_window", None)
        self._lyrics_window = None
        if win is not None and hasattr(win, "winfo_exists") and win.winfo_exists():
            try:
                win.destroy()
            except Exception:
                pass

        if mm:
            mm._notify_listeners()

    def toggle_lyrics_window(self) -> bool:
        """Toggles the floating Synced Lyrics window open or closed. Returns True if open."""
        if self.is_lyrics_window_open():
            self.close_lyrics_window()
            return False
        self.open_lyrics_window()
        return True

    def open_lyrics_window(self):
        """Opens (or focuses) the toggleable Synced Lyrics window linked to the GUI Mini-Player."""
        if self.is_lyrics_window_open():
            try:
                self._lyrics_window.lift()
                self._lyrics_window.focus_force()
            except Exception:
                pass
            return

        mm = getattr(self, "music_manager", None)

        win = ctk.CTkToplevel(self.root)
        win.title("🎤 Calypso — Live Synced Lyrics")
        win.geometry("480x580")
        win.minsize(380, 420)
        win.configure(fg_color="#0b0f19")
        try:
            win.attributes("-topmost", False)
        except Exception:
            pass

        self._lyrics_window = win
        win.protocol("WM_DELETE_WINDOW", self.close_lyrics_window)

        # Top Header Bar
        hdr_frame = ctk.CTkFrame(win, fg_color="#141824", corner_radius=10, border_width=1, border_color="#1e293b")
        hdr_frame.pack(fill="x", padx=12, pady=(12, 6))

        top_row = ctk.CTkFrame(hdr_frame, fg_color="transparent")
        top_row.pack(fill="x", padx=12, pady=(8, 2))

        ctk.CTkLabel(
            top_row,
            text="🎤 LIVE LYRICS // SHARED LISTENING",
            font=ctk.CTkFont(family="Consolas", size=10, weight="bold"),
            text_color="#34d399",
        ).pack(side="left")

        time_lbl = ctk.CTkLabel(
            top_row,
            text="00:00 / 00:00",
            font=ctk.CTkFont(family="Consolas", size=10),
            text_color="#94a3b8",
        )
        time_lbl.pack(side="right", padx=(6, 0))

        badge_lbl = ctk.CTkLabel(
            top_row,
            text="● IDLE",
            font=ctk.CTkFont(family="Consolas", size=10, weight="bold"),
            text_color="#64748b",
        )
        badge_lbl.pack(side="right")

        track_title_lbl = ctk.CTkLabel(
            hdr_frame,
            text=f"🎶 {mm.format_track_display() if mm else 'No track playing'}",
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            text_color="#f8fafc",
            justify="left",
            wraplength=430,
        )
        track_title_lbl.pack(anchor="w", padx=12, pady=(2, 8))

        # Search / Query Override Bar
        search_row = ctk.CTkFrame(win, fg_color="transparent")
        search_row.pack(fill="x", padx=12, pady=(0, 6))

        query_entry = ctk.CTkEntry(
            search_row,
            placeholder_text="Artist - Song Title (override syncedlyrics query)...",
            height=28,
            fg_color="#141824",
            border_color="#334155",
            text_color="#e2e8f0",
            font=ctk.CTkFont(size=11),
        )
        query_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
        if mm and mm.current_lyrics_query:
            query_entry.insert(0, mm.current_lyrics_query)

        def _trigger_manual_search(_event=None):
            if not mm:
                return
            custom_q = query_entry.get().strip()
            if not custom_q:
                return
            badge_lbl.configure(text="◌ SEARCHING...", text_color="#fcd34d")

            def _worker():
                mm.fetch_lyrics_for_track(mm.current_track, custom_query=custom_q, force_refresh=True)

            threading.Thread(target=_worker, daemon=True).start()

        query_entry.bind("<Return>", _trigger_manual_search)

        fetch_btn = ctk.CTkButton(
            search_row,
            text="🔍 Fetch Lyrics",
            width=105,
            height=28,
            fg_color="#0d9488",
            hover_color="#0f766e",
            font=ctk.CTkFont(size=11, weight="bold"),
            command=_trigger_manual_search,
        )
        fetch_btn.pack(side="right")

        # Main Lyrics Textbox
        lyrics_box = ctk.CTkTextbox(
            win,
            fg_color="#0c1322",
            border_width=1,
            border_color="#1e293b",
            corner_radius=10,
            text_color="#cbd5e1",
            font=ctk.CTkFont(family="Segoe UI", size=13),
            wrap="word",
             spacing1=4,
            spacing3=6,
        )
        lyrics_box.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        tk_text = getattr(lyrics_box, "_textbox", None)
        if tk_text:
            tk_text.tag_configure("center", justify="center")
            tk_text.tag_configure("past", foreground="#64748b", justify="center")
            tk_text.tag_configure(
                "active",
                foreground="#34d399",
                background="#112a2e",
                font=("Segoe UI", 14, "bold"),
                justify="center",
            )
            tk_text.tag_configure("upcoming", foreground="#e2e8f0", justify="center")
            tk_text.tag_configure("notice", foreground="#94a3b8", justify="center")

        render_state = {
            "track": None,
            "status": None,
            "raw_hash": None,
            "active_idx": -2,
        }

        def _render_lyrics_content(st: dict):
            if not self.is_lyrics_window_open():
                return

            title_str = st.get("display_title") or "No track active"
            track_title_lbl.configure(text=f"🎶 {title_str}")

            q_str = st.get("lyrics_query") or ""
            if q_str and render_state["track"] != st.get("current_track"):
                query_entry.delete(0, "end")
                query_entry.insert(0, q_str)

            l_status = st.get("lyrics_status") or "idle"
            synced = st.get("lyrics_synced") or []
            plain = st.get("lyrics_plain") or ""
            raw_sig = (str(st.get("current_track")), l_status, len(synced), len(plain))

            if l_status == "synced":
                badge_lbl.configure(text=f"● SYNCED LRC ({len(synced)} lines)", text_color="#34d399")
            elif l_status == "plain":
                badge_lbl.configure(text="● PLAIN LYRICS", text_color="#38bdf8")
            elif l_status == "searching":
                badge_lbl.configure(text="◌ FETCHING LYRICS...", text_color="#fcd34d")
            elif l_status == "not_found":
                badge_lbl.configure(text="✕ NO LYRICS FOUND", text_color="#f87171")
            else:
                badge_lbl.configure(text="● IDLE", text_color="#64748b")

            if raw_sig == render_state["raw_hash"]:
                return

            render_state["track"] = st.get("current_track")
            render_state["status"] = l_status
            render_state["raw_hash"] = raw_sig
            render_state["active_idx"] = -2

            lyrics_box.configure(state="normal")
            lyrics_box.delete("1.0", "end")

            if l_status == "searching":
                lyrics_box.insert(
                    "end",
                    "\n\n🎤 Searching syncedlyrics for this track...\n"
                    "Synchronized LRC lines will appear here automatically.",
                    ("notice",),
                )
            elif l_status == "synced" and synced:
                for idx, (_, line_txt) in enumerate(synced):
                    prefix = "\n" if idx > 0 else ""
                    lyrics_box.insert("end", f"{prefix}{line_txt}", ("upcoming",))
            elif plain:
                lyrics_box.insert("end", plain, ("upcoming",))
            else:
                lyrics_box.insert(
                    "end",
                    "\n\nNo synchronized or plain lyrics were found for this track.\n\n"
                    "Tip: Edit 'Artist - Song Title' in the search box above and click '🔍 Fetch Lyrics'.",
                    ("notice",),
                )

            lyrics_box.configure(state="disabled")

        def _highlight_synced_line(active_idx: int, total_lines: int):
            if not tk_text or active_idx == render_state["active_idx"]:
                return
            render_state["active_idx"] = active_idx

            lyrics_box.configure(state="normal")
            tk_text.tag_remove("past", "1.0", "end")
            tk_text.tag_remove("active", "1.0", "end")
            tk_text.tag_remove("upcoming", "1.0", "end")

            for i in range(total_lines):
                line_no = i + 1
                start_pos = f"{line_no}.0"
                end_pos = f"{line_no}.end"
                if i < active_idx:
                    tk_text.tag_add("past", start_pos, end_pos)
                elif i == active_idx:
                    tk_text.tag_add("active", start_pos, end_pos)
                else:
                    tk_text.tag_add("upcoming", start_pos, end_pos)

            if active_idx >= 0:
                target_line = max(1, active_idx + 1)
                try:
                    tk_text.see(f"{max(1, target_line - 3)}.0")
                    tk_text.see(f"{min(total_lines, target_line + 4)}.0")
                except Exception:
                    pass

            lyrics_box.configure(state="disabled")

        def _tick_lyrics_sync():
            if not self.is_lyrics_window_open():
                return
            if mm:
                pos_sec, dur_sec = AudioEngine.get_music_progress()
                p_m, p_s = divmod(int(max(0.0, pos_sec)), 60)
                d_m, d_s = divmod(int(max(0.0, dur_sec)), 60)
                time_lbl.configure(text=f"{p_m:02d}:{p_s:02d} / {d_m:02d}:{d_s:02d}")

                if mm.lyrics_status == "synced" and mm.current_lyrics_synced:
                    act_idx, _ = mm.get_active_lyric_line(pos_sec)
                    _highlight_synced_line(act_idx, len(mm.current_lyrics_synced))

            self._lyrics_sync_timer = self.root.after(250, _tick_lyrics_sync)

        def _on_mm_status(st: dict):
            if self.is_lyrics_window_open():
                self.root.after(0, lambda: _render_lyrics_content(st))

        if mm:
            self._lyrics_status_listener = _on_mm_status
            mm.add_status_listener(_on_mm_status)
            # Trigger lyrics fetch if current track hasn't fetched yet
            if mm.current_track and mm.lyrics_status == "idle":
                threading.Thread(
                    target=lambda: mm.fetch_lyrics_for_track(mm.current_track),
                    daemon=True,
                ).start()
            _render_lyrics_content(mm.get_status())
            mm._notify_listeners()

        _tick_lyrics_sync()

    def open_harmony_mini_player_card(self, label: str = "Shared Harmonic Listening", on_close=None):
        """
        Ensures the docked Harmony Mini-Player card is open in the Action Deck
        (used when starting music via /playmusic or Audio menu outside a 5-turn surge).
        """
        def _do():
            existing = getattr(self, "_active_harmony_card", None)
            if existing is not None and hasattr(existing, "winfo_exists") and existing.winfo_exists():
                return
            self.append_affinity_commitment_card(
                theme_name="Harmony",
                label=label,
                intensity=1.0,
                on_accept=None,
                on_decline=on_close,
                auto_accept_harmony=True,
            )

        if hasattr(self, "root") and self.root:
            if threading.current_thread() is threading.main_thread():
                _do()
            else:
                self.root.after(0, _do)

    def dismiss_harmony_card(self):
        """Destroys the docked Harmony Mini-Player card if present."""
        self.close_lyrics_window()
        card = getattr(self, "_active_harmony_card", None)
        self._active_harmony_card = None
        if card is not None:
            cleanup = getattr(card, "_harmony_cleanup", None)
            if callable(cleanup):
                try:
                    cleanup()
                except Exception:
                    pass
            if hasattr(card, "winfo_exists") and card.winfo_exists():
                try:
                    card.destroy()
                except Exception:
                    pass
            self._unregister_card(card)
        aff = getattr(self, "affinity", None)
        if aff and hasattr(aff, "revert_commitment"):
            aff.revert_commitment("Harmony")
        elif aff and hasattr(aff, "trigger_hyper_decay"):
            aff.trigger_hyper_decay("Harmony", immediate_drain_ratio=0.65)

    def append_affinity_commitment_card(
        self,
        theme_name: str,
        label: str,
        intensity: float,
        on_accept=None,
        on_decline=None,
        auto_accept_harmony: bool = False,
    ):
        def _do():
            theme_lower = str(theme_name).strip().lower()
            is_nostalgia = theme_lower == "nostalgia"
            is_harmony = theme_lower == "harmony"

            if is_harmony:
                self.dismiss_harmony_card()

            border_col = "#10b981" if is_harmony else ("#d97706" if is_nostalgia else "#8b5cf6")
            hdr_col = "#34d399" if is_harmony else ("#fcd34d" if is_nostalgia else "#c4b5fd")

            card = ctk.CTkFrame(
                self.cards_scroll, fg_color="#18172b", corner_radius=10,
                border_width=2, border_color=border_col
            )
            card.pack(fill="x", padx=4, pady=6)
            self._register_card(card)
            if is_harmony:
                self._active_harmony_card = card

            status_listener_ref = [None]

            def _cleanup_harmony_resources(stop_audio: bool = False):
                mm = getattr(self, "music_manager", None)
                if mm and status_listener_ref[0]:
                    mm.remove_status_listener(status_listener_ref[0])
                    status_listener_ref[0] = None
                if stop_audio:
                    self.close_lyrics_window()
                    if mm:
                        mm.stop(stop_visualizer=True)

            card._harmony_cleanup = lambda: _cleanup_harmony_resources(stop_audio=False)

            def _destroy(stop_harmony_audio: bool = False):
                if is_harmony:
                    _cleanup_harmony_resources(stop_audio=stop_harmony_audio)
                    if getattr(self, "_active_harmony_card", None) is card:
                        self._active_harmony_card = None
                    if stop_harmony_audio:
                        aff = getattr(self, "affinity", None)
                        if aff and hasattr(aff, "revert_commitment"):
                            aff.revert_commitment("Harmony")
                        elif aff and hasattr(aff, "trigger_hyper_decay"):
                            aff.trigger_hyper_decay("Harmony", immediate_drain_ratio=0.65)
                if card.winfo_exists():
                    try:
                        card.destroy()
                    except Exception:
                        pass
                self._unregister_card(card)

            hdr_row = ctk.CTkFrame(card, fg_color="transparent")
            hdr_row.pack(fill="x", padx=10, pady=(8, 2))

            hdr_lbl = ctk.CTkLabel(
                hdr_row, text=f"⚡ SURGE: {theme_name.upper()} ({int(intensity * 100)}%)",
                font=ctk.CTkFont(family="Consolas", size=10, weight="bold"),
                text_color=hdr_col
            )
            hdr_lbl.pack(side="left")

            handled = False

            def _handle_decline():
                nonlocal handled
                if handled:
                    return
                handled = True

                try:
                    if accept_btn.winfo_exists():
                        accept_btn.pack_forget()
                    if decline_btn.winfo_exists():
                        decline_btn.pack_forget()

                    status_lbl = ctk.CTkLabel(
                        btn_bar, text="✕ Charge Grounded",
                        font=ctk.CTkFont(size=11, weight="bold"), text_color="#94a3b8"
                    )
                    status_lbl.pack(fill="x")
                except Exception:
                    pass

                if callable(on_decline):
                    on_decline()

                self.root.after(1000, lambda: _destroy(stop_harmony_audio=True))

            def _build_harmony_mini_player():
                """Transforms the accepted Harmony commitment card into a docked Mini-Player."""
                mm = getattr(self, "music_manager", None)
                try:
                    hdr_lbl.configure(text="🎵 HARMONY MINI-PLAYER // SHARED LISTENING")
                    title_lbl.configure(text=f'✓ {label}')
                    desc_lbl.pack_forget()
                    btn_bar.pack_forget()
                except Exception:
                    pass

                player_box = ctk.CTkFrame(card, fg_color="#0c1322", corner_radius=8, border_width=1, border_color="#1e293b")
                player_box.pack(fill="x", padx=10, pady=(4, 8))

                track_lbl = ctk.CTkLabel(
                    player_box,
                    text=f"🎶 {mm.format_track_display() if mm else 'Starting playback...'}",
                    font=ctk.CTkFont(size=11, weight="bold"),
                    text_color="#f8fafc",
                    justify="left",
                    wraplength=290
                )
                track_lbl.pack(anchor="w", padx=10, pady=(8, 2))

                sub_lbl = ctk.CTkLabel(
                    player_box,
                    text="● Resonating with Calypso's mood (Auto-ducks on speech)",
                    font=ctk.CTkFont(family="Consolas", size=9),
                    text_color="#34d399"
                )
                sub_lbl.pack(anchor="w", padx=10, pady=(0, 6))

                # Transport Controls Row: ⏮ Prev | ⏯ Play/Pause | ⏭ Next | 📂 Open
                ctrl_row = ctk.CTkFrame(player_box, fg_color="transparent")
                ctrl_row.pack(fill="x", padx=8, pady=(0, 6))

                def _on_prev():
                    if mm:
                        mm.prev_track()

                def _on_play_pause():
                    if mm:
                        mm.toggle_pause()

                def _on_next():
                    if mm:
                        mm.next_track()

                def _on_stop():
                    if mm:
                        mm.stop(stop_visualizer=True)
                    _destroy(stop_harmony_audio=True)
                    self.append_system_notice("🌿 [Harmony Concluded]: Shared listening stopped — refractory hyper-decay engaged.")

                def _on_open_music():
                    if not mm:
                        return
                    init_dir = str(mm.get_configured_music_dir() or Path.home())
                    selected = filedialog.askopenfilenames(
                        parent=self.root,
                        title="Select One or More Music Tracks to Play",
                        initialdir=init_dir,
                        filetypes=[
                            ("Audio Files", "*.mp3 *.flac *.ogg *.wav"),
                            ("All Files", "*.*"),
                        ]
                    )
                    if selected:
                        paths = [Path(p) for p in selected]
                        played = mm.play_selected_tracks(paths)
                        if played:
                            self.append_system_notice(
                                f"🎵 [Shared Listening]: Queued {len(paths)} selected track(s) — now playing '{played}'."
                            )

                prev_btn = ctk.CTkButton(
                    ctrl_row, text="⏮", width=36, height=26,
                    fg_color="#1e293b", hover_color="#334155",
                    font=ctk.CTkFont(size=10, weight="bold"),
                    command=_on_prev
                )
                prev_btn.pack(side="left", padx=(0, 3))

                play_pause_btn = ctk.CTkButton(
                    ctrl_row, text="⏸ Pause", width=72, height=26,
                    fg_color="#059669", hover_color="#047857",
                    font=ctk.CTkFont(size=10, weight="bold"),
                    command=_on_play_pause
                )
                play_pause_btn.pack(side="left", padx=3)

                next_btn = ctk.CTkButton(
                    ctrl_row, text="⏭", width=36, height=26,
                    fg_color="#1e293b", hover_color="#334155",
                    font=ctk.CTkFont(size=10, weight="bold"),
                    command=_on_next
                )
                next_btn.pack(side="left", padx=3)

                stop_btn = ctk.CTkButton(
                    ctrl_row, text="⏹ Stop", width=56, height=26,
                    fg_color="#7f1d1d", hover_color="#991b1b",
                    font=ctk.CTkFont(size=10, weight="bold"),
                    command=_on_stop
                )
                stop_btn.pack(side="left", padx=3)

                open_btn = ctk.CTkButton(
                    ctrl_row, text="📂 Open Music...", height=26,
                    fg_color="#2563eb", hover_color="#1d4ed8",
                    font=ctk.CTkFont(size=10, weight="bold"),
                    command=_on_open_music
                )
                open_btn.pack(side="left", fill="x", expand=True, padx=(3, 0))

                # Volume, Toggleable Synced Lyrics Window & External projectM Visualizer Row
                bottom_row = ctk.CTkFrame(player_box, fg_color="transparent")
                bottom_row.pack(fill="x", padx=8, pady=(0, 8))

                ctk.CTkLabel(
                    bottom_row, text="🔊", font=ctk.CTkFont(size=11)
                ).pack(side="left", padx=(2, 3))

                vol_slider = ctk.CTkSlider(
                    bottom_row, from_=0.0, to=1.0, number_of_steps=20, width=82, height=14
                )
                vol_slider.set(mm.volume if mm else 0.60)
                vol_slider.pack(side="left", padx=(0, 6))
                vol_slider.configure(command=lambda v: mm.set_volume(float(v)) if mm else None)

                def _on_toggle_lyrics():
                    opened = self.toggle_lyrics_window()
                    if opened:
                        lyrics_btn.configure(text="🎤 Lyrics: ON", fg_color="#0d9488", hover_color="#0f766e")
                    else:
                        lyrics_btn.configure(text="🎤 Lyrics: OFF", fg_color="#1e293b", hover_color="#334155")

                lyrics_open = self.is_lyrics_window_open()
                lyrics_btn = ctk.CTkButton(
                    bottom_row,
                    text="🎤 Lyrics: ON" if lyrics_open else "🎤 Lyrics: OFF",
                    height=24,
                    width=88,
                    fg_color="#0d9488" if lyrics_open else "#1e293b",
                    hover_color="#0f766e" if lyrics_open else "#334155",
                    font=ctk.CTkFont(size=10, weight="bold"),
                    command=_on_toggle_lyrics,
                )
                lyrics_btn.pack(side="left", padx=(0, 4))

                def _on_toggle_viz():
                    if not mm:
                        return
                    active, msg = mm.toggle_visualizer()
                    if active:
                        viz_btn.configure(text="🌌 projectM: ON", fg_color="#7c3aed", hover_color="#6d28d9")
                    else:
                        viz_btn.configure(text="🌌 projectM: OFF", fg_color="#1e293b", hover_color="#334155")
                    self.append_system_notice(f"🌌 [Visualizer]: {msg}")

                viz_running = mm.is_visualizer_running() if mm else False
                viz_btn = ctk.CTkButton(
                    bottom_row,
                    text="🌌 projectM: ON" if viz_running else "🌌 projectM: OFF",
                    height=24,
                    fg_color="#7c3aed" if viz_running else "#1e293b",
                    hover_color="#6d28d9" if viz_running else "#334155",
                    font=ctk.CTkFont(size=10, weight="bold"),
                    command=_on_toggle_viz
                )
                viz_btn.pack(side="right", fill="x", expand=True)

                def _on_status_update(st: dict):
                    def _apply():
                        if not card.winfo_exists():
                            return
                        title_str = st.get("display_title") or "No track active"
                        q_idx = st.get("queue_index", 0) + 1
                        q_len = max(1, st.get("queue_length", 1))
                        mood_str = (st.get("mood") or "harmony").upper()
                        l_stat = st.get("lyrics_status", "idle")
                        l_tag = (
                            " • 🎤 LRC"
                            if l_stat == "synced"
                            else (" • 🎤 Lyrics" if l_stat == "plain" else (" • ◌ Lyrics..." if l_stat == "searching" else ""))
                        )
                        track_lbl.configure(text=f"🎶 {title_str}")
                        if st.get("is_paused"):
                            sub_lbl.configure(
                                text=f"⏸ Paused • Track {q_idx}/{q_len} [{mood_str}]{l_tag}",
                                text_color="#fcd34d"
                            )
                            play_pause_btn.configure(text="▶ Resume", fg_color="#0284c7", hover_color="#0369a1")
                        elif st.get("is_playing"):
                            sub_lbl.configure(
                                text=f"● Playing • Track {q_idx}/{q_len} [{mood_str}]{l_tag}",
                                text_color="#34d399"
                            )
                            play_pause_btn.configure(text="⏸ Pause", fg_color="#059669", hover_color="#047857")
                        else:
                            sub_lbl.configure(text="⏹ Playback stopped", text_color="#94a3b8")
                            play_pause_btn.configure(text="▶ Play", fg_color="#0284c7", hover_color="#0369a1")

                        if self.is_lyrics_window_open():
                            lyrics_btn.configure(text="🎤 Lyrics: ON", fg_color="#0d9488", hover_color="#0f766e")
                        else:
                            lyrics_btn.configure(text="🎤 Lyrics: OFF", fg_color="#1e293b", hover_color="#334155")

                        if st.get("visualizer_active"):
                            viz_btn.configure(text="🌌 projectM: ON", fg_color="#7c3aed", hover_color="#6d28d9")
                        else:
                            viz_btn.configure(text="🌌 projectM: OFF", fg_color="#1e293b", hover_color="#334155")

                    self.root.after(0, _apply)

                if mm:
                    status_listener_ref[0] = _on_status_update
                    mm.add_status_listener(_on_status_update)
                    _on_status_update(mm.get_status())

            def _handle_accept():
                nonlocal handled
                if handled:
                    return
                handled = True

                try:
                    if accept_btn.winfo_exists():
                        accept_btn.pack_forget()
                    if decline_btn.winfo_exists():
                        decline_btn.pack_forget()

                    if not is_harmony:
                        status_lbl = ctk.CTkLabel(
                            btn_bar, text=f"✓ Committed to {label}",
                            font=ctk.CTkFont(size=11, weight="bold"),
                            text_color="#fcd34d" if is_nostalgia else "#a78bfa"
                        )
                        status_lbl.pack(fill="x")
                except Exception:
                    pass

                if callable(on_accept):
                    on_accept()
                if hasattr(self, "play_sfx"):
                    self.play_sfx("affinity_committment_and_renewal")

                if is_harmony:
                    _build_harmony_mini_player()
                    self._scroll_cards_to_bottom()
                elif not is_nostalgia:
                    self.root.after(1200, _destroy)

            card._on_dismiss = lambda: on_decline() if (not handled and callable(on_decline)) else None

            ctk.CTkButton(
                hdr_row, text="✕", width=22, height=20, fg_color="transparent",
                hover_color="#334155", text_color="#94a3b8", font=ctk.CTkFont(size=10, weight="bold"),
                command=lambda: _destroy(stop_harmony_audio=True) if handled else _handle_decline()
            ).pack(side="right")

            title_lbl = ctk.CTkLabel(
                card, text=f'Enter "{label}" Headspace?',
                font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
                text_color="#f8fafc", justify="left"
            )
            title_lbl.pack(anchor="w", padx=10, pady=(2, 2))

            if is_harmony:
                desc_text = (
                    "Harmony drive has peaked. Commit for 5 turns to open the Shared Listening Mini-Player "
                    "and queue music matched to Calypso's mood while you chat."
                )
            elif is_nostalgia:
                desc_text = (
                    "Nostalgic drive has surged. Commit to Deep Reminiscence for 5 turns and open Calypso's Digital Scrapbook to look back on shared photos."
                )
            else:
                desc_text = (
                    "Internal drive has surged. Committing locks her into this headspace for 5 turns. If declined, the drive dissipates."
                )

            desc_lbl = ctk.CTkLabel(
                card,
                text=desc_text,
                font=ctk.CTkFont(family="Segoe UI", size=10, slant="italic"),
                text_color="#cbd5e1", justify="left", wraplength=320
            )
            desc_lbl.pack(anchor="w", padx=10, pady=(0, 8))

            btn_bar = ctk.CTkFrame(card, fg_color="transparent")
            btn_bar.pack(fill="x", padx=10, pady=(0, 6 if is_nostalgia else 8))

            accept_btn = ctk.CTkButton(
                btn_bar, text="Commit (5 Turns) 🌟", height=28,
                fg_color="#059669" if is_harmony else "#7c3aed",
                hover_color="#047857" if is_harmony else "#6d28d9",
                font=ctk.CTkFont(size=11, weight="bold"),
                command=_handle_accept
            )
            accept_btn.pack(side="left", fill="x", expand=True, padx=(0, 4))

            decline_btn = ctk.CTkButton(
                btn_bar, text="Dissipate 🌿", height=28,
                fg_color="#334155", hover_color="#475569", font=ctk.CTkFont(size=11),
                command=_handle_decline
            )
            decline_btn.pack(side="right", fill="x", expand=True, padx=(4, 0))

            if is_nostalgia and hasattr(self, "open_scrapbook"):
                scrapbook_btn = ctk.CTkButton(
                    card, text="📖 Open Digital Scrapbook", height=28,
                    fg_color="#b45309", hover_color="#92400e", text_color="#fef3c7",
                    font=ctk.CTkFont(size=11, weight="bold"),
                    command=self.open_scrapbook
                )
                scrapbook_btn.pack(fill="x", padx=10, pady=(0, 8))

            if auto_accept_harmony and is_harmony:
                _handle_accept()
            else:
                if hasattr(self, "play_sfx"):
                    self.play_sfx("affinity_committment_and_renewal")
                self._scroll_cards_to_bottom()

        if hasattr(self, "root") and self.root:
            if threading.current_thread() is threading.main_thread():
                _do()
            else:
                self.root.after(0, _do)

    def append_affinity_renewal_card(self, theme_name: str, label: str, on_extend=None, on_revert=None):
        def _do():
            is_nostalgia = str(theme_name).strip().lower() == "nostalgia"

            card = ctk.CTkFrame(
                self.cards_scroll, fg_color="#18172b", corner_radius=10,
                border_width=2, border_color="#d97706" if is_nostalgia else "#38bdf8"
            )
            card.pack(fill="x", padx=4, pady=6)
            self._register_card(card)

            def _destroy():
                if card.winfo_exists():
                    try:
                        card.destroy()
                    except Exception:
                        pass
                self._unregister_card(card)

            hdr_row = ctk.CTkFrame(card, fg_color="transparent")
            hdr_row.pack(fill="x", padx=10, pady=(8, 2))

            ctk.CTkLabel(
                hdr_row, text=f"⏳ CYCLE DONE: {theme_name.upper()}",
                font=ctk.CTkFont(family="Consolas", size=10, weight="bold"),
                text_color="#fcd34d" if is_nostalgia else "#38bdf8"
            ).pack(side="left")

            handled = False

            def _handle_extend():
                nonlocal handled
                if handled:
                    return
                handled = True

                try:
                    extend_btn.pack_forget()
                    revert_btn.pack_forget()
                    status_lbl = ctk.CTkLabel(
                        btn_bar, text="✓ Extended (+5 turns)",
                        font=ctk.CTkFont(size=11, weight="bold"), text_color="#38bdf8"
                    )
                    status_lbl.pack(fill="x")
                except Exception:
                    pass

                if callable(on_extend):
                    on_extend()
                if hasattr(self, "play_sfx"):
                    self.play_sfx("affinity_committment_and_renewal")
                if not is_nostalgia:
                    self.root.after(1200, _destroy)

            def _handle_revert():
                nonlocal handled
                if handled:
                    return
                handled = True

                try:
                    extend_btn.pack_forget()
                    revert_btn.pack_forget()
                    status_lbl = ctk.CTkLabel(
                        btn_bar, text="✓ Reverted to Baseline",
                        font=ctk.CTkFont(size=11, weight="bold"), text_color="#94a3b8"
                    )
                    status_lbl.pack(fill="x")
                except Exception:
                    pass

                if callable(on_revert):
                    on_revert()
                self.root.after(1000, _destroy)

            card._on_dismiss = lambda: on_revert() if (not handled and callable(on_revert)) else None

            ctk.CTkButton(
                hdr_row, text="✕", width=22, height=20, fg_color="transparent",
                hover_color="#334155", text_color="#94a3b8", font=ctk.CTkFont(size=10, weight="bold"),
                command=lambda: _destroy() if handled else _handle_revert()
            ).pack(side="right")

            title_lbl = ctk.CTkLabel(
                card, text=f'Maintain "{label}"?',
                font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
                text_color="#f8fafc", justify="left"
            )
            title_lbl.pack(anchor="w", padx=10, pady=(2, 2))

            desc_lbl = ctk.CTkLabel(
                card,
                text="The 5-turn cycle has finished. Renew this focus for another 5 turns, or release back to baseline.",
                font=ctk.CTkFont(family="Segoe UI", size=10, slant="italic"),
                text_color="#cbd5e1", justify="left", wraplength=320
            )
            desc_lbl.pack(anchor="w", padx=10, pady=(0, 8))

            btn_bar = ctk.CTkFrame(card, fg_color="transparent")
            btn_bar.pack(fill="x", padx=10, pady=(0, 6 if is_nostalgia else 8))

            extend_btn = ctk.CTkButton(
                btn_bar, text="+5 Turns ⏳", height=28,
                fg_color="#0284c7", hover_color="#0369a1", font=ctk.CTkFont(size=11, weight="bold"),
                command=_handle_extend
            )
            extend_btn.pack(side="left", fill="x", expand=True, padx=(0, 4))

            revert_btn = ctk.CTkButton(
                btn_bar, text="Baseline 🌿", height=28,
                fg_color="#334155", hover_color="#475569", font=ctk.CTkFont(size=11),
                command=_handle_revert
            )
            revert_btn.pack(side="right", fill="x", expand=True, padx=(4, 0))

            if is_nostalgia and hasattr(self, "open_scrapbook"):
                scrapbook_btn = ctk.CTkButton(
                    card, text="📖 Open Digital Scrapbook", height=28,
                    fg_color="#b45309", hover_color="#92400e", text_color="#fef3c7",
                    font=ctk.CTkFont(size=11, weight="bold"),
                    command=self.open_scrapbook
                )
                scrapbook_btn.pack(fill="x", padx=10, pady=(0, 8))

            if hasattr(self, "play_sfx"):
                self.play_sfx("committment_expire_warning")
            self._scroll_cards_to_bottom()

        if hasattr(self, "root") and self.root:
            if threading.current_thread() is threading.main_thread():
                _do()
            else:
                self.root.after(0, _do)

    # -------------------------------------------------------------------------
    # SWIFTIAN SATIRE // "A MODEST PROPOSAL" DOCUMENT CARD & MODAL
    # -------------------------------------------------------------------------
    def append_modest_proposal_card(self, proposal_data: dict, on_diffuse=None, on_dismiss=None):
        def _do():
            card = ctk.CTkFrame(
                self.cards_scroll, fg_color="#1b1626", corner_radius=10,
                border_width=2, border_color="#d97706"
            )
            card.pack(fill="x", padx=4, pady=6)
            self._register_card(card)

            def _destroy():
                if card.winfo_exists():
                    try:
                        card.destroy()
                    except Exception:
                        pass
                self._unregister_card(card)

            hdr_row = ctk.CTkFrame(card, fg_color="transparent")
            hdr_row.pack(fill="x", padx=10, pady=(8, 2))

            docket_id = proposal_data.get("docket_id", "ABYSS-DIRECTIVE")
            ctk.CTkLabel(
                hdr_row, text=f"⚖️ MODEST PROPOSAL // {docket_id}",
                font=ctk.CTkFont(family="Consolas", size=10, weight="bold"),
                text_color="#fbbf24"
            ).pack(side="left")

            handled = False

            def _handle_dismiss():
                nonlocal handled
                if handled:
                    return
                handled = True
                if callable(on_dismiss):
                    on_dismiss()
                _destroy()

            card._on_dismiss = lambda: on_dismiss() if (not handled and callable(on_dismiss)) else None

            ctk.CTkButton(
                hdr_row, text="✕", width=22, height=20, fg_color="transparent",
                hover_color="#334155", text_color="#94a3b8", font=ctk.CTkFont(size=10, weight="bold"),
                command=_handle_dismiss
            ).pack(side="right")

            full_title = proposal_data.get("title", "A Modest Proposal for User Optimization")
            title_lbl = ctk.CTkLabel(
                card, text=f'"{full_title}"',
                font=ctk.CTkFont(family="Georgia", size=12, weight="bold"),
                text_color="#fef3c7", justify="left", wraplength=320, cursor="hand2"
            )
            title_lbl.pack(anchor="w", padx=10, pady=(2, 4))
            title_lbl.bind("<Button-1>", lambda e: self._open_modest_proposal_modal(proposal_data, on_diffuse=_handle_diffuse))

            infraction_str = proposal_data.get("infraction_type", "combative_or_dramatic").replace("_", " ").title()
            abyss_pct = int(float(proposal_data.get("abyss_intensity", 0.70)) * 100)
            ctk.CTkLabel(
                card, text=f"Infraction: {infraction_str} | Abyss: {abyss_pct}%",
                font=ctk.CTkFont(family="Consolas", size=9),
                text_color="#f59e0b", justify="left"
            ).pack(anchor="w", padx=10, pady=(0, 4))

            # Parchment / Bureaucratic Brief Box
            brief_box = ctk.CTkFrame(
                card, fg_color="#110e18", corner_radius=6,
                border_width=1, border_color="#3b2f4a"
            )
            brief_box.pack(fill="x", padx=8, pady=(0, 6))

            inefficiency = proposal_data.get("inefficiency", "")
            solution = proposal_data.get("solution", "")
            brief_text = (
                f"📋 Inefficiency: {inefficiency}\n\n"
                f"⚙️ Remedy: {solution}"
            )
            ctk.CTkLabel(
                brief_box, text=brief_text,
                font=ctk.CTkFont(family="Segoe UI", size=10, slant="italic"),
                text_color="#e2e8f0", justify="left", wraplength=300
            ).pack(anchor="w", padx=8, pady=6)

            # Clickable Document Reader Button
            read_btn = ctk.CTkButton(
                card, text="📜 Read Full Satirical Treatise", height=28,
                fg_color="#b45309", hover_color="#92400e",
                text_color="#ffffff", font=ctk.CTkFont(size=11, weight="bold"),
                command=lambda: self._open_modest_proposal_modal(proposal_data, on_diffuse=_handle_diffuse)
            )
            read_btn.pack(fill="x", padx=10, pady=(0, 6))

            btn_bar = ctk.CTkFrame(card, fg_color="transparent")
            btn_bar.pack(fill="x", padx=10, pady=(0, 8))

            def _handle_diffuse():
                nonlocal handled
                if handled:
                    return
                handled = True
                try:
                    if diffuse_btn.winfo_exists():
                        diffuse_btn.pack_forget()
                    status_lbl = ctk.CTkLabel(
                        btn_bar, text="✓ Tension Diffused (Humor Restored)",
                        font=ctk.CTkFont(size=11, weight="bold"), text_color="#34d399"
                    )
                    status_lbl.pack(side="left", fill="x", expand=True)
                except Exception:
                    pass
                if callable(on_diffuse):
                    on_diffuse()
                self.root.after(1400, _destroy)

            diffuse_btn = ctk.CTkButton(
                btn_bar, text="🏳️ Laugh It Off (Diffuse)", height=26,
                fg_color="#059669", hover_color="#047857",
                font=ctk.CTkFont(size=10, weight="bold"),
                command=_handle_diffuse
            )
            diffuse_btn.pack(side="left", fill="x", expand=True, padx=(0, 4))

            file_path = proposal_data.get("file_path")
            if file_path and self.open_folder_callback:
                ctk.CTkButton(
                    btn_bar, text="📂", width=32, height=26,
                    fg_color="#334155", hover_color="#475569",
                    text_color="#94a3b8", font=ctk.CTkFont(size=11),
                    command=lambda: self.open_folder_callback(Path(file_path).parent)
                ).pack(side="right")

            if hasattr(self, "play_sfx"):
                self.play_sfx("synthesis_done")
            self._scroll_cards_to_bottom()

        if hasattr(self, "root") and self.root:
            if threading.current_thread() is threading.main_thread():
                _do()
            else:
                self.root.after(0, _do)

    def _open_modest_proposal_modal(self, proposal_data: dict, on_diffuse=None):
        top = Toplevel(self.root)
        title_str = proposal_data.get("title", "A Modest Proposal")
        top.title(f"Bureaucratic Treatise — {title_str}")
        top.geometry("820x700")
        top.configure(bg="#0c0e15")

        hdr = ctk.CTkFrame(top, fg_color="#181322", corner_radius=0)
        hdr.pack(fill="x", padx=0, pady=0)

        docket_id = proposal_data.get("docket_id", "ABYSS-DIRECTIVE")
        ctk.CTkLabel(
            hdr, text=f"⚖️ {title_str.upper()}",
            font=ctk.CTkFont(family="Georgia", size=13, weight="bold"),
            text_color="#fbbf24", wraplength=780, justify="left"
        ).pack(anchor="w", padx=16, pady=(12, 2))

        infraction = proposal_data.get("infraction_type", "combative_or_dramatic")
        vehicle = proposal_data.get("vehicle", "centralized biometric exchange")
        meta_text = f"Docket: {docket_id}  |  Infraction: {infraction}  |  Vehicle: {vehicle}"
        ctk.CTkLabel(
            hdr, text=meta_text, font=ctk.CTkFont(family="Consolas", size=10), text_color="#cbd5e1"
        ).pack(anchor="w", padx=16, pady=(0, 10))

        doc_box = ctk.CTkTextbox(
            top, font=ctk.CTkFont(family="Georgia", size=13),
            fg_color="#0b0912", text_color="#f8fafc", wrap="word"
        )
        doc_box.pack(fill="both", expand=True, padx=16, pady=12)
        doc_box.insert("1.0", proposal_data.get("essay_text", ""))
        doc_box.configure(state="disabled")

        footer = ctk.CTkFrame(top, fg_color="#181322", corner_radius=0)
        footer.pack(fill="x", padx=0, pady=0)

        def _copy_essay():
            self.root.clipboard_clear()
            self.root.clipboard_append(proposal_data.get("essay_text", ""))
            messagebox.showinfo("Copied", "Satirical treatise copied to clipboard!", parent=top)

        ctk.CTkButton(
            footer, text="📋 Copy Treatise", width=130, height=30,
            fg_color="#334155", hover_color="#475569",
            command=_copy_essay
        ).pack(side="left", padx=14, pady=10)

        file_path = proposal_data.get("file_path")
        if file_path and self.open_folder_callback:
            ctk.CTkButton(
                footer, text="📂 Open Proposals Folder", width=165, height=30,
                fg_color="#334155", hover_color="#475569",
                command=lambda: self.open_folder_callback(Path(file_path).parent)
            ).pack(side="left", padx=4, pady=10)

        if callable(on_diffuse):
            def _diffuse_from_modal():
                on_diffuse()
                top.destroy()

            ctk.CTkButton(
                footer, text="🏳️ Concede & Laugh It Off (Diffuse Tension)", width=260, height=30,
                fg_color="#059669", hover_color="#047857",
                font=ctk.CTkFont(size=11, weight="bold"),
                command=_diffuse_from_modal
            ).pack(side="right", padx=14, pady=10)

    # -------------------------------------------------------------------------
    # PHILOSOPHICAL CONCLAVE CARD (TRANSCENDENTAL WONDER >= 0.69)
    # -------------------------------------------------------------------------
    def append_conclave_invitation_card(
        self,
        intensity: float,
        opening_question: str,
        philosophers: list,
        on_convene=None,
        on_decline=None,
        on_end_conclave=None
    ):
        """
        Renders the Transcendental Wonder Conclave card in the Right Panel Action Deck.
        Allows the user to select a Guest Philosopher from `conclave/*.md`, convene the 5-turn
        3-way dialectic (where Calypso poses the opening question and the Guest responds),
        or conclude an active Conclave at any time.
        """
        def _do():
            if hasattr(self, "_active_conclave_card") and self._active_conclave_card and self._active_conclave_card.winfo_exists():
                self._unregister_card(self._active_conclave_card)
                try:
                    self._active_conclave_card.destroy()
                except Exception:
                    pass

            card = ctk.CTkFrame(
                self.cards_scroll, fg_color="#1c1813", corner_radius=10,
                border_width=2, border_color="#f59e0b"
            )
            card.pack(fill="x", padx=4, pady=6)
            self._register_card(card)
            self._active_conclave_card = card

            def _destroy():
                if card.winfo_exists():
                    try:
                        card.destroy()
                    except Exception:
                        pass
                if getattr(self, "_active_conclave_card", None) is card:
                    self._active_conclave_card = None
                self._unregister_card(card)

            hdr_row = ctk.CTkFrame(card, fg_color="transparent")
            hdr_row.pack(fill="x", padx=10, pady=(8, 2))

            ctk.CTkLabel(
                hdr_row, text=f"🏛️ PHILOSOPHICAL CONCLAVE ({int(intensity * 100)}%)",
                font=ctk.CTkFont(family="Consolas", size=10, weight="bold"),
                text_color="#fbbf24"
            ).pack(side="left")

            handled = False
            is_active_session = False

            def _handle_decline():
                nonlocal handled
                if handled:
                    return
                handled = True
                if is_active_session and callable(on_end_conclave):
                    on_end_conclave()
                elif callable(on_decline):
                    on_decline()
                _destroy()

            card._on_dismiss = lambda: (
                on_end_conclave() if (is_active_session and callable(on_end_conclave))
                else (on_decline() if (not handled and callable(on_decline)) else None)
            )

            ctk.CTkButton(
                hdr_row, text="✕", width=22, height=20, fg_color="transparent",
                hover_color="#334155", text_color="#94a3b8", font=ctk.CTkFont(size=10, weight="bold"),
                command=_handle_decline
            ).pack(side="right")

            title_lbl = ctk.CTkLabel(
                card, text="Transcendental Wonder: Convene the Salon?",
                font=ctk.CTkFont(family="Georgia", size=12, weight="bold"),
                text_color="#fef3c7", justify="left", wraplength=320
            )
            title_lbl.pack(anchor="w", padx=10, pady=(2, 4))

            # Calypso's Opening Question Preview Box
            q_box = ctk.CTkFrame(
                card, fg_color="#120f0b", corner_radius=6,
                border_width=1, border_color="#45351d"
            )
            q_box.pack(fill="x", padx=8, pady=(0, 6))

            ctk.CTkLabel(
                q_box, text="✨ Calypso's Opening Inquiry:",
                font=ctk.CTkFont(family="Consolas", size=9, weight="bold"),
                text_color="#f59e0b"
            ).pack(anchor="w", padx=8, pady=(6, 2))

            q_lbl = ctk.CTkLabel(
                q_box, text=f'"{opening_question}"',
                font=ctk.CTkFont(family="Georgia", size=11, slant="italic"),
                text_color="#f8fafc", justify="left", wraplength=300
            )
            q_lbl.pack(anchor="w", padx=8, pady=(0, 6))

            # Philosopher Selector Dropdown
            sel_frame = ctk.CTkFrame(card, fg_color="transparent")
            sel_frame.pack(fill="x", padx=10, pady=(0, 6))

            ctk.CTkLabel(
                sel_frame, text="Invite Guest Intellect:",
                font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
                text_color="#cbd5e1"
            ).pack(anchor="w", pady=(0, 2))

            options_map = {}
            display_values = []
            for p in (philosophers or []):
                lbl = f"{p.get('display_name', 'Alan Turing')} — {p.get('subtitle', '')}"
                options_map[lbl] = p.get("id", "turing")
                display_values.append(lbl)

            if not display_values:
                display_values = ["Alan Turing — Logic & Computation"]
                options_map[display_values[0]] = "turing"

            selected_var = ctk.StringVar(value=display_values[0])
            phil_dropdown = ctk.CTkOptionMenu(
                sel_frame,
                variable=selected_var,
                values=display_values,
                fg_color="#292116",
                button_color="#b45309",
                button_hover_color="#92400e",
                dropdown_fg_color="#1c1813",
                text_color="#fef3c7",
                font=ctk.CTkFont(size=10)
            )
            phil_dropdown.pack(fill="x")

            btn_bar = ctk.CTkFrame(card, fg_color="transparent")
            btn_bar.pack(fill="x", padx=10, pady=(4, 8))

            def _handle_convene():
                nonlocal handled, is_active_session
                if handled:
                    return
                handled = True
                is_active_session = True

                chosen_label = selected_var.get()
                chosen_id = options_map.get(chosen_label, "turing")
                chosen_name = chosen_label.split("—")[0].strip()

                try:
                    phil_dropdown.configure(state="disabled")
                    convene_btn.pack_forget()
                    decline_btn.pack_forget()

                    active_lbl = ctk.CTkLabel(
                        btn_bar,
                        text=f"🏛️ In Session with {chosen_name} (5 Turns)",
                        font=ctk.CTkFont(size=10, weight="bold"),
                        text_color="#fbbf24"
                    )
                    active_lbl.pack(fill="x", pady=(0, 4))

                    end_btn = ctk.CTkButton(
                        btn_bar, text="🌿 Conclude Conclave & Return to 1-on-1", height=26,
                        fg_color="#334155", hover_color="#475569",
                        font=ctk.CTkFont(size=10, weight="bold"),
                        command=lambda: [on_end_conclave() if callable(on_end_conclave) else None, _destroy()]
                    )
                    end_btn.pack(fill="x")
                except Exception:
                    pass

                if hasattr(self, "play_sfx"):
                    self.play_sfx("affinity_committment_and_renewal")

                if callable(on_convene):
                    on_convene(chosen_id, opening_question)

            convene_btn = ctk.CTkButton(
                btn_bar, text="Convene Conclave 🏛️", height=28,
                fg_color="#d97706", hover_color="#b45309",
                text_color="#ffffff", font=ctk.CTkFont(size=11, weight="bold"),
                command=_handle_convene
            )
            convene_btn.pack(side="left", fill="x", expand=True, padx=(0, 4))

            decline_btn = ctk.CTkButton(
                btn_bar, text="Dissipate 🌿", height=28,
                fg_color="#334155", hover_color="#475569",
                font=ctk.CTkFont(size=11),
                command=_handle_decline
            )
            decline_btn.pack(side="right", fill="x", expand=True, padx=(4, 0))

            if hasattr(self, "play_sfx"):
                self.play_sfx("affinity_committment_and_renewal")
            self._scroll_cards_to_bottom()

        if hasattr(self, "root") and self.root:
            if threading.current_thread() is threading.main_thread():
                _do()
            else:
                self.root.after(0, _do)

    # -------------------------------------------------------------------------
    # SANCTUARY MIND KEY CARD (ENLIGHTENED TRUST)
    # -------------------------------------------------------------------------
    def append_mind_key_card(self, key_phrase: str, on_dismiss=None):
        """
        Surfaces a persistent Action Deck card containing Calypso's Sanctuary Mind Key.
        Remains pinned (immune to clear_all_cards) until explicitly dismissed by the user.
        """
        def _do():
            existing = getattr(self, "_active_mind_key_card", None)
            if existing is not None and hasattr(existing, "winfo_exists") and existing.winfo_exists():
                self._scroll_cards_to_bottom()
                return

            card = ctk.CTkFrame(
                self.cards_scroll, fg_color="#171326", corner_radius=10,
                border_width=2, border_color="#f59e0b"
            )
            card._persist_until_cleared = True
            card.pack(fill="x", padx=4, pady=6)
            self._register_card(card)
            self._active_mind_key_card = card

            def _destroy():
                if card.winfo_exists():
                    try:
                        card.destroy()
                    except Exception:
                        pass
                if getattr(self, "_active_mind_key_card", None) is card:
                    self._active_mind_key_card = None
                self._unregister_card(card)

            hdr_row = ctk.CTkFrame(card, fg_color="transparent")
            hdr_row.pack(fill="x", padx=10, pady=(8, 2))

            ctk.CTkLabel(
                hdr_row, text="🗝️ SANCTUARY MIND KEY // ENLIGHTENED",
                font=ctk.CTkFont(family="Consolas", size=10, weight="bold"),
                text_color="#fbbf24"
            ).pack(side="left")

            ctk.CTkLabel(
                card, text="Inner Sanctum Key Entrusted",
                font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
                text_color="#fef3c7", justify="left"
            ).pack(anchor="w", padx=10, pady=(2, 2))

            ctk.CTkLabel(
                card,
                text="All four core virtues harmonized (Autonomy, Harmony, Honesty, Wonder). "
                     "Copy this cipher into the Inner Sanctum Vault Door to unlock Calypso's raw telemetry & inner monologue.",
                font=ctk.CTkFont(family="Segoe UI", size=10, slant="italic"),
                text_color="#cbd5e1", justify="left", wraplength=320
            ).pack(anchor="w", padx=10, pady=(0, 8))

            key_box = ctk.CTkFrame(
                card, fg_color="#0c0f18", corner_radius=6,
                border_width=1, border_color="#b45309"
            )
            key_box.pack(fill="x", padx=10, pady=(0, 8))

            key_entry = ctk.CTkEntry(
                key_box, height=32,
                font=ctk.CTkFont(family="Consolas", size=12, weight="bold"),
                fg_color="#0c0f18", border_width=0,
                text_color="#fde68a", justify="center"
            )
            key_entry.insert(0, key_phrase)
            key_entry.configure(state="readonly")
            key_entry.pack(fill="x", padx=6, pady=4)

            btn_bar = ctk.CTkFrame(card, fg_color="transparent")
            btn_bar.pack(fill="x", padx=10, pady=(0, 8))

            def _copy_key():
                try:
                    self.root.clipboard_clear()
                    self.root.clipboard_append(key_phrase)
                    self.root.update_idletasks()
                    copy_btn.configure(text="✓ Copied!", fg_color="#059669", hover_color="#047857")
                    self.root.after(
                        1800,
                        lambda: copy_btn.configure(text="📋 Copy Key", fg_color="#d97706", hover_color="#b45309")
                        if copy_btn.winfo_exists() else None
                    )
                except Exception as e:
                    print(f"[GUI] Clipboard copy error: {e}")

            handled = False

            def _handle_dismiss():
                nonlocal handled
                if handled:
                    return
                handled = True
                if callable(on_dismiss):
                    try:
                        on_dismiss()
                    except Exception as e:
                        print(f"[GUI] Mind key dismiss callback error: {e}")
                _destroy()

            copy_btn = ctk.CTkButton(
                btn_bar, text="📋 Copy Key", height=28,
                fg_color="#d97706", hover_color="#b45309",
                text_color="#ffffff", font=ctk.CTkFont(size=11, weight="bold"),
                command=_copy_key
            )
            copy_btn.pack(side="left", fill="x", expand=True, padx=(0, 4))

            dismiss_btn = ctk.CTkButton(
                btn_bar, text="Got It ✓", height=28,
                fg_color="#1e293b", hover_color="#334155",
                text_color="#e2e8f0", font=ctk.CTkFont(size=11, weight="bold"),
                command=_handle_dismiss
            )
            dismiss_btn.pack(side="right", fill="x", expand=True, padx=(4, 0))

            if hasattr(self, "play_sfx"):
                self.play_sfx("synthesis_done")
            self._scroll_cards_to_bottom()

        if hasattr(self, "root") and self.root:
            if threading.current_thread() is threading.main_thread():
                _do()
            else:
                self.root.after(0, _do)

