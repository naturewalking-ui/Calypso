# modules/calendar_window.py

import calendar
from datetime import datetime, date
import tkinter as tk
from tkinter import messagebox
import customtkinter as ctk
from modules.calendar_manager import CalendarManager
from modules.goal_manager import GoalManager


class CalendarWindow(ctk.CTkToplevel):
    def __init__(
        self,
        parent_root,
        alarm_service=None,
        on_alarm_set_callback=None,
        goal_manager=None,
        on_goal_created_callback=None
    ):
        super().__init__(parent_root)
        self.title("Event Calendar, Goals & Scheduler")
        self.geometry("940x660")
        self.minsize(860, 580)
        self.configure(fg_color="#0c0e15")
        self.transient(parent_root)

        self.alarm_service = alarm_service
        self.on_alarm_set_callback = on_alarm_set_callback
        self.on_goal_created_callback = on_goal_created_callback
        self.manager = CalendarManager()
        self.goal_manager = goal_manager or GoalManager(calendar_manager=self.manager)

        # Navigation State
        today = date.today()
        self.current_year = today.year
        self.current_month = today.month
        self.selected_date_str = today.strftime("%Y-%m-%d")

        self._setup_layout()
        self._render_calendar_grid()
        self._render_day_events(self.selected_date_str)

    def _setup_layout(self):
        self.columnconfigure(0, weight=3)
        self.columnconfigure(1, weight=2)
        self.rowconfigure(0, weight=1)

        # Left: Calendar Grid Frame
        self.left_frame = ctk.CTkFrame(self, fg_color="#141824", corner_radius=12, border_width=1, border_color="#1e2538")
        self.left_frame.grid(row=0, column=0, sticky="nsew", padx=(12, 6), pady=12)
        self.left_frame.rowconfigure(2, weight=1)
        self.left_frame.columnconfigure(0, weight=1)

        # Right: Day Details & Event Inspector
        self.right_frame = ctk.CTkFrame(self, fg_color="#141824", corner_radius=12, border_width=1, border_color="#1e2538")
        self.right_frame.grid(row=0, column=1, sticky="nsew", padx=(6, 12), pady=12)
        self.right_frame.rowconfigure(1, weight=1)
        self.right_frame.columnconfigure(0, weight=1)

        # Setup Left Header (Month / Year Controls)
        cal_nav = ctk.CTkFrame(self.left_frame, fg_color="transparent")
        cal_nav.grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 8))
        cal_nav.columnconfigure(1, weight=1)

        self.prev_btn = ctk.CTkButton(
            cal_nav, text="◀ Prev", width=70, height=28,
            fg_color="#1e293b", hover_color="#334155", command=self._prev_month
        )
        self.prev_btn.grid(row=0, column=0, sticky="w")

        self.month_label = ctk.CTkLabel(
            cal_nav, text="",
            font=ctk.CTkFont(family="Consolas", size=15, weight="bold"),
            text_color="#f8fafc"
        )
        self.month_label.grid(row=0, column=1, sticky="ew")

        btn_box = ctk.CTkFrame(cal_nav, fg_color="transparent")
        btn_box.grid(row=0, column=2, sticky="e")

        ctk.CTkButton(
            btn_box, text="Today", width=60, height=28,
            fg_color="#334155", hover_color="#475569", command=self._jump_to_today
        ).pack(side="left", padx=(0, 6))

        ctk.CTkButton(
            btn_box, text="Next ▶", width=70, height=28,
            fg_color="#1e293b", hover_color="#334155", command=self._next_month
        ).pack(side="left")

        # Day of Week Header Row
        dow_frame = ctk.CTkFrame(self.left_frame, fg_color="#0e111a", height=28, corner_radius=6)
        dow_frame.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 6))
        for col_idx, day_name in enumerate(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]):
            dow_frame.columnconfigure(col_idx, weight=1)
            ctk.CTkLabel(
                dow_frame, text=day_name,
                font=ctk.CTkFont(family="Consolas", size=11, weight="bold"),
                text_color="#94a3b8" if col_idx < 5 else "#38bdf8"
            ).grid(row=0, column=col_idx, pady=3)

        # 6x7 Month Grid Frame
        self.grid_container = ctk.CTkFrame(self.left_frame, fg_color="transparent")
        self.grid_container.grid(row=2, column=0, sticky="nsew", padx=12, pady=(0, 12))
        for r in range(6):
            self.grid_container.rowconfigure(r, weight=1)
        for c in range(7):
            self.grid_container.columnconfigure(c, weight=1)

        # Right Header
        self.detail_hdr = ctk.CTkLabel(
            self.right_frame, text="",
            font=ctk.CTkFont(family="Consolas", size=13, weight="bold"),
            text_color="#38bdf8"
        )
        self.detail_hdr.grid(row=0, column=0, sticky="w", padx=16, pady=(14, 4))

        # Event List Scroll Area
        self.events_scroll = ctk.CTkScrollableFrame(self.right_frame, fg_color="#0b0e17", corner_radius=8)
        self.events_scroll.grid(row=1, column=0, sticky="nsew", padx=12, pady=6)
        self.events_scroll.columnconfigure(0, weight=1)

        # Add Event Drawer (Bottom Right)
        self._setup_add_event_form()

    def _setup_add_event_form(self):
        form_frame = ctk.CTkFrame(self.right_frame, fg_color="#0e111a", corner_radius=8)
        form_frame.grid(row=2, column=0, sticky="ew", padx=12, pady=(4, 12))

        hdr_row = ctk.CTkFrame(form_frame, fg_color="transparent")
        hdr_row.pack(fill="x", padx=10, pady=(8, 4))

        ctk.CTkLabel(
            hdr_row, text="➕ Add Event / Goal for Selected Day",
            font=ctk.CTkFont(size=11, weight="bold"), text_color="#f8fafc"
        ).pack(side="left")

        self.is_goal_var = tk.BooleanVar(value=False)
        self.goal_chk = ctk.CTkCheckBox(
            hdr_row, text="🎯 Personal Goal", variable=self.is_goal_var,
            checkbox_width=18, checkbox_height=18,
            font=ctk.CTkFont(size=11, weight="bold"), text_color="#fbbf24",
            fg_color="#d97706", hover_color="#b45309",
            command=self._toggle_goal_mode
        )
        self.goal_chk.pack(side="right")

        self.title_entry = ctk.CTkEntry(
            form_frame, placeholder_text="Title (e.g., Dentist appointment or Upgrade Calypso's Model)",
            height=30, fg_color="#1a2030", border_color="#2b354d"
        )
        self.title_entry.pack(fill="x", padx=10, pady=2)

        self.criteria_entry = ctk.CTkEntry(
            form_frame, placeholder_text="Goal Details / Target (e.g., Save $3000, Lose 10 lbs, Read Dune)",
            height=28, fg_color="#1a2030", border_color="#92400e"
        )

        self.row2 = ctk.CTkFrame(form_frame, fg_color="transparent")
        self.row2.pack(fill="x", padx=10, pady=4)

        self.time_entry = ctk.CTkEntry(
            self.row2, placeholder_text="Time (e.g. 08:30am, 14:00)",
            height=30, width=165, fg_color="#1a2030", border_color="#2b354d"
        )
        self.time_entry.pack(side="left", padx=(0, 6))

        self.save_btn = ctk.CTkButton(
            self.row2, text="Save Event", height=30,
            fg_color="#059669", hover_color="#047857",
            font=ctk.CTkFont(weight="bold"), command=self._handle_add_event
        )
        self.save_btn.pack(side="left", fill="x", expand=True)

    def _toggle_goal_mode(self):
        if self.is_goal_var.get():
            self.criteria_entry.pack(fill="x", padx=10, pady=2, before=self.row2)
            self.save_btn.configure(text="🎯 Lock In Goal", fg_color="#d97706", hover_color="#b45309")
        else:
            self.criteria_entry.pack_forget()
            self.save_btn.configure(text="Save Event", fg_color="#059669", hover_color="#047857")

    def refresh(self):
        """Reloads calendar & goal data from disk and refreshes the visual UI."""
        self.manager.load_events()
        if self.goal_manager:
            self.goal_manager.load_goals()
        self._render_calendar_grid()
        self._render_day_events(self.selected_date_str)

    # -------------------------------------------------------------------------
    # CALENDAR NAVIGATION & DRAWING
    # -------------------------------------------------------------------------
    def _jump_to_today(self):
        today = date.today()
        self.current_year = today.year
        self.current_month = today.month
        self.selected_date_str = today.strftime("%Y-%m-%d")
        self._render_calendar_grid()
        self._render_day_events(self.selected_date_str)

    def _prev_month(self):
        if self.current_month == 1:
            self.current_month = 12
            self.current_year -= 1
        else:
            self.current_month -= 1
        self._render_calendar_grid()

    def _next_month(self):
        if self.current_month == 12:
            self.current_month = 1
            self.current_year += 1
        else:
            self.current_month += 1
        self._render_calendar_grid()

    def _render_calendar_grid(self):
        self.manager.load_events()
        month_name = calendar.month_name[self.current_month]
        self.month_label.configure(text=f"{month_name.upper()} {self.current_year}")

        for child in self.grid_container.winfo_children():
            child.destroy()

        cal = calendar.Calendar(firstweekday=0)
        month_matrix = cal.monthdayscalendar(self.current_year, self.current_month)

        today_str = date.today().strftime("%Y-%m-%d")

        for r_idx, week in enumerate(month_matrix):
            for c_idx, day_num in enumerate(week):
                if day_num == 0:
                    empty = ctk.CTkFrame(self.grid_container, fg_color="transparent")
                    empty.grid(row=r_idx, column=c_idx, padx=2, pady=2, sticky="nsew")
                    continue

                cell_date_str = f"{self.current_year:04d}-{self.current_month:02d}-{day_num:02d}"
                day_evts = self.manager.get_events_for_date(cell_date_str)
                has_evts = bool(day_evts)
                has_goal = any(e.get("is_goal") for e in day_evts)
                is_today = (cell_date_str == today_str)
                is_selected = (cell_date_str == self.selected_date_str)

                # Determine styling
                if is_selected:
                    btn_bg = "#2563eb"
                    hover_color = "#1d4ed8"
                    border_color = "#60a5fa"
                    border_w = 2
                elif is_today:
                    btn_bg = "#1e293b"
                    hover_color = "#334155"
                    border_color = "#38bdf8"
                    border_w = 2
                elif has_goal:
                    btn_bg = "#1f1a14"
                    hover_color = "#2d2418"
                    border_color = "#d97706"
                    border_w = 1
                else:
                    btn_bg = "#111624"
                    hover_color = "#1a2233"
                    border_color = "#1e293b"
                    border_w = 1

                # Append a target icon for goal days or bullet dot for normal events
                if has_goal:
                    label_text = f"{day_num}\n🎯"
                    text_color = "#fbbf24" if not is_selected else "#f8fafc"
                elif has_evts:
                    label_text = f"{day_num}\n•"
                    text_color = "#34d399" if not is_selected else "#f8fafc"
                else:
                    label_text = f"{day_num}"
                    text_color = "#f8fafc" if day_num else "#64748b"

                btn = ctk.CTkButton(
                    self.grid_container,
                    text=label_text,
                    font=ctk.CTkFont(family="Consolas", size=12, weight="bold"),
                    fg_color=btn_bg,
                    text_color=text_color,
                    hover_color=hover_color,
                    border_width=border_w,
                    border_color=border_color,
                    corner_radius=6,
                    command=lambda d=cell_date_str: self._on_date_selected(d)
                )
                btn.grid(row=r_idx, column=c_idx, padx=2, pady=2, sticky="nsew")

    def _on_date_selected(self, date_str: str):
        self.selected_date_str = date_str
        self._render_calendar_grid()
        self._render_day_events(date_str)

    # -------------------------------------------------------------------------
    # RIGHT PANEL: EVENTS LIST & ACTIONS
    # -------------------------------------------------------------------------
    def _render_day_events(self, date_str: str):
        self.manager.load_events()
        for widget in self.events_scroll.winfo_children():
            widget.destroy()

        try:
            dt_obj = datetime.strptime(date_str, "%Y-%m-%d")
            formatted_date = dt_obj.strftime("%A, %B %d, %Y")
        except Exception:
            formatted_date = date_str

        self.detail_hdr.configure(text=f"📅 {formatted_date}")

        events = self.manager.get_events_for_date(date_str)
        if not events:
            ctk.CTkLabel(
                self.events_scroll,
                text="No events or goals scheduled for this day.\nUse the form below to add one.",
                font=ctk.CTkFont(size=11, slant="italic"),
                text_color="#64748b",
                justify="center"
            ).pack(pady=40)
            return

        for ev in events:
            is_goal = bool(ev.get("is_goal"))
            border_col = "#d97706" if is_goal else "#1e293b"
            card_bg = "#191714" if is_goal else "#141824"

            card = ctk.CTkFrame(self.events_scroll, fg_color=card_bg, corner_radius=8, border_width=1, border_color=border_col)
            card.pack(fill="x", padx=4, pady=4)

            top_row = ctk.CTkFrame(card, fg_color="transparent")
            top_row.pack(fill="x", padx=10, pady=(8, 2))

            title_col = "#fbbf24" if is_goal else "#f8fafc"
            ctk.CTkLabel(
                top_row, text=ev.get("title", "Untitled"),
                font=ctk.CTkFont(size=12, weight="bold"), text_color=title_col,
                wraplength=230, justify="left"
            ).pack(side="left")

            del_btn = ctk.CTkButton(
                top_row, text="✕", width=24, height=24,
                fg_color="#991b1b", hover_color="#dc2626",
                font=ctk.CTkFont(size=11, weight="bold"),
                command=lambda e_obj=ev: self._handle_delete_event(e_obj)
            )
            del_btn.pack(side="right")

            notes_str = ev.get("notes", "")
            if notes_str:
                ctk.CTkLabel(
                    card, text=f"📌 {notes_str}",
                    font=ctk.CTkFont(size=11), text_color="#cbd5e1",
                    wraplength=260, justify="left"
                ).pack(anchor="w", padx=10, pady=(0, 4))

            time_str = ev.get("time", "")
            if time_str:
                bot_row = ctk.CTkFrame(card, fg_color="transparent")
                bot_row.pack(fill="x", padx=10, pady=(2, 8))

                ctk.CTkLabel(
                    bot_row, text=f"⏰ {time_str}",
                    font=ctk.CTkFont(family="Consolas", size=10), text_color="#38bdf8"
                ).pack(side="left")

                if self.alarm_service and not is_goal:
                    alarm_btn = ctk.CTkButton(
                        bot_row, text="Arm Alarm ⏰", width=85, height=22,
                        fg_color="#2563eb", hover_color="#1d4ed8",
                        font=ctk.CTkFont(family="Consolas", size=9, weight="bold"),
                        command=lambda t=time_str: self._arm_event_alarm(t)
                    )
                    alarm_btn.pack(side="right")

    def _handle_add_event(self):
        title = self.title_entry.get().strip()
        time_val = self.time_entry.get().strip()
        criteria_val = self.criteria_entry.get().strip()
        is_goal = self.is_goal_var.get()

        if not title:
            messagebox.showwarning("Title Required", "Please provide a title for the event or goal.", parent=self)
            return

        if is_goal and self.goal_manager:
            ok, msg, goal = self.goal_manager.create_goal(
                title=title,
                target_date_str=self.selected_date_str,
                criteria=criteria_val,
                time_str=time_val,
                source="calendar"
            )
            if not ok:
                messagebox.showwarning("Goal Notice", msg, parent=self)
                return

            self.manager.load_events()
            self.title_entry.delete(0, "end")
            self.time_entry.delete(0, "end")
            self.criteria_entry.delete(0, "end")
            self.is_goal_var.set(False)
            self._toggle_goal_mode()

            self._render_calendar_grid()
            self._render_day_events(self.selected_date_str)

            # Trigger immediate discussion with Calypso in chat!
            if callable(self.on_goal_created_callback) and goal:
                try:
                    self.on_goal_created_callback(goal)
                except Exception as e:
                    print(f"[Calendar] Goal discussion callback error: {e}")
            return

        self.manager.add_event(self.selected_date_str, title, time_val, notes=criteria_val)
        self.title_entry.delete(0, "end")
        self.time_entry.delete(0, "end")
        self.criteria_entry.delete(0, "end")

        self._render_calendar_grid()
        self._render_day_events(self.selected_date_str)

    def _handle_delete_event(self, ev: dict):
        if isinstance(ev, str):
            event_id = ev
            goal_id = None
        else:
            event_id = ev.get("id", "")
            goal_id = ev.get("goal_id")

        if goal_id and self.goal_manager:
            self.goal_manager.remove_goal(goal_id)
            self.manager.load_events()
            self._render_calendar_grid()
            self._render_day_events(self.selected_date_str)
            return

        if self.manager.delete_event(self.selected_date_str, event_id):
            self._render_calendar_grid()
            self._render_day_events(self.selected_date_str)

    def _arm_event_alarm(self, time_val: str):
        if not self.alarm_service:
            messagebox.showinfo("Alarm", "Alarm service not available.", parent=self)
            return

        success, msg = self.alarm_service.set_alarm(time_val)
        if success:
            if self.on_alarm_set_callback:
                self.on_alarm_set_callback(f"⏰ [Alarm]: {msg}")
            messagebox.showinfo("Alarm Armed", msg, parent=self)
        else:
            messagebox.showerror("Alarm Error", msg, parent=self)
