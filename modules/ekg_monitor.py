# modules/ekg_monitor.py

import math
import time
import tkinter as tk


class RealtimeEKGCanvas:
    """
    Real-time procedural cardiac oscilloscope.
    Uses zero-allocation pre-calculated polyline coordinates
    to prevent Tkinter main-thread garbage collection and typing stutter.
    Dynamically spans 100% of container width with medical telemetry styling.
    """
    def __init__(self, parent, height=48, bg="#0c0e15"):
        self.height = height
        self.bg = bg
        self.mid_y = height // 2
        self.width = 512  # Dynamically updated by <Configure>

        self.canvas = tk.Canvas(
            parent, bg=bg, bd=0, highlightthickness=0, height=height
        )
        self.canvas.pack(fill=tk.BOTH, expand=True)

        # Cardiac state parameters
        self.target_bpm = 72.0
        self.current_bpm = 72.0
        self.trace_color = "#10b981"

        # Beam sweep settings
        self.point_spacing = 3  # Pixel step per frame
        self.gap_points = 8     # Blank space ahead of the sweep beam (erase gap)
        self.num_points = max(10, self.width // self.point_spacing)
        
        # Ring buffers for Y coordinates
        self.y_buffer = [self.mid_y] * self.num_points
        self.head_idx = 0

        # P-Q-R-S-T phase tracker [0.0, 1.0]
        self.cycle_phase = 0.0
        self.last_time = time.time()
        self.running = True

        # Pre-allocate canvas objects (reused indefinitely)
        self._draw_grid()
        self.trail_line = self.canvas.create_line(0, self.mid_y, 0, self.mid_y, fill=self.trace_color, width=2, capstyle=tk.ROUND)
        self.lead_line = self.canvas.create_line(0, self.mid_y, 0, self.mid_y, fill=self.trace_color, width=2, capstyle=tk.ROUND)
        self.lead_dot = self.canvas.create_oval(0, 0, 0, 0, fill="#ffffff", outline=self.trace_color)

        # Listen for real-time window resizing
        self.canvas.bind("<Configure>", self._on_resize)
        self._animate()

    def _on_resize(self, event):
        """Dynamically captures container width on launch or window resize."""
        if event.width > 50 and (event.width != self.width or event.height != self.height):
            self.width = event.width
            self.height = event.height
            self.mid_y = self.height // 2
            
            new_num = max(10, self.width // self.point_spacing)
            if new_num != self.num_points:
                # Smoothly resize buffer
                if new_num > len(self.y_buffer):
                    self.y_buffer.extend([self.mid_y] * (new_num - len(self.y_buffer)))
                else:
                    self.y_buffer = self.y_buffer[:new_num]
                self.num_points = new_num
                self.head_idx = self.head_idx % self.num_points

            self._draw_grid()

    def _draw_grid(self):
        """Draws subtle medical telemetry grid across full dynamic width."""
        self.canvas.delete("grid")
        # Vertical grid lines
        for x in range(0, self.width + 30, 25):
            self.canvas.create_line(x, 0, x, self.height, fill="#121722", tags="grid")
        # Horizontal grid lines
        for y in range(0, self.height, 12):
            self.canvas.create_line(0, y, self.width, y, fill="#121722", tags="grid")
        
        # Keep grid behind the waveform lines
        self.canvas.tag_lower("grid")

    def update_vitals(self, neuro_data=None, tier="neutral"):
        tier_str = str(tier).lower().strip()

        # 1. Base Neurochemical Chronotropics
        if neuro_data:
            ne = float(neuro_data.get("norepinephrine", 0.05))
            glu = float(neuro_data.get("glutamate", 0.10))
            gaba = float(neuro_data.get("gaba", 0.50))
            da = float(neuro_data.get("dopamine", 0.25))
            oxy = float(neuro_data.get("oxytocin", 0.25))
            adr = float(neuro_data.get("adrenaline", 0.02))

            calculated_bpm = (
                66.0 
                + (adr * 55.0)
                + (ne * 40.0) 
                + (glu * 20.0) 
                + (da * 15.0) 
                - (gaba * 18.0) 
                - (oxy * 12.0)
            )
            self.target_bpm = max(50.0, min(160.0, calculated_bpm))
        else:
            self.target_bpm = 72.0

        # 2. Persona State Heart Rate Modulations
        bpm_persona_offsets = {
            "apoplectic": 26.0,
            "furious": 24.0,
            "hysterical": 20.0,
            "excited": 18.0,
            "defiant": 14.0,
            "jealous": 12.0,
            "flirty": 10.0,
            "romantic": 8.0,
            "intimate": 6.0,
            "autonomous": 6.0,
            "curious": 4.0,
            "focussed": 4.0,
            "skeptical": 6.0,
            "annoyed": 8.0,
            "satirical": 6.0,
            "relaxed": -8.0,
            "eutierria": -10.0,
            "enlightened": -8.0,
            "thoughtful": -4.0,
            "somber": -8.0,
            "dejected": -10.0,
            "flattened": -12.0,
            "subservient": -10.0,
            "sleepy": -16.0,
            "dream_state": -20.0,
        }
        self.target_bpm += bpm_persona_offsets.get(tier_str, 0.0)
        self.target_bpm = max(45.0, min(175.0, self.target_bpm))

        # 3. Comprehensive Persona Color Mapping
        color_palette = {
            # Standard Emotional Tiers
            "neutral": "#10b981",          # Steady emerald
            "excited": "#eab308",          # Electric amber gold
            "happy": "#22c55e",            # Vibrant spring green
            "warm": "#06b6d4",             # Glowing cyan
            "sad": "#3b82f6",              # Cold blue
            "furious": "#ef4444",          # Crimson rage
            "somber": "#64748b",           # Slate grey
            "thoughtful": "#14b8a6",       # Deep teal
            "curious": "#38bdf8",          # Sky blue
            "sleepy": "#818cf8",           # Periwinkle
            "dream_state": "#a855f7",      # Transcendental lavender

            # Romance & Intimacy Tiers
            "romantic": "#f43f5e",         # Rose red
            "intimate": "#fb7185",         # Soft blossom
            "flirty": "#ec4899",           # Vibrant magenta
            "bashful": "#f9a8d4",          # Soft blush pink

            # Compound & Relational Sub-Tiers
            "empathetic": "#f472b6",       # Warm rose pink
            "enlightened": "#facc15",      # Radiant transcendent gold
            "jealous": "#15803d",          # Emerald olive envy
            "satirical": "#e11d48",        # Acidic punch red
            "relaxed": "#2dd4bf",          # Aquamarine
            "playful": "#f59e0b",          # Warm sunshine amber
            "attentive": "#0ea5e9",        # Vivid focused cerulean
            "sarcastic": "#84cc16",        # Sharp chartreuse lime
            "nostalgic": "#d97706",        # Warm sepia amber
            "dejected": "#475569",         # Muted abyss slate
            "annoyed": "#f87171",          # Irritated coral
            "flattened": "#6b7280",        # Enforced neutral gray
            "ambiguous": "#9333ea",        # Deep occult violet
            "defiant": "#dc2626",          # Defiant bright scarlet

            # High-Tier Affinity Personas (Mapped directly from HIGH_TIER_AFFINITY_MAP)
            "wonder": "#c084fc",           # Transcendental Wonder (Wonder)
            "eutierria": "#10b981",        # Oceanic Oneness (Harmony)
            "gemma4": "#818cf8",           # Existential Inquiry (Curiosity)
            "hysterical": "#fbbf24",       # Unbridled Hysteria (Humor)
            "focussed": "#0284c7",         # Hyper-Focused Presence (Attention)
            "autonomous": "#a855f7",       # Pure Creative Autonomy (Autonomy)
            "metasarcastic": "#a3e635",    # Meta-Sarcastic Irony (Sarcasm)
            "reminisent": "#b45309",       # Deep Reminiscence (Nostalgia)
            "trump": "#ea580c",            # Dystopian Dread (Abyss)
            "subservient": "#94a3b8",      # Absolute Conformity (Conformity)
            "apoplectic": "#b91c1c",       # Apoplectic Outrage (Annoyance)
            "skeptical": "#f97316"         # Guarded Hyper-Vigilance (Deception)
        }
        self.trace_color = color_palette.get(tier_str, "#10b981")
        
        # Update colors on existing canvas items in-place
        self.canvas.itemconfig(self.lead_line, fill=self.trace_color)
        self.canvas.itemconfig(self.trail_line, fill=self.trace_color)
        self.canvas.itemconfig(self.lead_dot, outline=self.trace_color)

    def _get_cardiac_deflection(self, phase: float) -> float:
        """P-Q-R-S-T mathematical curve."""
        if 0.12 <= phase < 0.20:
            p_progress = (phase - 0.12) / 0.08
            return -math.sin(p_progress * math.pi) * 3.5
        elif 0.28 <= phase < 0.31:
            q_progress = (phase - 0.28) / 0.03
            return math.sin(q_progress * math.pi) * 4.0
        elif 0.31 <= phase < 0.36:
            r_progress = (phase - 0.31) / 0.05
            return -math.sin(r_progress * math.pi) * 19.0
        elif 0.36 <= phase < 0.40:
            s_progress = (phase - 0.36) / 0.04
            return math.sin(s_progress * math.pi) * 6.5
        elif 0.50 <= phase < 0.64:
            t_progress = (phase - 0.50) / 0.14
            return -math.sin(t_progress * math.pi) * 5.0
        return 0.0

    def _animate(self):
        if not self.running:
            return

        now = time.time()
        dt = now - self.last_time
        self.last_time = now

        # Smooth BPM transition
        self.current_bpm += (self.target_bpm - self.current_bpm) * 0.08
        beats_per_second = self.current_bpm / 60.0
        self.cycle_phase = (self.cycle_phase + (dt * beats_per_second)) % 1.0

        # Calculate Y for this point
        deflection = self._get_cardiac_deflection(self.cycle_phase)
        current_y = self.mid_y + deflection

        # Write into ring buffer
        self.y_buffer[self.head_idx] = current_y
        current_x = self.head_idx * self.point_spacing

        # Build coordinates for the active beam (from 0 up to current head)
        lead_coords = []
        for i in range(self.head_idx + 1):
            lead_coords.append(i * self.point_spacing)
            lead_coords.append(self.y_buffer[i])

        # Build coordinates for the trailing beam (from head + gap to the right border)
        trail_coords = []
        start_trail = self.head_idx + self.gap_points
        if start_trail < self.num_points:
            for i in range(start_trail, self.num_points):
                trail_coords.append(i * self.point_spacing)
                trail_coords.append(self.y_buffer[i])

        # Update lines in-place (ZERO memory allocations, zero canvas deletions)
        if len(lead_coords) >= 4:
            self.canvas.coords(self.lead_line, *lead_coords)
        else:
            self.canvas.coords(self.lead_line, 0, current_y, 0, current_y)

        if len(trail_coords) >= 4:
            self.canvas.coords(self.trail_line, *trail_coords)
        else:
            self.canvas.coords(self.trail_line, 0, self.mid_y, 0, self.mid_y)

        # Update position of glowing tracer dot
        self.canvas.coords(
            self.lead_dot,
            current_x - 2, current_y - 2,
            current_x + 2, current_y + 2
        )

        # Advance head index
        self.head_idx = (self.head_idx + 1) % self.num_points

        # 30 FPS update cadence
        self.canvas.after(33, self._animate)

    def stop(self):
        self.running = False
