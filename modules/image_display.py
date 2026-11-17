# modules/image_display.py

import os
import sys
import platform
import ctypes
import subprocess
import re
from pathlib import Path
import tkinter as tk
from PIL import Image, ImageTk, ImageOps

SUPPORTED_EXTENSIONS = ('.png', '.jpg', '.jpeg', '.webp', '.bmp', '.gif')


class BorderlessViewer:
    """
    Borderless, draggable image slideshow and viewer designed to integrate
    seamlessly with Calypso's main GUI as a Toplevel window.
    
    Features:
    - Double-click to toggle fullscreen on the CURRENT monitor only
    - Press 'M' to cycle through connected monitors
    - Dynamic aspect-ratio-preserving scaling
    - Safe drag behavior (disabled in fullscreen)
    """
    def __init__(self, parent_root, folder_or_file_path, width=1080, height=1920, interval=30):
        self.parent = parent_root
        self.interval = float(interval)
        self._after_id = None
        self.drag_x = 0
        self.drag_y = 0
        
        # Fullscreen state management
        self.is_fullscreen = False
        self.windowed_state = {"x": None, "y": None, "w": width, "h": height}

        # Multi-monitor support
        self.current_monitor_index = 0
        self.monitors = []
        if platform.system() == "Linux":
            self.monitors = self._get_linux_monitors()

        # Resolve paths and initial selection
        target_path = Path(folder_or_file_path)
        if target_path.is_file():
            folder_path = target_path.parent
            initial_target = str(target_path.resolve())
        else:
            folder_path = target_path
            initial_target = None

        self.images = self.load_image_paths(str(folder_path))
        if not self.images:
            raise FileNotFoundError(f"No supported images found in '{folder_path}'.")

        # Determine start index
        self.current_index = 0
        if initial_target and initial_target in self.images:
            self.current_index = self.images.index(initial_target)

        # 1. Create Toplevel attached to Calypso's root
        self.top = tk.Toplevel(self.parent)
        self.top.overrideredirect(True)
        self.top.config(bg="black")
        self.top.attributes("-topmost", True)

        # 2. Center on the first detected monitor (or virtual desktop fallback)
        if self.monitors:
            mon = self.monitors[0]
            pos_x = mon['x'] + (mon['w'] - width) // 2
            pos_y = mon['y'] + (mon['h'] - height) // 2
        else:
            screen_w = self.top.winfo_screenwidth()
            screen_h = self.top.winfo_screenheight()
            pos_x = max(0, (screen_w - width) // 2)
            pos_y = max(0, (screen_h - height) // 2)
            
        self.top.geometry(f"{width}x{height}+{pos_x}+{pos_y}")

        # 3. Canvas (auto-fills window due to pack options)
        self.canvas = tk.Canvas(
            self.top, width=width, height=height,
            bg="black", highlightthickness=0
        )
        self.canvas.pack(fill=tk.BOTH, expand=True)

        # 4. Bind events & capture keyboard focus
        self.bind_events()
        self.top.focus_force()

        # Ensure Tkinter has processed geometry before measuring dimensions
        self.top.update_idletasks()

        # 5. Display image & begin slideshow if timer provided
        self.show_image()
        if self.interval > 0:
            self._after_id = self.top.after(int(self.interval * 1000), self.auto_cycle)

    def load_image_paths(self, folder):
        if not os.path.isdir(folder):
            return []
        files = [
            os.path.join(folder, f)
            for f in sorted(os.listdir(folder))
            if f.lower().endswith(SUPPORTED_EXTENSIONS)
        ]
        return files

    def bind_events(self):
        # Exit shortcuts
        self.top.bind("<Escape>", lambda e: self.close())
        self.top.bind("q", lambda e: self.close())
        self.top.bind("Q", lambda e: self.close())

        # Cycle forwards
        self.top.bind("<Right>", lambda e: self.next_image())
        self.top.bind("<space>", lambda e: self.next_image())

        # Cycle backwards
        self.top.bind("<Left>", lambda e: self.prev_image())
        self.top.bind("<BackSpace>", lambda e: self.prev_image())

        # Window drag handlers
        self.canvas.bind("<Button-1>", self.start_drag)
        self.canvas.bind("<B1-Motion>", self.do_drag)
        
        # Double-click to toggle fullscreen
        self.canvas.bind("<Double-Button-1>", self.toggle_fullscreen)

        # Monitor cycling hotkey
        self.top.bind("<m>", lambda e: self.switch_monitor())
        self.top.bind("<M>", lambda e: self.switch_monitor())

    def start_drag(self, event):
        # Disable dragging while in fullscreen to prevent accidental window movement
        if self.is_fullscreen:
            return
        self.drag_x = event.x
        self.drag_y = event.y

    def do_drag(self, event):
        if self.is_fullscreen:
            return
        deltax = event.x - self.drag_x
        deltay = event.y - self.drag_y
        x = self.top.winfo_x() + deltax
        y = self.top.winfo_y() + deltay
        self.top.geometry(f"+{x}+{y}")

    def _get_linux_monitors(self):
        """
        Queries xrandr to get connected monitors and their exact bounds.
        Returns a list of dicts: [{'name': 'HDMI-1', 'x': 0, 'y': 0, 'w': 1920, 'h': 1080}, ...]
        """
        try:
            result = subprocess.run(['xrandr', '--query'], capture_output=True, text=True, check=True)
            monitors = []
            for line in result.stdout.splitlines():
                if ' connected' in line:
                    name = line.split()[0]
                    # Extract active resolution and position from the connected line
                    match = re.search(r'(\d+)x(\d+)\+(\d+)\+(\d+)', line)
                    if match:
                        monitors.append({
                            'name': name,
                            'w': int(match.group(1)),
                            'h': int(match.group(2)),
                            'x': int(match.group(3)),
                            'y': int(match.group(4))
                        })
            return monitors
        except Exception as e:
            print(f"[ImageViewer] xrandr query failed or unavailable: {e}")
            return []

    def _get_current_monitor_bounds(self):
        """
        Returns (x, y, width, height) of the currently selected monitor.
        Falls back to Windows API or virtual desktop if needed.
        """
        if self.monitors:
            mon = self.monitors[self.current_monitor_index]
            return mon['x'], mon['y'], mon['w'], mon['h']

        if platform.system() == "Windows":
            try:
                hwnd = self.top.winfo_id()
                hmonitor = ctypes.windll.user32.MonitorFromWindow(hwnd, 2)
                if hmonitor:
                    class MONITORINFO(ctypes.Structure):
                        _fields_ = [
                            ("cbSize", ctypes.c_ulong),
                            ("rcMonitor", ctypes.c_long * 4),
                            ("rcWork", ctypes.c_long * 4),
                            ("dwFlags", ctypes.c_ulong)
                        ]
                    mi = MONITORINFO()
                    mi.cbSize = ctypes.sizeof(MONITORINFO)
                    ctypes.windll.user32.GetMonitorInfoW(hmonitor, ctypes.byref(mi))
                    left, top, right, bottom = mi.rcMonitor
                    w, h = right - left, bottom - top
                    if w > 0 and h > 0:
                        return left, top, w, h
            except Exception:
                pass

        # Fallback to virtual desktop
        return 0, 0, self.top.winfo_screenwidth(), self.top.winfo_screenheight()

    def toggle_fullscreen(self, event=None):
        if not self.is_fullscreen:
            # Save current windowed position & size
            self.windowed_state["x"] = self.top.winfo_x()
            self.windowed_state["y"] = self.top.winfo_y()
            self.windowed_state["w"] = self.top.winfo_width()
            self.windowed_state["h"] = self.top.winfo_height()

            # Get exact bounds of the selected monitor
            mon_x, mon_y, mon_w, mon_h = self._get_current_monitor_bounds()
            self.top.geometry(f"{mon_w}x{mon_h}+{mon_x}+{mon_y}")
            self.is_fullscreen = True
        else:
            # Restore previous windowed state
            self.top.geometry(
                f"{self.windowed_state['w']}x{self.windowed_state['h']}+"
                f"{self.windowed_state['x']}+{self.windowed_state['y']}"
            )
            self.is_fullscreen = False

        # Force Tkinter to apply geometry changes before measuring
        self.top.update_idletasks()
        
        # Redraw image to fit new dimensions
        self.show_image()

    def switch_monitor(self):
        """Cycle to the next connected monitor and reposition the window."""
        if not self.monitors:
            return
            
        self.current_monitor_index = (self.current_monitor_index + 1) % len(self.monitors)
        mon = self.monitors[self.current_monitor_index]

        # Update saved windowed position to center on the new monitor
        self.windowed_state['x'] = mon['x'] + (mon['w'] - self.windowed_state['w']) // 2
        self.windowed_state['y'] = mon['y'] + (mon['h'] - self.windowed_state['h']) // 2

        if self.is_fullscreen:
            self.top.geometry(f"{mon['w']}x{mon['h']}+{mon['x']}+{mon['y']}")
        else:
            self.top.geometry(
                f"{self.windowed_state['w']}x{self.windowed_state['h']}+"
                f"{self.windowed_state['x']}+{self.windowed_state['y']}"
            )

        self.top.update_idletasks()
        self.show_image()

    def show_image(self):
        if not self.images:
            return

        img_path = self.images[self.current_index]

        try:
            with Image.open(img_path) as img:
                # Correct orientation for camera shots
                img = ImageOps.exif_transpose(img)

                # Get current canvas dimensions
                c_w = self.canvas.winfo_width()
                c_h = self.canvas.winfo_height()

                # Fallback if canvas hasn't been rendered yet
                if c_w <= 0 or c_h <= 0:
                    c_w, c_h = self.windowed_state["w"], self.windowed_state["h"]

                # Calculate scaling ratio to preserve aspect ratio
                ratio = min(c_w / img.width, c_h / img.height)
                new_w = int(img.width * ratio)
                new_h = int(img.height * ratio)

                # High-quality downscaling/upscaling
                img_resized = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
                self.tk_img = ImageTk.PhotoImage(img_resized)

                self.canvas.delete("all")
                self.canvas.create_image(c_w // 2, c_h // 2, anchor=tk.CENTER, image=self.tk_img)
        except Exception as e:
            print(f"[ImageViewer] Failed to load {img_path}: {e}")

    def next_image(self):
        if not self.images:
            return
        self.current_index = (self.current_index + 1) % len(self.images)
        self.show_image()

    def prev_image(self):
        if not self.images:
            return
        self.current_index = (self.current_index - 1) % len(self.images)
        self.show_image()

    def auto_cycle(self):
        self.next_image()
        if self.interval > 0 and self.top.winfo_exists():
            self._after_id = self.top.after(int(self.interval * 1000), self.auto_cycle)

    def close(self):
        if self._after_id:
            try:
                self.top.after_cancel(self._after_id)
            except Exception:
                pass
        self.top.destroy()

