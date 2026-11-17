# modules/debugger.py

import json
import logging
import math
import os
import platform
import sys
import threading
import time
import traceback
import urllib.request
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import customtkinter as ctk
import torch

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

from modules.config import config


# =========================================================================
# LOGGING RING-BUFFER HANDLER
# =========================================================================
class RingBufferLogHandler(logging.Handler):
    """Captures live logging records in memory for the Debugger HUD."""
    def __init__(self, capacity: int = 150):
        super().__init__()
        self.buffer = deque(maxlen=capacity)

    def emit(self, record):
        try:
            msg = self.format(record)
            self.buffer.append({
                "time": datetime.fromtimestamp(record.created).strftime("%H:%M:%S"),
                "level": record.levelname,
                "logger": record.name,
                "msg": msg
            })
        except Exception:
            pass


# =========================================================================
# CORE DIAGNOSTIC ENGINE & SENTRY
# =========================================================================
class DiagnosticEngine:
    def __init__(self, logger: Optional[logging.Logger] = None):
        self.logger = logger or logging.getLogger("Calypso.Diagnostics")
        self.start_time = time.time()
        self.thread_crashes = deque(maxlen=20)
        self.recent_llm_exchanges = deque(maxlen=10)
        self.gui_notifier = None

        # Memory dumps directory
        self.dump_dir = config.BASE_DIR / "logs" / "crash_dumps"
        self.dump_dir.mkdir(parents=True, exist_ok=True)

        # Attach memory log handler
        self.log_handler = RingBufferLogHandler(capacity=200)
        self.log_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
        root_logger = logging.getLogger()
        root_logger.addHandler(self.log_handler)

    def install_thread_hooks(self, gui_notifier=None):
        """Installs global unhandled exception hooks for the main process and threads."""
        self.gui_notifier = gui_notifier

        def _global_excepthook(exc_type, exc_value, exc_traceback):
            err_str = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
            self.logger.critical(f"FATAL UNHANDLED EXCEPTION:\n{err_str}")
            self._record_crash("MainThread", str(exc_value), err_str)
            if self.gui_notifier:
                self.gui_notifier(f"🛑 [Fatal Error]: {exc_value}")
            sys.__excepthook__(exc_type, exc_value, exc_traceback)

        sys.excepthook = _global_excepthook

        def _thread_excepthook(args):
            err_str = "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback))
            thread_name = args.thread.name if args.thread else "UnknownThread"
            self.logger.error(f"BACKGROUND THREAD CRASH [{thread_name}]:\n{err_str}")
            self._record_crash(thread_name, str(args.exc_value), err_str)
            if self.gui_notifier:
                self.gui_notifier(f"⚠️ [Thread Crash in '{thread_name}']: {args.exc_value}")

        threading.excepthook = _thread_excepthook
        self.logger.info("[✓] Diagnostic Thread Sentries & Global Exception Hooks Installed.")

    def _record_crash(self, thread_name: str, reason: str, stack: str):
        self.thread_crashes.append({
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "thread": thread_name,
            "reason": reason,
            "stack": stack
        })

    def record_llm_stream(self, system_prompt: str, user_prompt: str, raw_output: str, cleaned_output: str):
        """Records raw vs. cleaned token responses for debugging syntax tags."""
        self.recent_llm_exchanges.append({
            "timestamp": datetime.now().strftime("%H:%M:%S"),
            "system_len": len(system_prompt),
            "user_prompt": user_prompt[:150],
            "raw_output": raw_output,
            "cleaned_output": cleaned_output
        })


# ---------------------------------------------------------------------
    # SUBSYSTEM BOOT SANITY PROBE
    # ---------------------------------------------------------------------
    def run_boot_diagnostics(self, ollama_url: str, model_name: str) -> Dict[str, Any]:
        """Runs a non-blocking hardware & API handshake report at system boot."""
        cuda_devices = []
        if torch.cuda.is_available():
            for i in range(torch.cuda.device_count()):
                try:
                    free_b, total_b = torch.cuda.mem_get_info(i)
                    props = torch.cuda.get_device_properties(i)
                    cuda_devices.append({
                        "index": i,
                        "name": torch.cuda.get_device_name(i),
                        "compute_capability": f"{props.major}.{props.minor}",
                        "total_mb": round(total_b / (1024 * 1024), 1),
                        "free_mb": round(free_b / (1024 * 1024), 1)
                    })
                except Exception as e:
                    cuda_devices.append({"index": i, "name": torch.cuda.get_device_name(i), "error": str(e)})

        report = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "platform": platform.platform(),
            "python": platform.python_version(),
            "cuda_available": torch.cuda.is_available(),
            "cuda_device_count": len(cuda_devices),
            "cuda_devices": cuda_devices,
            "ollama_reachable": False,
            "model_ready": False,
            "dirs_valid": True,
            "errors": []
        }

        # Check directories
        critical_dirs = [config.MEMORY_DIR, config.WORKSPACE_DIR, config.INPUT_DIR, config.OUTPUT_DIR]
        for d in critical_dirs:
            if not d.exists():
                try:
                    d.mkdir(parents=True, exist_ok=True)
                except Exception as e:
                    report["dirs_valid"] = False
                    report["errors"].append(f"Directory failure '{d.name}': {e}")

        # Check Ollama
        try:
            base_url = ollama_url.split("/api")[0]
            req = urllib.request.Request(f"{base_url}/api/tags", headers={"User-Agent": "CalypsoDebugger"})
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                report["ollama_reachable"] = True
                installed_models = [m.get("name", "") for m in data.get("models", [])]
                report["installed_models"] = installed_models
                report["model_ready"] = any(model_name in m for m in installed_models)
                if not report["model_ready"]:
                    report["errors"].append(f"Target LLM '{model_name}' not listed in Ollama.")
        except Exception as e:
            report["errors"].append(f"Ollama connection error: {e}")

        return report

    # ---------------------------------------------------------------------
    # METRICS & MULTI-GPU HARDWARE QUERIES
    # ---------------------------------------------------------------------
    def get_vram_stats(self) -> Dict[str, Any]:
        """Returns accurate per-card GPU VRAM metrics across all detected GPUs."""
        if not torch.cuda.is_available():
            return {
                "active": False,
                "device_count": 0,
                "devices": [],
                "allocated_mb": 0,
                "reserved_mb": 0,
                "total_mb": 0,
                "percent": 0.0
            }

        devices = []
        try:
            device_count = torch.cuda.device_count()
            for i in range(device_count):
                try:
                    free_bytes, total_bytes = torch.cuda.mem_get_info(i)
                    allocated = torch.cuda.memory_allocated(i)
                    reserved = torch.cuda.memory_reserved(i)

                    total_mb = total_bytes / (1024 * 1024)
                    allocated_mb = allocated / (1024 * 1024)
                    reserved_mb = reserved / (1024 * 1024)
                    used_mb = (total_bytes - free_bytes) / (1024 * 1024)
                    percent = (used_mb / total_mb) * 100.0 if total_mb > 0 else 0.0

                    props = torch.cuda.get_device_properties(i)
                    compute_cap = f"{props.major}.{props.minor}"

                    devices.append({
                        "index": i,
                        "name": torch.cuda.get_device_name(i),
                        "compute_capability": compute_cap,
                        "total_mb": round(total_mb, 1),
                        "used_mb": round(used_mb, 1),
                        "free_mb": round(free_bytes / (1024 * 1024), 1),
                        "allocated_mb": round(allocated_mb, 1),
                        "reserved_mb": round(reserved_mb, 1),
                        "percent": round(percent, 1)
                    })
                except Exception as dev_err:
                    devices.append({
                        "index": i,
                        "name": f"cuda:{i}",
                        "error": str(dev_err)
                    })

            primary = devices[0] if devices else {}
            return {
                "active": True,
                "device_count": device_count,
                "devices": devices,
                # Backward compatibility
                "device_name": primary.get("name", "N/A"),
                "allocated_mb": primary.get("allocated_mb", 0),
                "reserved_mb": primary.get("reserved_mb", 0),
                "total_mb": primary.get("total_mb", 0),
                "percent": primary.get("percent", 0.0)
            }
        except Exception as e:
            return {"active": False, "device_count": 0, "devices": [], "error": str(e)}
    def audit_limbic_state(self, neuro, esteem, affinity) -> List[str]:
        """Verifies biological variables remain bounded; clamps runaway values."""
        corrections = []

        if neuro and hasattr(neuro, "chemicals") and hasattr(neuro, "lock"):
            with neuro.lock:
                for chem, val in list(neuro.chemicals.items()):
                    if val is None or math.isnan(val):
                        neuro.chemicals[chem] = 0.50
                        corrections.append(f"Clamped NaN/None in '{chem}' to 0.50")
                    elif val < 0.0:
                        neuro.chemicals[chem] = 0.0
                        corrections.append(f"Clamped negative value in '{chem}' to 0.0")
                    elif val > 1.0:
                        neuro.chemicals[chem] = 1.0
                        corrections.append(f"Clamped hyper-arousal in '{chem}' to 1.0")

        if esteem and hasattr(esteem, "current_t_score"):
            if esteem.current_t_score is None or math.isnan(esteem.current_t_score):
                esteem.current_t_score = 50.0
                corrections.append("Clamped NaN/None in esteem T-Score to 50.0")
            elif esteem.current_t_score < 20.0:
                esteem.current_t_score = 20.0
                corrections.append("Clamped esteem T-Score below floor (20.0)")
            elif esteem.current_t_score > 80.0:
                esteem.current_t_score = 80.0
                corrections.append("Clamped esteem T-Score above ceiling (80.0)")

        if affinity and hasattr(affinity, "themes"):
            for theme, data in list(affinity.themes.items()):
                intensity = data.get("intensity", 0.0)
                if intensity is None or math.isnan(intensity):
                    data["intensity"] = 0.20
                    corrections.append(f"Fixed NaN in affinity '{theme}'")
                elif intensity < 0.0:
                    data["intensity"] = 0.0
                    corrections.append(f"Clamped negative affinity '{theme}'")
                elif intensity > 1.0:
                    data["intensity"] = 1.0

        if corrections:
            for c in corrections:
                self.logger.warning(f"[Limbic Audit]: {c}")

        return corrections



    def get_ram_stats(self) -> Dict[str, Any]:
        """Returns system RAM metrics via psutil or fallback zero-metrics."""
        if HAS_PSUTIL:
            try:
                v = psutil.virtual_memory()
                return {
                    "total_mb": round(v.total / (1024 * 1024), 1),
                    "used_mb": round(v.used / (1024 * 1024), 1),
                    "percent": v.percent
                }
            except Exception:
                pass
        return {"total_mb": 0, "used_mb": 0, "percent": 0.0}

    def create_blackbox_dump(self, neuro=None, esteem=None, affinity=None, scenario_engine=None, history=None) -> Path:
        """Creates a Markdown diagnostic report for troubleshooting and bug tickets."""
        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        dump_path = self.dump_dir / f"calypso_dump_{timestamp_str}.md"

        vram = self.get_vram_stats()
        ram = self.get_ram_stats()

        lines = [
            f"# Calypso Emotion Core — Diagnostic Blackbox Report",
            f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"**Uptime:** {int(time.time() - self.start_time)} seconds",
            "",
            "## 1. Environment & Hardware",
            f"- **OS / Platform:** {platform.platform()}",
            f"- **Python Version:** {platform.python_version()}",
            f"- **PyTorch Version:** {torch.__version__}",
            f"- **CUDA Available:** {torch.cuda.is_available()}",
            f"- **GPU Count:** {vram.get('device_count', 0)}",
        ]

        if vram.get("active") and vram.get("devices"):
            for dev in vram["devices"]:
                if "error" in dev:
                    lines.append(f"- **GPU {dev['index']}:** Error ({dev['error']})")
                else:
                    lines.append(
                        f"- **GPU {dev['index']} ({dev['name']}):** {dev['percent']}% used "
                        f"({dev['used_mb']} MB / {dev['total_mb']} MB) • PyTorch Allocated: {dev['allocated_mb']} MB"
                    )
        else:
            lines.append("- **GPU:** No CUDA devices active.")

        lines.extend([
            f"- **System RAM:** {ram.get('percent', 0.0)}% used ({ram.get('used_mb', 0)} MB / {ram.get('total_mb', 0)} MB)",
            "",
            "## 2. Active Model & Config Snapshot",
            f"- **Ollama URL:** `{config.OLLAMA_URL}`",
            f"- **Active LLM:** `{config.MODEL_NAME}`",
            f"- **Vision Model:** `{config.VISION_MODEL}`",
            f"- **Stable Diffusion URL:** `{config.SD_URL}`",
            f"- **Active SD Checkpoint:** `{config.SD_MODEL}`",
            "",
            "## 3. Emotional Subsystem State",
        ])

        if esteem and hasattr(esteem, "current_t_score"):
            lines.append(f"- **Esteem T-Score:** {esteem.current_t_score:.2f}")
        if scenario_engine and hasattr(scenario_engine, "active_scenario"):
            active_sc = scenario_engine.active_scenario
            lines.append(f"- **Active Scenario:** {active_sc.get('title', 'None') if active_sc else 'None (Baseline)'}")

        if neuro and hasattr(neuro, "chemicals"):
            lines.append("\n### Neurochemistry Matrix:")
            with neuro.lock:
                for chem, val in neuro.chemicals.items():
                    lines.append(f"  - `{chem:<14}`: {val:.3f}")

        if affinity and hasattr(affinity, "themes"):
            lines.append("\n### Top Affinity Themes:")
            sorted_aff = sorted(affinity.themes.items(), key=lambda x: x[1].get("intensity", 0), reverse=True)
            for th, data in sorted_aff[:6]:
                lines.append(f"  - `{th:<12}`: {data.get('intensity', 0):.2f}")

        lines.append("\n## 4. Unhandled Thread Crashes")
        if self.thread_crashes:
            for crash in self.thread_crashes:
                lines.append(f"### Crash in `{crash['thread']}` at {crash['timestamp']}")
                lines.append(f"**Reason:** `{crash['reason']}`")
                lines.append("```text")
                lines.append(crash["stack"].strip())
                lines.append("```")
        else:
            lines.append("*(No background thread crashes recorded)*")

        lines.append("\n## 5. Recent Dialogue Exchange (Last 3 Turns)")
        if history:
            for msg in history[-3:]:
                lines.append(f"**[{msg.get('role', 'unknown').upper()}]:**")
                lines.append(f"> {msg.get('content', '').replace(chr(10), ' ')}")
                lines.append("")

        lines.append("## 6. Recent Internal Log Ring Buffer (Last 25 Events)")
        lines.append("```text")
        for log_entry in list(self.log_handler.buffer)[-25:]:
            lines.append(f"[{log_entry['time']}] [{log_entry['level']}] {log_entry['logger']}: {log_entry['msg']}")
        lines.append("```")

        with open(dump_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        self.logger.info(f"[DiagnosticEngine] Exported crash dump to {dump_path}")
        return dump_path


# =========================================================================
# INTERACTIVE DEV & DIAGNOSTIC HUD (CTkToplevel)
# =========================================================================
class DiagnosticHUD:
    def __init__(self, parent_root, diagnostic_engine: DiagnosticEngine, neuro=None, esteem=None, affinity=None):
        self.root = parent_root
        self.diag = diagnostic_engine
        self.neuro = neuro
        self.esteem = esteem
        self.affinity = affinity
        self._is_active = True

        # Pre-initialize widget references to prevent attribute errors during poll
        self.lbl_gpu_name = None
        self.lbl_vram = None
        self.bar_vram = None
        self.lbl_ram = None
        self.bar_ram = None
        self.txt_raw_llm = None
        self.txt_logs = None
        self.chem_sliders = {}

        self.win = ctk.CTkToplevel(parent_root)
        self.win.title("Calypso Limbic & System Diagnostics Console")
        self.win.geometry("980x780")
        self.win.minsize(860, 640)
        self.win.configure(fg_color="#080a10")

        # Top Bar
        hdr = ctk.CTkFrame(self.win, fg_color="#10141f", corner_radius=0, height=48)
        hdr.pack(fill="x", padx=0, pady=0)
        hdr.pack_propagate(False)

        ctk.CTkLabel(
            hdr, text="🐞 CALYPSO RUNTIME TELEMETRY & DIAGNOSTICS",
            font=ctk.CTkFont(family="Consolas", size=13, weight="bold"),
            text_color="#38bdf8"
        ).pack(side="left", padx=16)

        ctk.CTkButton(
            hdr, text="📋 Export Blackbox Dump", width=170, height=28,
            fg_color="#2563eb", hover_color="#1d4ed8", font=ctk.CTkFont(size=11, weight="bold"),
            command=self._do_dump
        ).pack(side="right", padx=14)

        # Tabs
        self.tabs = ctk.CTkTabview(
            self.win, fg_color="#0e121d",
            segmented_button_fg_color="#182030",
            segmented_button_selected_color="#2563eb"
        )
        self.tabs.pack(fill="both", expand=True, padx=12, pady=10)

        self.tab_sys = self.tabs.add("⚡ Hardware & VRAM")
        self.tab_limbic = self.tabs.add("🧪 Limbic Overrides")
        self.tab_raw = self.tabs.add("👁️ LLM Raw Stream Tap")
        self.tab_logs = self.tabs.add("📜 Event Logs")

        # Build each tab
        self._build_hardware_tab()
        self._build_limbic_tab()
        self._build_raw_stream_tab()
        self._build_logs_tab()

        self.win.protocol("WM_DELETE_WINDOW", self._on_close)
        self._poll_telemetry()

    def _on_close(self):
        self._is_active = False
        try:
            self.win.destroy()
        except Exception:
            pass

    def _do_dump(self):
        dump_file = self.diag.create_blackbox_dump(self.neuro, self.esteem, self.affinity)
        if not hasattr(self, "_dump_lbl") or not self._dump_lbl.winfo_exists():
            self._dump_lbl = ctk.CTkLabel(
                self.tab_sys,
                text="",
                font=ctk.CTkFont(size=11), text_color="#34d399"
            )
            self._dump_lbl.pack(pady=4)
        self._dump_lbl.configure(text=f"✓ Dump exported: {dump_file.name}")

# ---------------------------------------------------------------------
    # TAB 1: HARDWARE & VRAM
    # ---------------------------------------------------------------------
    def _build_hardware_tab(self):
        t = self.tab_sys

        # Scrollable container for hardware telemetry
        self.gpu_cards_container = ctk.CTkFrame(t, fg_color="transparent")
        self.gpu_cards_container.pack(fill="x", padx=16, pady=(10, 4))

        self.gpu_ui_elements = {}

        # RAM Gauge Section
        ram_frame = ctk.CTkFrame(t, fg_color="#121724", corner_radius=8, border_width=1, border_color="#1e2538")
        ram_frame.pack(fill="x", padx=16, pady=(8, 12))

        self.lbl_ram = ctk.CTkLabel(ram_frame, text="System RAM: Scanning...", font=ctk.CTkFont(family="Consolas", size=11), text_color="#94a3b8")
        self.lbl_ram.pack(anchor="w", padx=12, pady=(10, 2))

        self.bar_ram = ctk.CTkProgressBar(ram_frame, height=12, corner_radius=6, progress_color="#38bdf8", fg_color="#1a2030")
        self.bar_ram.pack(fill="x", padx=12, pady=(0, 12))
        self.bar_ram.set(0.0)

        # Boot probe trigger
        probe_box = ctk.CTkFrame(t, fg_color="#121724", corner_radius=8, border_width=1, border_color="#1e2538")
        probe_box.pack(fill="x", padx=16, pady=4)

        ctk.CTkLabel(
            probe_box, text="🛠️ Subsystem Verification Handshake",
            font=ctk.CTkFont(size=12, weight="bold"), text_color="#f8fafc"
        ).pack(anchor="w", padx=12, pady=(10, 4))

        self.txt_probe = ctk.CTkTextbox(probe_box, height=140, font=ctk.CTkFont(family="Consolas", size=10), fg_color="#080a10")
        self.txt_probe.pack(fill="both", expand=True, padx=12, pady=(0, 10))

        def _run_probe():
            res = self.diag.run_boot_diagnostics(config.OLLAMA_URL, config.MODEL_NAME)
            self.txt_probe.delete("1.0", "end")
            self.txt_probe.insert("end", json.dumps(res, indent=2))

        ctk.CTkButton(probe_box, text="Run Subsystem Probe", width=160, height=26, command=_run_probe).pack(anchor="e", padx=12, pady=(0, 10))

    def _render_gpu_card(self, dev_info: Dict[str, Any]):
        idx = dev_info["index"]
        card = ctk.CTkFrame(self.gpu_cards_container, fg_color="#121724", corner_radius=8, border_width=1, border_color="#1e2538")
        card.pack(fill="x", pady=4)

        lbl_name = ctk.CTkLabel(
            card,
            text=f"GPU {idx}: {dev_info.get('name', 'NVIDIA GPU')} (Compute {dev_info.get('compute_capability', 'N/A')})",
            font=ctk.CTkFont(family="Consolas", size=12, weight="bold"),
            text_color="#38bdf8"
        )
        lbl_name.pack(anchor="w", padx=12, pady=(8, 2))

        lbl_stats = ctk.CTkLabel(
            card,
            text="VRAM: Initializing...",
            font=ctk.CTkFont(family="Consolas", size=10),
            text_color="#94a3b8"
        )
        lbl_stats.pack(anchor="w", padx=12, pady=(0, 2))

        bar = ctk.CTkProgressBar(card, height=12, corner_radius=6, progress_color="#10b981", fg_color="#1a2030")
        bar.pack(fill="x", padx=12, pady=(0, 10))
        bar.set(0.0)

        self.gpu_ui_elements[idx] = {
            "card": card,
            "lbl_name": lbl_name,
            "lbl_stats": lbl_stats,
            "bar": bar
        }

    # ---------------------------------------------------------------------
    # REALTIME TELEMETRY LOOP
    # ---------------------------------------------------------------------
    def _poll_telemetry(self):
        if not self._is_active:
            return

        # 1. Update GPUs
        vram_data = self.diag.get_vram_stats()
        if vram_data.get("active") and vram_data.get("devices"):
            for dev in vram_data["devices"]:
                idx = dev["index"]
                if idx not in self.gpu_ui_elements:
                    self._render_gpu_card(dev)

                ui = self.gpu_ui_elements[idx]
                pct = dev.get("percent", 0.0)

                # Adaptive color: Green (<70%), Orange (70-85%), Red (>85%)
                bar_color = "#10b981" if pct < 70 else ("#f59e0b" if pct < 85 else "#ef4444")
                ui["bar"].configure(progress_color=bar_color)
                ui["bar"].set(min(1.0, max(0.0, pct / 100.0)))

                ui["lbl_stats"].configure(
                    text=f"VRAM: {dev.get('used_mb', 0):,.0f} MB / {dev.get('total_mb', 0):,.0f} MB ({pct:.1f}%) • "
                         f"PyTorch Allocated: {dev.get('allocated_mb', 0):,.0f} MB • Free: {dev.get('free_mb', 0):,.0f} MB"
                )

        # 2. Update System RAM
        ram = self.diag.get_ram_stats()
        self.lbl_ram.configure(text=f"System RAM: {ram.get('used_mb', 0):,.0f} MB / {ram.get('total_mb', 0):,.0f} MB ({ram.get('percent', 0)}%)")
        self.bar_ram.set(ram.get("percent", 0.0) / 100.0)

        # 3. Update Raw LLM View if new exchange arrived
        if self.diag.recent_llm_exchanges:
            last_ex = self.diag.recent_llm_exchanges[-1]
            content = f"--- Exchange at {last_ex['timestamp']} ---\n[User Snippet]: {last_ex['user_prompt']}\n\n[RAW TOKENS DIRECT FROM OLLAMA]:\n{last_ex['raw_output']}\n\n[AFTER REGEX STRIP]:\n{last_ex['cleaned_output']}"
            if self.txt_raw_llm.get("1.0", "end-1c") != content:
                self.txt_raw_llm.delete("1.0", "end")
                self.txt_raw_llm.insert("1.0", content)

        # 4. Update Logs
        log_records = list(self.diag.log_handler.buffer)[-40:]
        fmt_logs = "\n".join([f"[{r['time']}] [{r['level']}] {r['logger']}: {r['msg']}" for r in log_records])
        self.txt_logs.delete("1.0", "end")
        self.txt_logs.insert("1.0", fmt_logs)
        self.txt_logs.see("end")

        self.root.after(1000, self._poll_telemetry)

    # ---------------------------------------------------------------------
    # TAB 2: LIMBIC OVERRIDES & UNIT INJECTOR
    # ---------------------------------------------------------------------
    def _build_limbic_tab(self):
        t = self.tab_limbic

        ctk.CTkLabel(
            t, text="Synthetic Neurochemical Injection (Testing Only)",
            font=ctk.CTkFont(size=12, weight="bold"), text_color="#f8fafc"
        ).pack(anchor="w", padx=16, pady=(12, 6))

        slider_grid = ctk.CTkFrame(t, fg_color="transparent")
        slider_grid.pack(fill="x", padx=16, pady=4)
        slider_grid.columnconfigure(1, weight=1)

        self.chem_sliders = {}
        if self.neuro and hasattr(self.neuro, "chemicals") and hasattr(self.neuro, "lock"):
            row = 0
            for chem in ["dopamine", "serotonin", "oxytocin", "cortisol", "adrenaline", "acetylcholine"]:
                lbl = ctk.CTkLabel(slider_grid, text=f"{chem.title():<14}:", font=ctk.CTkFont(family="Consolas", size=10))
                lbl.grid(row=row, column=0, sticky="w", pady=3)

                val_init = self.neuro.chemicals.get(chem, 0.5)
                val_lbl = ctk.CTkLabel(slider_grid, text=f"{val_init:.2f}", font=ctk.CTkFont(family="Consolas", size=10), width=36)
                val_lbl.grid(row=row, column=2, sticky="e", padx=6)

                def _slider_cb(v, c=chem, vl=val_lbl):
                    vl.configure(text=f"{float(v):.2f}")
                    if self.neuro and hasattr(self.neuro, "lock"):
                        with self.neuro.lock:
                            self.neuro.chemicals[c] = float(v)
                            if hasattr(self.neuro, "calculate_valence"):
                                self.neuro.calculate_valence()

                sl = ctk.CTkSlider(slider_grid, from_=0.0, to=1.0, command=_slider_cb)
                sl.set(val_init)
                sl.grid(row=row, column=1, sticky="ew", padx=8, pady=3)
                self.chem_sliders[chem] = (sl, val_lbl)
                row += 1
        else:
            ctk.CTkLabel(
                slider_grid,
                text="⚠️ Limbic/Neurochemistry engine not connected.\n(Open via chat with '/debug' to bind active engine).",
                font=ctk.CTkFont(size=11), text_color="#94a3b8", justify="left"
            ).grid(row=0, column=0, columnspan=3, pady=10)

        btn_row = ctk.CTkFrame(t, fg_color="transparent")
        btn_row.pack(fill="x", padx=16, pady=16)

        def _force_audit():
            if not self.neuro:
                ctk.CTkLabel(t, text="⚠️ Neurochemistry engine not connected.", font=ctk.CTkFont(size=10), text_color="#f87171").pack(pady=2)
                return
            fixes = self.diag.audit_limbic_state(self.neuro, self.esteem, self.affinity)
            msg = f"✓ Invariant audit completed. {len(fixes)} corrections made." if fixes else "✓ All limbic invariants verified healthy."
            ctk.CTkLabel(t, text=msg, font=ctk.CTkFont(size=10), text_color="#34d399").pack(pady=2)

        ctk.CTkButton(
            btn_row, text="Run Limbic Sanity Audit", width=180, height=28,
            fg_color="#059669", hover_color="#047857", command=_force_audit
        ).pack(side="left")

    # ---------------------------------------------------------------------
    # TAB 3: RAW LLM STREAM TAP
    # ---------------------------------------------------------------------
    def _build_raw_stream_tab(self):
        t = self.tab_raw

        ctk.CTkLabel(
            t, text="Unfiltered Ollama Output (Inspect Raw vs Extracted Action Tags)",
            font=ctk.CTkFont(size=12, weight="bold"), text_color="#f8fafc"
        ).pack(anchor="w", padx=16, pady=(12, 6))

        self.txt_raw_llm = ctk.CTkTextbox(
            t, fg_color="#080a10", text_color="#cbd5e1",
            font=ctk.CTkFont(family="Consolas", size=10), wrap="word"
        )
        self.txt_raw_llm.pack(fill="both", expand=True, padx=16, pady=(0, 12))

    # ---------------------------------------------------------------------
    # TAB 4: LIVE EVENT LOG FEED
    # ---------------------------------------------------------------------
    def _build_logs_tab(self):
        t = self.tab_logs

        self.txt_logs = ctk.CTkTextbox(
            t, fg_color="#080a10", text_color="#94a3b8",
            font=ctk.CTkFont(family="Consolas", size=10), wrap="none"
        )
        self.txt_logs.pack(fill="both", expand=True, padx=16, pady=12)

        # 3. Update Logs
        if self.txt_logs and self.txt_logs.winfo_exists() and hasattr(self.diag, "log_handler"):
            log_records = list(self.diag.log_handler.buffer)[-40:]
            fmt_logs = "\n".join([f"[{r['time']}] [{r['level']}] {r['logger']}: {r['msg']}" for r in log_records])
            self.txt_logs.delete("1.0", "end")
            self.txt_logs.insert("1.0", fmt_logs)
            self.txt_logs.see("end")

        if self._is_active:
            self.root.after(1000, self._poll_telemetry)
