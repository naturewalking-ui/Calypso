# modules/hardware_sentinel.py

import json
import logging
import os
import urllib.request
from pathlib import Path
from typing import Dict, Any, List, Optional

try:
    import torch
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False

logger = logging.getLogger("EmotionEngine.HardwareSentinel")


class HardwareSentinel:
    """
    Intelligent hardware sentry and diagnostic engine that detects GPU capacity,
    available VRAM, system RAM, and local model availability to determine the
    optimal "Sweet Spot" for:
      1. Gemma 4 Series Language Models (the only officially supported LLM family)
      2. Cognitive Context & Thinking Horizon Profiles
      3. SDXL (Stable Diffusion XL) Image Generation Profiles
      4. MusicGen / AudioCraft Eligibility (Off by default unless >= 16 GB VRAM)
    """

    MUSICGEN_MIN_VRAM_GB: float = 16.0

    # Supported Gemma 4 Series Catalog (Only Gemma 4 series is supported)
    GEMMA4_CATALOG: List[Dict[str, Any]] = [
        {
            "tag": "gemma4:e2b",
            "match_keys": ["e2b", ":2b"],
            "name": "Gemma 4 E2B (Ultra-Light Edge)",
            "min_vram_gb": 0.0,
            "ideal_vram_range": "CPU / 4–6 GB VRAM",
            "weights_gb": 1.8,
            "kv_gb_per_32k": 1.2,
            "plain_description": (
                "Ultra-lightweight Gemma 4 brain built for laptops, integrated graphics, "
                "or entry-level GPUs (4–6 GB VRAM). Very fast and gentle on memory."
            ),
        },
        {
            "tag": "gemma4:e4b",
            "match_keys": ["e4b", ":4b"],
            "name": "Gemma 4 E4B (Agile Edge)",
            "min_vram_gb": 6.0,
            "ideal_vram_range": "6–10 GB VRAM",
            "weights_gb": 3.2,
            "kv_gb_per_32k": 2.0,
            "plain_description": (
                "Nimble Gemma 4 brain ideal for 8 GB gaming graphics cards. "
                "Delivers quick replies and multimodal vision without bogging down your PC."
            ),
        },
        {
            "tag": "gemma4:12b",
            "match_keys": ["12b"],
            "name": "Gemma 4 12B (Balanced Workstation)",
            "min_vram_gb": 11.0,
            "ideal_vram_range": "12–16 GB VRAM",
            "weights_gb": 8.0,
            "kv_gb_per_32k": 5.0,
            "plain_description": (
                "Mid-sized dense Gemma 4 brain for 12–16 GB graphics cards. "
                "Offers rich emotional nuance, strong memory recall, and thoughtful conversation."
            ),
        },
        {
            "tag": "gemma4:26b",
            "match_keys": ["26b", "27b"],
            "name": "Gemma 4 26B MoE (High-Speed Expert)",
            "min_vram_gb": 18.0,
            "ideal_vram_range": "20–24 GB VRAM",
            "weights_gb": 16.5,
            "kv_gb_per_32k": 10.0,
            "plain_description": (
                "Mixture-of-Experts (MoE) Gemma 4 brain with 26B total knowledge but only 4B active "
                "parameters per word—giving near-flagship intelligence at fast speeds on 20–24 GB GPUs."
            ),
        },
        {
            "tag": "gemma4:31b",
            "match_keys": ["31b", "32b"],
            "name": "Gemma 4 31B (Flagship Contemplative)",
            "min_vram_gb": 24.0,
            "ideal_vram_range": "24–32+ GB VRAM",
            "weights_gb": 19.5,
            "kv_gb_per_32k": 12.0,
            "plain_description": (
                "The largest, deepest-thinking dense Gemma 4 brain for enthusiast 24 GB–32 GB+ "
                "workstations and dual-GPU setups."
            ),
        },
    ]

    PROFILES: Dict[str, Dict[str, Any]] = {
        "grounded": {
            "id": "grounded",
            "name": "Grounded & Agile",
            "description": "Snappy, lightweight memory footprint for 8–12 GB GPUs or laptops.",
            "plain_english": "Keeps short-term memory compact (8,192 tokens) so replies stay fast and never overload your graphics card.",
            "num_ctx": 8192,
            "num_predict": 2048,
            "min_vram_gb": 8.0,
            "badge": "8 GB - 12 GB",
        },
        "balanced": {
            "id": "balanced",
            "name": "Balanced Companion",
            "description": "Rich emotional depth and thought for 16–24 GB single GPUs.",
            "plain_english": "Balances a generous conversation memory (16,384 tokens) with smooth performance on 16–24 GB graphics cards.",
            "num_ctx": 16384,
            "num_predict": 4096,
            "min_vram_gb": 14.0,
            "badge": "16 GB - 24 GB",
        },
        "deep_contemplative": {
            "id": "deep_contemplative",
            "name": "Deep Contemplative (Unconstrained)",
            "description": "Full uninhibited thinking and expansive context for 32 GB+ multi-GPU rigs.",
            "plain_english": "Unlocks maximum short-term memory (32,768 tokens) and deep internal reflection for 32 GB+ systems.",
            "num_ctx": 32768,
            "num_predict": 8192,
            "min_vram_gb": 28.0,
            "badge": "32 GB+ (Dual GPU / Workstation)",
        },
        "custom": {
            "id": "custom",
            "name": "Custom Horizon",
            "description": "Manually configured context and prediction limits.",
            "plain_english": "Custom memory and thinking limits set manually in Preferences.",
            "num_ctx": 32768,
            "num_predict": 8192,
            "min_vram_gb": 0.0,
            "badge": "Manual",
        }
    }

    SDXL_PROFILES: Dict[str, Dict[str, Any]] = {
        "sdxl_base": {
            "id": "sdxl_base",
            "name": "SDXL Standard (High Detail — 1024×1024)",
            "badge": "12 GB+ VRAM Recommended",
            "sd_steps": 25,
            "sd_guidance_scale": 6.0,
            "sd_resolution": "1024 x 1024 (1:1 Square)",
            "sd_enable_face_swap": True,
            "sd_restore_face": True,
            "autonomous_art_enabled": True,
            "plain_english": (
                "Full 1024×1024 high-resolution paintings with 25 detail steps, "
                "automatic face matching (InSwapper), and facial restoration (GFPGAN)."
            ),
        },
        "sdxl_turbo": {
            "id": "sdxl_turbo",
            "name": "SDXL Lightning / Fast (Low-Memory — 1024×1024, 6 Steps)",
            "badge": "8–12 GB VRAM Sweet Spot",
            "sd_steps": 6,
            "sd_guidance_scale": 2.0,
            "sd_resolution": "1024 x 1024 (1:1 Square)",
            "sd_enable_face_swap": True,
            "sd_restore_face": True,
            "autonomous_art_enabled": True,
            "plain_english": (
                "Uses a fast 6-step rendering cycle so Calypso can paint 1024×1024 scenes "
                "quickly without tying up mid-range 8–12 GB graphics cards."
            ),
        },
        "sd15": {
            "id": "sd15",
            "name": "Compact Safe Mode (512×512 — Minimal VRAM)",
            "badge": "Under 8 GB VRAM / Laptop Safe",
            "sd_steps": 20,
            "sd_guidance_scale": 6.5,
            "sd_resolution": "512 x 512 (SD 1.5 Classic)",
            "sd_enable_face_swap": False,
            "sd_restore_face": False,
            "autonomous_art_enabled": False,
            "plain_english": (
                "Lowers canvas size to 512×512 and pauses unprompted background painting "
                "so systems with limited video memory stay responsive."
            ),
        },
    }

    @classmethod
    def is_gemma4_model(cls, model_name: str) -> bool:
        """Returns True if the model name belongs to the supported Gemma 4 series."""
        if not model_name:
            return False
        norm = model_name.strip().lower()
        return "gemma4" in norm or "gemma-4" in norm

    @classmethod
    def filter_supported_gemma4_models(cls, model_list: List[str]) -> List[str]:
        """Filters an Ollama model list strictly to Gemma 4 series models."""
        if not model_list:
            return []
        return [m for m in model_list if cls.is_gemma4_model(m)]

    @classmethod
    def get_system_ram_info(cls) -> Dict[str, Any]:
        """Detects total and available system RAM and CPU core count."""
        cpu_cores = os.cpu_count() or 4
        total_ram_gb = 0.0
        avail_ram_gb = 0.0

        if PSUTIL_AVAILABLE:
            try:
                vm = psutil.virtual_memory()
                total_ram_gb = round(vm.total / (1024 ** 3), 1)
                avail_ram_gb = round(vm.available / (1024 ** 3), 1)
            except Exception:
                pass

        if total_ram_gb <= 0.0 and os.path.exists("/proc/meminfo"):
            try:
                with open("/proc/meminfo", "r", encoding="utf-8") as f:
                    for line in f:
                        if line.startswith("MemTotal:"):
                            kb = int(line.split()[1])
                            total_ram_gb = round(kb / (1024 ** 2), 1)
                        elif line.startswith("MemAvailable:"):
                            kb = int(line.split()[1])
                            avail_ram_gb = round(kb / (1024 ** 2), 1)
            except Exception:
                pass

        summary = f"{total_ram_gb} GB System RAM • {cpu_cores} CPU Threads" if total_ram_gb > 0 else f"{cpu_cores} CPU Threads"
        return {
            "total_ram_gb": total_ram_gb,
            "available_ram_gb": avail_ram_gb,
            "cpu_cores": cpu_cores,
            "summary": summary,
        }

    @classmethod
    def get_gpu_info(cls) -> Dict[str, Any]:
        """Detects all available GPUs, VRAM capacities, and system headroom (with nvidia-smi fallback)."""
        devices: List[Dict[str, Any]] = []
        total_vram_bytes = 0
        free_vram_bytes = 0
        max_single_gb = 0.0

        if TORCH_AVAILABLE and torch.cuda.is_available():
            for i in range(torch.cuda.device_count()):
                try:
                    free_b, total_b = torch.cuda.mem_get_info(i)
                    name = torch.cuda.get_device_name(i)
                    total_vram_bytes += total_b
                    free_vram_bytes += free_b
                    dev_total_gb = round(total_b / (1024 ** 3), 2)
                    if dev_total_gb > max_single_gb:
                        max_single_gb = dev_total_gb
                    devices.append({
                        "index": i,
                        "name": name,
                        "total_gb": dev_total_gb,
                        "free_gb": round(free_b / (1024 ** 3), 2)
                    })
                except Exception as e:
                    logger.warning(f"[HardwareSentinel] Failed to query GPU {i}: {e}")

        # Fallback to nvidia-smi if torch.cuda did not report devices
        if not devices:
            try:
                import subprocess
                res = subprocess.run(
                    ["nvidia-smi", "--query-gpu=index,name,memory.total,memory.free", "--format=csv,noheader,nounits"],
                    capture_output=True, text=True, timeout=3
                )
                if res.returncode == 0 and res.stdout.strip():
                    for line in res.stdout.strip().splitlines():
                        parts = [p.strip() for p in line.split(",")]
                        if len(parts) >= 4:
                            idx = int(parts[0])
                            name = parts[1]
                            tot_mb = float(parts[2])
                            free_mb = float(parts[3])
                            tot_b = int(tot_mb * 1024 * 1024)
                            fr_b = int(free_mb * 1024 * 1024)
                            total_vram_bytes += tot_b
                            free_vram_bytes += fr_b
                            dev_total_gb = round(tot_mb / 1024.0, 2)
                            if dev_total_gb > max_single_gb:
                                max_single_gb = dev_total_gb
                            devices.append({
                                "index": idx,
                                "name": name,
                                "total_gb": dev_total_gb,
                                "free_gb": round(free_mb / 1024.0, 2)
                            })
            except Exception:
                pass

        if not devices:
            return {
                "cuda_available": False,
                "device_count": 0,
                "total_vram_gb": 0.0,
                "free_vram_gb": 0.0,
                "max_single_gpu_gb": 0.0,
                "devices": [],
                "summary": "CPU Mode (No NVIDIA CUDA GPU detected)"
            }

        total_gb = round(total_vram_bytes / (1024 ** 3), 2)
        free_gb = round(free_vram_bytes / (1024 ** 3), 2)
        device_count = len(devices)

        if device_count > 1:
            dev_name = devices[0]["name"] if devices else "GPU"
            summary = f"{device_count}x {dev_name} ({total_gb} GB Total VRAM)"
        elif device_count == 1:
            summary = f"{devices[0]['name']} ({total_gb} GB VRAM)"
        else:
            summary = "CUDA Active (No devices returned)"

        return {
            "cuda_available": True,
            "device_count": device_count,
            "total_vram_gb": total_gb,
            "free_vram_gb": free_gb,
            "max_single_gpu_gb": max_single_gb,
            "devices": devices,
            "summary": summary
        }

    @classmethod
    def recommend_profile(cls) -> str:
        """Determines the best Cognitive Profile ID based on detected VRAM."""
        info = cls.get_gpu_info()
        total_vram = info.get("total_vram_gb", 0.0)

        if total_vram >= 28.0:
            return "deep_contemplative"
        elif total_vram >= 14.0:
            return "balanced"
        else:
            return "grounded"

    @classmethod
    def recommend_gemma4_model(cls, installed_models: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Determines the sweet-spot Gemma 4 model for the user's detected VRAM.
        If matching Gemma 4 models are already installed in Ollama, prefers the best
        installed tag that fits smoothly in VRAM.
        """
        gpu_info = cls.get_gpu_info()
        vram = gpu_info.get("total_vram_gb", 0.0)
        installed_gemma4 = cls.filter_supported_gemma4_models(installed_models or [])

        # Determine target tier by VRAM
        if vram >= 26.0:
            target_entry = cls.GEMMA4_CATALOG[3]  # gemma4:26b MoE (or 31b) is the sweet spot for 26GB+ alongside TTS/SDXL
            if vram >= 30.0:
                # Check if user has a 26b or 31b installed
                for m in installed_gemma4:
                    if any(k in m.lower() for k in ("26b", "27b", "31b", "32b")):
                        return {
                            "recommended_model": m,
                            "catalog_entry": cls.GEMMA4_CATALOG[4] if "31b" in m.lower() else cls.GEMMA4_CATALOG[3],
                            "is_installed": True,
                            "reason": (
                                f"Your system has {vram} GB of VRAM, which easily supports high-capacity Gemma 4 models "
                                f"with deep reasoning and a large 32K memory window."
                            ),
                        }
                target_entry = cls.GEMMA4_CATALOG[3]  # gemma4:26b MoE is ultra-fast & leaves headroom for SDXL/MusicGen
        elif vram >= 18.0:
            target_entry = cls.GEMMA4_CATALOG[3]  # gemma4:26b
        elif vram >= 11.0:
            target_entry = cls.GEMMA4_CATALOG[2]  # gemma4:12b
        elif vram >= 6.0:
            target_entry = cls.GEMMA4_CATALOG[1]  # gemma4:e4b
        else:
            target_entry = cls.GEMMA4_CATALOG[0]  # gemma4:e2b

        # Check if an installed Gemma 4 model matches the target tier
        for m in installed_gemma4:
            m_low = m.lower()
            if any(k in m_low for k in target_entry["match_keys"]):
                return {
                    "recommended_model": m,
                    "catalog_entry": target_entry,
                    "is_installed": True,
                    "reason": (
                        f"Selected installed model '{m}' — {target_entry['plain_description']}"
                    ),
                }

        # Otherwise, check if ANY installed Gemma 4 model fits within VRAM
        for entry in reversed(cls.GEMMA4_CATALOG):
            if vram >= entry["min_vram_gb"] or entry["min_vram_gb"] == 0.0:
                for m in installed_gemma4:
                    if any(k in m.lower() for k in entry["match_keys"]):
                        return {
                            "recommended_model": m,
                            "catalog_entry": entry,
                            "is_installed": True,
                            "reason": (
                                f"Found installed Gemma 4 model '{m}', which fits safely within your {vram} GB VRAM."
                            ),
                        }

        # Fallback: recommend the ideal catalog tag for their hardware
        if vram <= 0.0:
            reason = (
                "No dedicated NVIDIA CUDA graphics card was detected. We recommend 'gemma4:e2b', "
                "which is compact enough to run on standard system memory (CPU)."
            )
        else:
            reason = (
                f"Based on your {vram} GB of video memory, '{target_entry['tag']}' ({target_entry['name']}) "
                f"is your hardware's sweet spot—giving the best intelligence without slowing down your PC."
            )

        return {
            "recommended_model": target_entry["tag"],
            "catalog_entry": target_entry,
            "is_installed": False,
            "reason": reason,
        }

    @classmethod
    def recommend_sdxl_profile(cls) -> Dict[str, Any]:
        """Determines the sweet-spot SDXL image generation profile based on VRAM."""
        gpu_info = cls.get_gpu_info()
        vram = gpu_info.get("total_vram_gb", 0.0)

        if vram >= 12.0:
            prof = cls.SDXL_PROFILES["sdxl_base"]
            reason = (
                f"With {vram} GB VRAM, your graphics card can comfortably render full 1024×1024 SDXL artwork "
                f"with facial identity matching and restoration enabled."
            )
        elif vram >= 7.5:
            prof = cls.SDXL_PROFILES["sdxl_turbo"]
            reason = (
                f"With {vram} GB VRAM, our 'SDXL Lightning / Fast' sweet spot (6 steps) lets Calypso paint "
                f"1024×1024 scenes rapidly without exhausting your video memory."
            )
        else:
            prof = cls.SDXL_PROFILES["sd15"]
            reason = (
                f"Because your system has {vram} GB VRAM (under 8 GB), we selected 'Compact Safe Mode' (512×512) "
                f"and paused automatic background painting so conversations stay smooth."
            )

        return {
            "profile_id": prof["id"],
            "profile": prof,
            "reason": reason,
        }

    @classmethod
    def evaluate_musicgen_eligibility(cls) -> Dict[str, Any]:
        """
        Evaluates whether the user's system meets the >= 16 GB VRAM requirement for MusicGen.
        (Uses 15.5 GB usable threshold to account for ~15.8-15.93 GB reported on nominal 16 GB GPUs).
        Unless the user has at least 16 GB of VRAM, MusicGen MUST be off by default.
        """
        gpu_info = cls.get_gpu_info()
        vram = gpu_info.get("total_vram_gb", 0.0)
        eligible = vram >= 15.5

        if eligible:
            reason = (
                f"✓ Your system has {vram} GB VRAM (meets the 16 GB minimum for MusicGen). "
                f"MusicGen is enabled for your hardware tier (or can be toggled below)."
            )
        else:
            reason = (
                f"🔒 MusicGen is automatically set to OFF by default because your system has {vram} GB VRAM "
                f"(16 GB+ VRAM is required to run MusicGen float32 audio synthesis alongside Gemma 4 without memory overflow)."
            )

        return {
            "eligible_16gb": eligible,
            "default_enabled": eligible,
            "total_vram_gb": vram,
            "min_vram_gb": cls.MUSICGEN_MIN_VRAM_GB,
            "reason": reason,
        }

    @classmethod
    def run_sweet_spot_diagnostics(cls, ollama_url: str = "http://localhost:11434") -> Dict[str, Any]:
        """
        Runs a full hardware and local service diagnostic scan for the onboarding wizard
        and preferences screen, returning beginner-friendly recommendations for Gemma 4,
        Cognitive Horizon, SDXL, and MusicGen.
        """
        gpu_info = cls.get_gpu_info()
        ram_info = cls.get_system_ram_info()
        vram = gpu_info.get("total_vram_gb", 0.0)

        # Classify overall hardware tier in plain English
        if vram >= 28.0:
            hw_tier_title = "Enthusiast / Multi-GPU Workstation (32 GB+ Class)"
            hw_tier_color = "#22c55e"
            hw_tier_explain = (
                "Your computer has abundant video memory. You can run Calypso's largest Gemma 4 brains, "
                "deep 32K conversation memory, high-detail 1024×1024 SDXL art, and MusicGen audio."
            )
        elif vram >= 15.5:
            hw_tier_title = "High-Performance GPU (16–24 GB Class)"
            hw_tier_color = "#38bdf8"
            hw_tier_explain = (
                "Your graphics card is well-suited for local AI. It hits the sweet spot for Gemma 4 12B or 26B MoE, "
                "a 16K memory window, full SDXL 1024×1024 artwork, and meets the 16 GB requirement for MusicGen."
            )
        elif vram >= 8.0:
            hw_tier_title = "Mainstream Gaming GPU (8–12 GB Class)"
            hw_tier_color = "#f59e0b"
            hw_tier_explain = (
                "Your graphics card can run Calypso smoothly when tuned to its sweet spot! We've selected an agile "
                "Gemma 4 brain, an 8K memory window, fast SDXL rendering, and turned MusicGen OFF to protect your VRAM."
            )
        else:
            hw_tier_title = "Entry-Level / CPU-Assisted System (< 8 GB VRAM)"
            hw_tier_color = "#f87171"
            hw_tier_explain = (
                "Your system has limited dedicated video memory. We've configured ultra-light Gemma 4 Edge settings, "
                "compact memory limits, and disabled heavy background music/art tasks so Calypso stays responsive."
            )

        # Probe local Ollama instance for installed models
        ollama_online = False
        all_installed_models: List[str] = []
        base_url = str(ollama_url or "http://localhost:11434").split("/api")[0].rstrip("/")
        try:
            req = urllib.request.Request(f"{base_url}/api/tags", headers={"User-Agent": "EmotionCore-Diagnostics"})
            with urllib.request.urlopen(req, timeout=2.5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                ollama_online = True
                all_installed_models = [m.get("name", "") for m in data.get("models", []) if m.get("name")]
        except Exception:
            ollama_online = False

        installed_gemma4 = cls.filter_supported_gemma4_models(all_installed_models)
        non_gemma4_count = len(all_installed_models) - len(installed_gemma4)

        gemma_rec = cls.recommend_gemma4_model(installed_gemma4)
        cog_profile_id = cls.recommend_profile()
        cog_profile = cls.PROFILES.get(cog_profile_id, cls.PROFILES["grounded"])
        sdxl_rec = cls.recommend_sdxl_profile()
        music_rec = cls.evaluate_musicgen_eligibility()

        return {
            "gpu_info": gpu_info,
            "ram_info": ram_info,
            "hw_tier_title": hw_tier_title,
            "hw_tier_color": hw_tier_color,
            "hw_tier_explain": hw_tier_explain,
            "ollama_online": ollama_online,
            "installed_gemma4_models": installed_gemma4,
            "non_gemma4_ignored_count": non_gemma4_count,
            "gemma_recommendation": gemma_rec,
            "cognitive_profile_id": cog_profile_id,
            "cognitive_profile": cog_profile,
            "sdxl_recommendation": sdxl_rec,
            "musicgen_recommendation": music_rec,
        }

    @classmethod
    def estimate_vram_usage(cls, model_name: str, num_ctx: int) -> Dict[str, Any]:
        """
        Estimates total VRAM required (weights + KV cache + CUDA overhead)
        with calibrated heuristics for the Gemma 4 model family.
        """
        name_lower = (model_name or "").lower()
        if "70b" in name_lower or "72b" in name_lower:
            weights_gb = 40.0
            kv_gb_per_32k = 16.0
        elif "31b" in name_lower or "32b" in name_lower:
            weights_gb = 19.5
            kv_gb_per_32k = 12.0
        elif "26b" in name_lower or "27b" in name_lower:
            weights_gb = 16.5
            kv_gb_per_32k = 10.0
        elif "12b" in name_lower or "14b" in name_lower:
            weights_gb = 8.0
            kv_gb_per_32k = 5.0
        elif "7b" in name_lower or "8b" in name_lower or "9b" in name_lower:
            weights_gb = 5.5
            kv_gb_per_32k = 3.5
        elif "e4b" in name_lower or ":4b" in name_lower:
            weights_gb = 3.2
            kv_gb_per_32k = 2.0
        elif "e2b" in name_lower or ":2b" in name_lower:
            weights_gb = 1.8
            kv_gb_per_32k = 1.2
        else:
            weights_gb = 8.0
            kv_gb_per_32k = 5.0

        ctx_ratio = max(1, num_ctx) / 32768.0
        kv_cache_gb = kv_gb_per_32k * ctx_ratio
        cuda_overhead_gb = 1.5
        est_total_gb = round(weights_gb + kv_cache_gb + cuda_overhead_gb, 1)

        info = cls.get_gpu_info()
        available_vram = info.get("total_vram_gb", 0.0)

        if available_vram <= 0:
            status = "unknown"
            status_text = f"~{est_total_gb} GB est. (Running on System RAM / CPU)"
            color = "#94a3b8"
        elif est_total_gb <= available_vram * 0.92:
            status = "optimal"
            status_text = f"~{est_total_gb} GB est. / {available_vram} GB VRAM (✓ Fits Safely in Video Memory)"
            color = "#22c55e"
        elif est_total_gb <= available_vram * 1.05:
            status = "near_limit"
            status_text = f"~{est_total_gb} GB est. / {available_vram} GB VRAM (⚠️ Near Video Memory Limit)"
            color = "#f59e0b"
        else:
            status = "overflow"
            status_text = f"~{est_total_gb} GB est. / {available_vram} GB VRAM (🛑 Too Large — Will Spill to Slow System RAM)"
            color = "#ef4444"

        return {
            "est_total_gb": est_total_gb,
            "weights_gb": weights_gb,
            "kv_cache_gb": round(kv_cache_gb, 1),
            "available_vram_gb": available_vram,
            "status": status,
            "status_text": status_text,
            "color": color
        }


hardware_sentinel = HardwareSentinel()
