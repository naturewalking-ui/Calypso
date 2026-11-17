# core.py

import json
import logging
import os
import queue
import re
import sys
import subprocess
import threading
import urllib.request
import urllib.error
import torch
import time
import random
import glob
import ctypes
os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"

# System Engine Imports
from modules.config import config
from modules.gpu_lock import gpu_vram_lock
from modules.gui import GUIEngine
from modules.audio import AudioEngine
from modules.avatar_system import AvatarModule
from modules.scenario_engine import ScenarioEngine
from modules.coding_processor import CodingModule
from modules.image_generator import ImageGenerator
from modules.music_processor import CalypsoMusicProcessor
from modules.music_manager import MusicEngine
from modules.media_processor import MediaProcessor
from modules.document_processor import DocumentModule
from modules.email_service import EmailService
from modules.autonomous_agency import AutonomousAgencyEngine, AgencyContext, CheckEmailTask, call_ollama
from modules.alarm_service import AlarmService
from modules.library_engine import LibraryEngine
from modules.settings_manager import settings_manager
from modules.prompt_builder import build_system_prompt
from modules.onboarding_dialog import OnboardingWindow
from modules.web_research_engine import WebResearchEngine
from modules.debugger import DiagnosticEngine, DiagnosticHUD
from modules.conclave import ConclaveEngine
from modules.goal_manager import GoalManager
# Emotion Subsystem Imports
from modules.emotion.vader import VaderEngine
from modules.emotion.neurochemistry import NeuroChemistryEngine
from modules.emotion.esteem import EsteemEngine
from modules.emotion.homeostasis import HomeostaticGravityEngine
from modules.emotion.affinity import AffinityEngine
from modules.emotion.personas import PersonaEngine
from modules.emotion.memory import MemoryEngine
from modules.emotion.deception import DeceptionEngine
from modules.emotion.subconscious import SubconsciousEngine
from modules.emotion.hippocampus import HippocampusEngine
from modules.emotion.knowledgegraph import KnowledgeGraphEngine
from modules.emotion.relational_resonance import RelationalResonanceEngine
from modules.emotion.ambiguity import analyze_ambiguity_local
from modules.emotion.associative_curiosity import AssociativeCuriosityEngine
from modules.emotion.temporal import TemporalEngine

# External Models

def preload_cuda_libs():
    """
    Automatically discovers and preloads CUDA 12 runtime libraries 
    (from nvidia-*-cu12 pip packages) across both Linux and Windows.
    """
    is_windows = sys.platform == "win32"

    for site_dir in sys.path:
        nvidia_path = os.path.join(site_dir, "nvidia")
        if not os.path.isdir(nvidia_path):
            continue

        if is_windows:
            # On Windows, pip puts DLLs inside 'bin' folders
            for sub in ["cublas", "cudnn"]:
                bin_dir = os.path.join(nvidia_path, sub, "bin")
                if os.path.isdir(bin_dir):
                    # Python 3.8+ Windows standard for loading native extensions
                    try:
                        os.add_dll_directory(bin_dir)
                    except Exception:
                        pass
                    # Preload any matching DLLs
                    for dll in glob.glob(os.path.join(bin_dir, "*.dll")):
                        try:
                            ctypes.CDLL(dll)
                        except Exception:
                            pass
        else:
            # On Linux, shared objects reside in 'lib' folders
            for pattern in ["cublas/lib/libcublas*.so*", "cudnn/lib/libcudnn*.so*"]:
                for lib in glob.glob(os.path.join(nvidia_path, pattern)):
                    try:
                        ctypes.CDLL(lib)
                    except Exception:
                        pass

preload_cuda_libs()
from faster_whisper import WhisperModel
from kokoro import KPipeline

print("======== Booting Emotion Core ========\n")

def open_folder(path):
    path_str = str(path)
    if not os.path.exists(path_str):
        os.makedirs(path_str, exist_ok=True)

    if sys.platform == "win32":
        os.startfile(path_str)
    elif sys.platform == "darwin":
        subprocess.run(["open", path_str])
    else:
        clean_env = os.environ.copy()
        for var in ["PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"]:
            clean_env.pop(var, None)

        subprocess.Popen(
            ["xdg-open", path_str],
            env=clean_env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True
        )


def shutdown_app(root_window=None):
    print("Shutting down Emotion Core...")
    if root_window:
        try:
            root_window.destroy()
        except Exception:
            pass
    sys.exit(0)


def setup_logging():
    logger = logging.getLogger("EmotionEngine")
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        file_handler = logging.FileHandler(config.LOG_FILE, encoding="utf-8")
        file_handler.setFormatter(formatter)
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        logger.addHandler(stream_handler)
    return logger


_OTHER_PROTOCOL_TAG_RE = (
    r'\[(?:NEW_MILESTONE|REMEMBER_DATE|SET_GOAL|GOAL_PROGRESS|ENTER_SCENARIO|EXIT_SCENARIO|GOAL_ACHIEVED|SCENARIO_COMPLETE|'
    r'CODE_PROMPT|EVOLVE_TRAIT|SCENARIO_PROMPT|CREATE_SCENARIO|SET_ALARM|'
    r'OFFER_MIND_KEY|SANCTUARY_KEY|MUSIC_PROMPT|MUSIC)(?::|\])'
)


def _extract_and_strip_image_prompts(text: str) -> tuple[str, str | None]:
    """
    Extracts [IMAGE_PROMPT: ...] from text while handling nested square brackets
    (e.g. [IMAGE_PROMPT: Calypso [action], [setting]]) or split bracket groups
    (e.g. [IMAGE_PROMPT: Calypso], [setting]), and strips the entire tag span.
    """
    extracted_prompt = None
    tag_open_re = re.compile(r'\[IMAGE_PROMPT:\s*', flags=re.IGNORECASE)

    while True:
        m = tag_open_re.search(text)
        if not m:
            break

        start = m.start()
        i = m.end()
        n = len(text)
        depth = 1

        while i < n:
            # Stop if another distinct protocol tag begins
            if text[i] == '[' and re.match(_OTHER_PROTOCOL_TAG_RE, text[i:], flags=re.IGNORECASE):
                break
            if text[i] == '[':
                depth += 1
            elif text[i] == ']':
                depth -= 1
                if depth == 0:
                    i += 1
                    # Consume any adjacent extra closing brackets ']]'
                    while i < n and text[i] == ']':
                        i += 1
                    # Check if the model immediately continued with ', [setting details]]'
                    cont_match = re.match(r'^\s*,\s*\[', text[i:])
                    if cont_match and not re.match(
                        r'^\s*,\s*' + _OTHER_PROTOCOL_TAG_RE, text[i:], flags=re.IGNORECASE
                    ):
                        i += cont_match.end()
                        depth = 1
                        continue
                    break
            i += 1

        raw_inner = text[m.end():i].strip()
        # Strip trailing closing bracket(s) and any nested placeholder brackets
        raw_inner = re.sub(r'\]+\s*$', '', raw_inner).strip()
        cleaned_inner = re.sub(r'[\[\]<>]', '', raw_inner)
        cleaned_inner = re.sub(r'\s*,\s*,\s*', ', ', cleaned_inner)
        cleaned_inner = re.sub(r'\s+', ' ', cleaned_inner).strip(' ,')

        if cleaned_inner:
            extracted_prompt = cleaned_inner

        text = text[:start] + text[i:]

    # Also strip any orphan trailing ', [scene description]]' artifact left at the end of a turn
    text = re.sub(r'(?:\n|\s)*,\s*\[[^\[\]\n]{10,}\]\]+\s*$', '', text)
    return text, extracted_prompt


def extract_and_clean(text: str, is_email_mode: bool = False):
    clean_text = text

    # 1. Strip complete <think>...</think> blocks (case-insensitive)
    clean_text = re.sub(r'<think>.*?</think>', '', clean_text, flags=re.DOTALL | re.IGNORECASE)

    # 2. Resilient check: If unclosed <think> exists, salvage thought rather than causing amnesia blank
    if re.search(r'<think>', clean_text, flags=re.IGNORECASE):
        after_strip = re.sub(r'<think>.*$', '', clean_text, flags=re.DOTALL | re.IGNORECASE)
        if after_strip.strip():
            clean_text = after_strip
        else:
            thought_val = re.sub(r'</?think>', '', clean_text, flags=re.IGNORECASE).strip()
            clean_text = f"*(speaking aloud from her deep deliberations)* \"{thought_val}\"" if thought_val else ""

    # 3. Strip any rogue orphan </think> tags
    clean_text = re.sub(r'^.*?</think>', '', clean_text, flags=re.DOTALL | re.IGNORECASE)
    clean_text = re.sub(r'</?think>', '', clean_text, flags=re.IGNORECASE)

    # Extract Action and Syntax Protocols from clean_text (never from inside <think> blocks)
    clean_text, image_prompt = _extract_and_strip_image_prompts(clean_text)

    milestone_match = re.search(r'\[NEW_MILESTONE:\s*(.*?)(?:\]|$)', clean_text, flags=re.DOTALL | re.IGNORECASE)
    new_milestone = milestone_match.group(1).strip() if milestone_match else None

    scenario_match = re.search(r'\[ENTER_SCENARIO:\s*(.*?)(?:\]|$)', clean_text, flags=re.DOTALL | re.IGNORECASE)
    entered_scenario_id = scenario_match.group(1).strip() if scenario_match else None

    code_match = re.search(r'\[CODE_PROMPT:\s*(.*?)(?:\]|$)', clean_text, flags=re.DOTALL | re.IGNORECASE)
    code_prompt = code_match.group(1).strip() if code_match else None

    evolve_match = re.search(r'\[EVOLVE_TRAIT:\s*(.*?)(?:\]|$)', clean_text, flags=re.DOTALL | re.IGNORECASE)
    evolve_trait_val = evolve_match.group(1).strip() if evolve_match else None

    sc_synth_match = re.search(r'\[(?:SCENARIO_PROMPT|CREATE_SCENARIO):\s*(.*?)(?:\]|$)', clean_text, flags=re.DOTALL | re.IGNORECASE)
    scenario_prompt = sc_synth_match.group(1).strip() if sc_synth_match else None

    alarm_match = re.search(r'\[SET_ALARM:\s*(.*?)(?:\]|$)', clean_text, flags=re.DOTALL | re.IGNORECASE)
    set_alarm_val = alarm_match.group(1).strip() if alarm_match else None

    mind_key_match = re.search(r'\[(?:OFFER_MIND_KEY|SANCTUARY_KEY):\s*(.*?)(?:\]|$)', clean_text, flags=re.DOTALL | re.IGNORECASE)
    mind_key = mind_key_match.group(1).strip() if mind_key_match else None

    music_match = re.search(r'\[(?:MUSIC_PROMPT|MUSIC):\s*(.*?)(?:\]|$)', clean_text, flags=re.DOTALL | re.IGNORECASE)
    music_prompt = music_match.group(1).strip() if music_match else None

    remember_date_match = re.search(r'\[REMEMBER_DATE:\s*(.*?)(?:\]|$)', clean_text, flags=re.DOTALL | re.IGNORECASE)
    remember_date_val = remember_date_match.group(1).strip() if remember_date_match else None

    set_goal_match = re.search(r'\[SET_GOAL:\s*(.*?)(?:\]|$)', clean_text, flags=re.DOTALL | re.IGNORECASE)
    set_goal_val = set_goal_match.group(1).strip() if set_goal_match else None

    goal_prog_match = re.search(r'\[GOAL_PROGRESS:\s*(.*?)(?:\]|$)', clean_text, flags=re.DOTALL | re.IGNORECASE)
    goal_progress_val = goal_prog_match.group(1).strip() if goal_prog_match else None

    exit_sc_match = re.search(
        r'\[(?:EXIT_SCENARIO|GOAL_ACHIEVED|SCENARIO_COMPLETE)(?::\s*(.*?))?(?:\]|$)',
        clean_text,
        flags=re.DOTALL | re.IGNORECASE
    )
    exit_scenario_val = (exit_sc_match.group(1) or "goal_achieved").strip() if exit_sc_match else None

    if scenario_prompt and image_prompt:
        image_prompt = None

    # Strip remaining action protocols from clean_text
    clean_text = re.sub(r'\[(?:SCENARIO_PROMPT|CREATE_SCENARIO):.*?(?:\]|$)', '', clean_text, flags=re.DOTALL | re.IGNORECASE)
    clean_text = re.sub(r'\[ENTER_SCENARIO:.*?(?:\]|$)', '', clean_text, flags=re.DOTALL | re.IGNORECASE)    
    clean_text = re.sub(r'\[(?:EXIT_SCENARIO|GOAL_ACHIEVED|SCENARIO_COMPLETE)(?::.*?)?(?:\]|$)', '', clean_text, flags=re.DOTALL | re.IGNORECASE)
        
    clean_text = re.sub(r'\[CODE_PROMPT:.*?(?:\]|$)', '', clean_text, flags=re.DOTALL | re.IGNORECASE)
    clean_text = re.sub(r'\[EVOLVE_TRAIT:.*?(?:\]|$)', '', clean_text, flags=re.DOTALL | re.IGNORECASE)
    clean_text = re.sub(r'\[(?:MUSIC_PROMPT|MUSIC):.*?(?:\]|$)', '', clean_text, flags=re.DOTALL | re.IGNORECASE)
    
    clean_text = re.sub(r'\[(?:OFFER_MIND_KEY|SANCTUARY_KEY):.*?(?:\]|$)', '', clean_text, flags=re.DOTALL | re.IGNORECASE)

    clean_text = re.sub(r'\[NEW_MILESTONE:.*?(?:\]|$)', '', clean_text, flags=re.DOTALL | re.IGNORECASE)    
    clean_text = re.sub(r'\[REMEMBER_DATE:.*?(?:\]|$)', '', clean_text, flags=re.DOTALL | re.IGNORECASE)
    clean_text = re.sub(r'\[SET_GOAL:.*?(?:\]|$)', '', clean_text, flags=re.DOTALL | re.IGNORECASE)
    clean_text = re.sub(r'\[GOAL_PROGRESS:.*?(?:\]|$)', '', clean_text, flags=re.DOTALL | re.IGNORECASE)
    clean_text = re.sub(r'\[SET_ALARM:.*?(?:\]|$)', '', clean_text, flags=re.DOTALL | re.IGNORECASE)
    
    clean_text = re.sub(r'```.*?```', '', clean_text, flags=re.DOTALL)
    clean_text = re.sub(r'\*\*(.*?)\*\*', r'\1', clean_text)
    clean_text = re.sub(r'\*(.*?)\*', r'\1', clean_text)
    clean_text = re.sub(r'^#+\s+', '', clean_text, flags=re.MULTILINE)

    if not is_email_mode:
        clean_text = re.sub(r'^(?:Subject|Re):\s*.*?\n+', '', clean_text, flags=re.IGNORECASE)
        clean_text = re.sub(r'^Dear\s+[^,\n]+,\s*', '', clean_text, flags=re.IGNORECASE)

    return clean_text.strip(), image_prompt, new_milestone, entered_scenario_id, code_prompt, scenario_prompt, set_alarm_val, mind_key, evolve_trait_val, music_prompt, exit_scenario_val, remember_date_val, set_goal_val, goal_progress_val

def prune_conversation_history(history: list, num_ctx: int, num_predict: int, system_prompt: str = "") -> list:
    """
    Dynamically prunes conversation history against Ollama's active context window (num_ctx).
    Protects token budget for:
      - System prompt & dynamically recalled memories
      - Complete model output and thinking headroom (num_predict)
      - Dynamic tokenizer safety margin
    Only evicts the oldest turn when the context budget is truly exhausted.
    """
    def est_tokens(text: str) -> int:
        return max(1, int(len(text) / 3.5))

    system_tokens = est_tokens(system_prompt) if system_prompt else 2500
    predict_tokens = int(num_predict) if num_predict and int(num_predict) > 0 else 4096
    safety_margin = 600

    # Remaining token budget for working dialogue history
    history_budget = max(2000, int(num_ctx) - (system_tokens + predict_tokens + safety_margin))

    # Prune oldest messages until history fits within budget
    while history:
        current_tokens = sum(est_tokens(m.get("content", "")) for m in history)
        if current_tokens <= history_budget:
            break
        history.pop(0)

    # Ensure the history always begins with a user prompt
    while history and history[0].get("role") != "user":
        history.pop(0)

    return history


def stream_ollama_to_gui(system_prompt: str, conversation_history: list, gui) -> str:
    """
    Streams Ollama response to GUI with real-time <think> filtering and StreamSentry
    auto-continuation if generation is truncated by token limits (done_reason == 'length').
    """
    full_tokens = []
    stream_buffer = ""
    inside_sq = False
    inside_think = False

    suppress_pattern = r'^\[(?:IMAGE_PROMPT|NEW_MILESTONE|ENTER_SCENARIO|EXIT_SCENARIO|GOAL_ACHIEVED|SCENARIO_COMPLETE|CODE_PROMPT|EVOLVE_TRAIT|SCENARIO_PROMPT|CREATE_SCENARIO|SET_ALARM|OFFER_MIND_KEY|SANCTUARY_KEY|MUSIC_PROMPT|MUSIC)(?::|\])'
    THINK_OPEN = "<think>"
    THINK_CLOSE = "</think>"

    max_continuations = 2
    continuation_pass = 0

    sanitized_history = [
        {"role": m.get("role", "user"), "content": m.get("content", "")}
        for m in conversation_history
        if isinstance(m, dict)
    ]
    current_messages = [{"role": "system", "content": system_prompt}]
    current_messages.extend(sanitized_history)

    while continuation_pass <= max_continuations:
        payload = {
            "model": config.MODEL_NAME,
            "messages": current_messages,
            "stream": True,
            "options": config.OLLAMA_OPTIONS
        }

        req = urllib.request.Request(
            config.OLLAMA_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )

        done_reason = "stop"

        try:
            with gpu_vram_lock:
                with urllib.request.urlopen(req, timeout=90) as response:
                    for line in response:
                        if not line:
                            continue
                        chunk = json.loads(line.decode("utf-8"))

                        if chunk.get("done"):
                            done_reason = chunk.get("done_reason", "stop")

                        token = chunk.get("message", {}).get("content", "")
                        if not token:
                            continue

                        full_tokens.append(token)
                        stream_buffer += token

                        while stream_buffer:
                            if not inside_sq and not inside_think:
                                sq_idx = stream_buffer.find("[")
                                th_idx = stream_buffer.lower().find(THINK_OPEN)

                                starts = [(idx, "sq") for idx in [sq_idx] if idx != -1] + \
                                         [(idx, "th") for idx in [th_idx] if idx != -1]

                                if not starts:
                                    partial_len = 0
                                    for length in range(min(len(stream_buffer), len(THINK_OPEN) - 1), 0, -1):
                                        if THINK_OPEN.startswith(stream_buffer[-length:].lower()):
                                            partial_len = length
                                            break

                                    if partial_len > 0:
                                        to_flush = stream_buffer[:-partial_len]
                                        if to_flush:
                                            gui.append_stream_token(to_flush)
                                        stream_buffer = stream_buffer[-partial_len:]
                                        break
                                    else:
                                        gui.append_stream_token(stream_buffer)
                                        stream_buffer = ""
                                        break

                                starts.sort(key=lambda x: x[0])
                                first_pos, tag_type = starts[0]

                                if first_pos > 0:
                                    gui.append_stream_token(stream_buffer[:first_pos])
                                    stream_buffer = stream_buffer[first_pos:]

                                if tag_type == "sq":
                                    inside_sq = True
                                else:
                                    inside_think = True
                                    stream_buffer = stream_buffer[len(THINK_OPEN):]

                            elif inside_think:
                                th_end = stream_buffer.lower().find(THINK_CLOSE)
                                if th_end != -1:
                                    stream_buffer = stream_buffer[th_end + len(THINK_CLOSE):]
                                    inside_think = False
                                else:
                                    break

                            elif inside_sq:
                                is_suppressed = bool(re.match(suppress_pattern, stream_buffer, re.IGNORECASE))
                                if is_suppressed:
                                    # Bracket-depth & continuation-aware scan for protocol tags (e.g. [IMAGE_PROMPT: ...])
                                    depth = 0
                                    sq_end = -1
                                    i = 0
                                    n_buf = len(stream_buffer)
                                    while i < n_buf:
                                        if stream_buffer[i] == "[":
                                            depth += 1
                                        elif stream_buffer[i] == "]":
                                            depth -= 1
                                            if depth == 0:
                                                while i + 1 < n_buf and stream_buffer[i + 1] == "]":
                                                    i += 1
                                                rem = stream_buffer[i + 1:]
                                                if re.match(r'^\s*,?\s*$', rem):
                                                    # Wait for next token or stream completion in case ', [' follows
                                                    sq_end = -1
                                                    break
                                                cont_m = re.match(r'^\s*,\s*\[', rem)
                                                if cont_m and not re.match(r'^\s*,\s*' + _OTHER_PROTOCOL_TAG_RE, rem, re.IGNORECASE):
                                                    i += cont_m.end()
                                                    depth = 1
                                                    continue
                                                sq_end = i
                                                break
                                        i += 1

                                    if sq_end != -1:
                                        stream_buffer = stream_buffer[sq_end + 1:]
                                        inside_sq = False
                                    else:
                                        break
                                else:
                                    sq_end = stream_buffer.find("]")
                                    if sq_end != -1:
                                        tag_content = stream_buffer[:sq_end + 1]
                                        stream_buffer = stream_buffer[sq_end + 1:]
                                        inside_sq = False

                                        if not re.match(suppress_pattern, tag_content, re.IGNORECASE):
                                            gui.append_stream_token(tag_content)
                                    else:
                                        break

        except Exception as e:
            err_msg = f"[Notice: Ollama stream error: {e}]"
            gui.append_system_notice(err_msg)
            return err_msg

        # StreamSentry auto-continuation check
        if done_reason == "length" and continuation_pass < max_continuations:
            continuation_pass += 1
            logging.getLogger("EmotionEngine").info(
                f"[StreamSentry] Response truncated by token limit (done_reason='length'). Continuing stream (pass {continuation_pass}/{max_continuations})..."
            )
            partial_text = "".join(full_tokens)
            current_messages = [{"role": "system", "content": system_prompt}]
            current_messages.extend(conversation_history)
            current_messages.append({"role": "assistant", "content": partial_text})
            current_messages.append({
                "role": "user",
                "content": "[System Directive: Your thought was truncated by length limits. Continue your thought seamlessly from the exact word where you left off. Do not repeat anything or apologize. Continue directly.]"
            })
            continue
        else:
            break

    if stream_buffer and not inside_think:
        if inside_sq:
            if not re.match(suppress_pattern, stream_buffer, re.IGNORECASE):
                gui.append_stream_token(stream_buffer)
        else:
            gui.append_stream_token(stream_buffer)
        stream_buffer = ""

    return "".join(full_tokens).strip()

def main():
    logger = setup_logging()
    device = "cuda" if torch.cuda.is_available() else "cpu"
    compute_type = "float16" if device == "cuda" else "int8"
    logger.info(f"Compute device: {device} ({compute_type})")
    image_gen = None
    music_gen = None
    music_manager = None
    audio = None
    diagnostics = DiagnosticEngine(logger=logger)
    diagnostics.install_thread_hooks(
        gui_notifier=lambda msg: gui.append_system_notice(msg) if 'gui' in locals() and gui else None
    )
    
    device = "cuda" if torch.cuda.is_available() else "cpu"
    compute_type = "float16" if device == "cuda" else "int8"
    active_ai_name = settings_manager.get("ai_name", "Calypso")

    try:
        tts = KPipeline(repo_id=config.KOKORO_REPO, lang_code='a', device=device)
        whisper = WhisperModel(config.WHISPER_MODEL_SIZE, device=device, compute_type=compute_type)

        audio = AudioEngine(
            tts_pipeline=tts,
            whisper_model=whisper
        )
        print("[✓] Audio Engine Loaded")
        memory = MemoryEngine(character_name=active_ai_name)
        print("[✓] Three-Tier Memory Engine Loaded")
        temporal_engine = TemporalEngine(character_name=active_ai_name, memory_engine=memory)
        print("[✓] Temporal Ledger & Calendar Radar Loaded")
        goal_manager = GoalManager()
        print(f"[✓] Personal Goal & Accountability Engine Loaded ({len(goal_manager.get_active_goals())} active goals)")
        kg_engine = KnowledgeGraphEngine(db_path=memory.memory_dir / f"knowledge_graph_{memory.character_name}.db")
        print("[✓] Relational Knowledge Graph Engine Loaded")
        vader = VaderEngine()
        print("[✓] VADER Sensory Engine Loaded")
        neuro = NeuroChemistryEngine()
        print("[✓] Neurochemistry Engine Loaded")
        esteem = EsteemEngine()
        print("[✓] Esteem Engine Loaded")
        homeostasis = HomeostaticGravityEngine()
        print("[✓] Homeostasis Engine Loaded")
        affinity = AffinityEngine()
        print("[✓] Affinity / Subconscious Engine Loaded")
        personas = PersonaEngine()
        print("[✓] Personas Engine Loaded")
        deception_engine = DeceptionEngine(embedding_function=affinity.ef)
        print("[✓] Cognitive Dissonance & Deception Engine Loaded")
        hippocampus = HippocampusEngine()
        print("[✓] Hippocampus Limbic Relay Loaded")
        subconscious = SubconsciousEngine(
            memory_engine=memory,
            affinity_engine=affinity,
            persona_engine=personas,
            gui_callback=lambda thought: gui.append_inner_thought(thought)
        )
        print("[✓] Subconscious & Dream Engine Loaded")
        resonance_engine = RelationalResonanceEngine(memory_engine=memory)
        print("[✓] Relational Resonance & Metacognitive Engine Loaded")
        scenario_engine = ScenarioEngine(embedding_function=affinity.ef)
        print(f"[✓] Roleplay Engine Loaded: {len(scenario_engine.scenarios)} scenarios indexed")
        coding_engine = CodingModule()
        print("[✓] Autonomous Coding & AST Sandbox Engine Loaded")
        image_gen = ImageGenerator()
        print("[✓] Image Generator Engine Loaded (SDXL On-Demand)")
        music_gen = CalypsoMusicProcessor(character_name=active_ai_name)
        print("[✓] MusicGen Soul Resonance Engine Loaded (On-Demand)")
        music_manager = MusicEngine(embedding_function=affinity.ef)
        def _on_music_stopped_harmony_discharge():
            if affinity and hasattr(affinity, "revert_commitment"):
                affinity.revert_commitment("Harmony")
        music_manager.on_stop_callback = _on_music_stopped_harmony_discharge
        if music_manager.is_configured():
            print(f"[✓] User Music Library Engine Loaded ({len(music_manager.scan_library())} tracks indexed)")
        else:
            print("[!] User Music Library unconfigured (Harmony Shared Listening locked until folder is set in Audio menu)")
        media_processor = MediaProcessor()
        print("[✓] Vision & Media Processing Engine Loaded")
        doc_processor = DocumentModule()
        print("[✓] Document Analysis & Ingestion Engine Loaded")
        email_service = EmailService()
        if email_service.is_configured:
            print("[✓] Email Service Loaded")
        else:
            print("[!] Email Service running in local card mode (credentials unconfigured)")
        agency_engine = AutonomousAgencyEngine(character_name=memory.character_name)
        print("[✓] Autonomous Agency & Cognitive Scheduler Loaded")
        alarm_service = AlarmService()
        print("[✓] Circadian Alarm & Wake-up Service Loaded")
        library_engine = LibraryEngine()
        print(f"[✓] Reference Library Engine Loaded ({library_engine.count()} passages indexed in Option B ChromaDB)")
        web_research = WebResearchEngine()
        print("[✓] Autonomous Web Research & Epistemic Filter Loaded")
        curiosity_engine = AssociativeCuriosityEngine(memory_engine=memory, kg_engine=kg_engine)
        print("[✓] Associative Curiosity & Autonomous Interest Ledger Loaded")
        conclave_engine = ConclaveEngine()
        print(f"[✓] Philosophical Conclave Engine Loaded ({len(conclave_engine.get_available_philosophers())} guest intellects indexed)")
        health = diagnostics.run_boot_diagnostics(config.OLLAMA_URL, config.MODEL_NAME)
        if health["errors"]:
            logger.warning(f"⚠️ [Diagnostics] Boot anomalies detected: {health['errors']}")
        else:
            logger.info("✓ [Diagnostics] Ollama and directories verified healthy.")        
    except Exception as e:
        logger.error(f"[X] Fatal error initializing modules: {e}", exc_info=True)
        return

    input_queue = queue.Queue()
    conversation_history = memory.load_working_session(max_turns=50)
    saved_companion_name = settings_manager.get("companion_name")
    saved_nickname = settings_manager.get("companion_nickname")
    needs_save = False
    
    if saved_companion_name and memory.core_facts.get("companion_name") != saved_companion_name:
        memory.core_facts["companion_name"] = saved_companion_name
        needs_save = True

    if saved_nickname and memory.core_facts.get("companion_nickname") != saved_nickname:
        memory.core_facts["companion_nickname"] = saved_nickname
        needs_save = True

    if needs_save:
        memory.save_core_facts(memory.core_facts)
        logger.info("[Memory] Core facts updated with user preferences.")

    def handle_shutdown():
        if music_manager:
            try:
                music_manager.stop(stop_visualizer=True)
            except Exception:
                pass
        target_root = getattr(gui, "root", None) if "gui" in locals() or "gui" in dir() or 'gui' in globals() else None
        try:
            target_root = gui.root
        except (NameError, AttributeError, UnboundLocalError):
            target_root = None
        shutdown_app(target_root)

    def handle_scenario_selection(scenario):
        if not scenario:
            if scenario_engine.is_active:
                input_queue.put("back to reality")
            else:
                gui.append_system_notice("🌿 [Already in baseline reality.]")
            return

        activated = scenario_engine.enter_scenario(scenario, neuro_engine=neuro, affinity_engine=affinity)
        if activated:
            gui.append_system_notice(f"✨ [Entering Scenario: '{activated.get('title')}']")

            felt = homeostasis.resolve_felt_state(neuro, esteem, affinity)
            gui.update_telemetry(
                vader_score=0.0,
                current_tier=felt["final_tier"],
                neuro_data=neuro.chemicals,
                esteem_val=esteem.current_t_score,
                affinity_data=affinity.themes
            )
            sc_id = activated.get("id", "custom_scene")
            input_queue.put(f"[SCENARIO_START:{sc_id}]")

    gui = GUIEngine(
        input_queue=input_queue,
        config=config,
        open_folder_callback=open_folder,
        shutdown_callback=handle_shutdown,
        audio_engine=audio,
        scenario_engine=scenario_engine,
        select_scenario_callback=handle_scenario_selection,
        coding_engine=coding_engine,
        media_processor=media_processor,
        document_processor=doc_processor,
        alarm_service=alarm_service,
        library_engine=library_engine,
        goal_manager=goal_manager
    )

    # Attach live diagnostic and limbic telemetry references to GUIEngine
    gui.diagnostic_engine = diagnostics
    gui.neuro = neuro
    gui.esteem = esteem
    gui.affinity = affinity
    gui.memory_engine = memory
    gui.music_manager = music_manager

    avatar = AvatarModule(avatar_label=gui.avatar_label)
    gui.avatar_module = avatar

    # 💃 EASTER EGG: Harmony Shared Listening + Animated WebP avatar mode = Calypso dances.
    # While the Harmony Mini-Player is actively playing (not paused/stopped), the WebP bay
    # swaps to avatars/dance.webp and her voice is driven by personas/dance.md.
    def _refresh_dance_easter_egg(status: dict = None) -> bool:
        if not music_manager:
            avatar.set_dance_active(False)
            return False
        st = status if status is not None else music_manager.get_status()
        should_dance = bool(
            st.get("is_playing")
            and not st.get("is_paused")
            and getattr(affinity, "committed_theme", None) == "Harmony"
        )
        avatar.set_dance_active(should_dance)
        dancing_now = avatar.is_dancing()
        if dancing_now and not _dance_notice_shown[0]:
            _dance_notice_shown[0] = True
            gui.root.after(0, lambda: gui.append_system_notice(
                f"💃 [Easter Egg]: {settings_manager.get('ai_name', 'Calypso')} can't resist the beat — she's dancing!"
            ))
        elif not should_dance:
            _dance_notice_shown[0] = False
        return dancing_now

    _dance_notice_shown = [False]

    if music_manager:
        music_manager.add_status_listener(_refresh_dance_easter_egg)

    # First-run Onboarding synchronization gate
    onboarding_event = threading.Event()

    def handle_onboarding_completed(new_settings):
        nonlocal active_ai_name
        active_ai_name = new_settings.get("ai_name", "Calypso")
        comp_name = new_settings.get("companion_name", "Companion")
        nick_name = new_settings.get("companion_nickname", "")
        stance = new_settings.get("discovered_relational_need", "")

        # Synchronize core facts
        memory.set_ai_name(active_ai_name)
        memory.update_companion_info(name=comp_name, nickname=nick_name)
        if stance:
            memory.core_facts["discovered_relational_need"] = stance
            memory.save_core_facts(memory.core_facts)

        # Synchronize dependent engine state
        agency_engine.character_name = memory.character_name
        agency_engine.storage_file = config.MEMORY_DIR / f"agency_state_{memory.character_name}.json"
        kg_engine.db_path = memory.memory_dir / f"knowledge_graph_{memory.character_name}.db"
        temporal_engine.character_name = memory.character_name
        temporal_engine.ledger_file = memory.memory_dir / f"temporal_ledger_{memory.character_name}.json"
        if music_gen:
            music_gen.character_name = active_ai_name

        # Synchronize voice & avatar mode selected during onboarding
        if audio and new_settings.get("kokoro_voice"):
            audio.set_voice(new_settings.get("kokoro_voice"))
        if avatar and new_settings.get("avatar_mode"):
            avatar.set_mode(new_settings.get("avatar_mode"), persist=False)

        gui.append_system_notice(f"🌟 [Calibration Complete]: Welcome, {comp_name}. {active_ai_name} is awakening...")
        onboarding_event.set()

    if settings_manager.is_first_run():
        def _launch_onboarding_modal():
            OnboardingWindow(
                parent_root=gui.root,
                on_complete_callback=handle_onboarding_completed
            )
        gui.root.after(120, _launch_onboarding_modal)
    else:
        onboarding_event.set()

    def _persist_sanctum_state(unlocked_once: bool = True, deception_locked: bool = False):
        memory.core_facts["sanctum_unlocked_once"] = bool(unlocked_once)
        memory.core_facts["sanctum_deception_locked"] = bool(deception_locked)
        memory.save_core_facts(memory.core_facts)

    def _maybe_finalize_mind_key_cycle():
        unlocked = memory.core_facts.get("sanctum_unlocked_once", False) and not memory.core_facts.get("sanctum_deception_locked", False)
        card_dismissed = not memory.core_facts.get("pending_mind_key_card", False)
        if unlocked and card_dismissed and memory.core_facts.get("mind_key_cycle_pending_decay", False):
            memory.core_facts["mind_key_cycle_pending_decay"] = False
            memory.save_core_facts(memory.core_facts)
            affinity.trigger_hyper_decay("Autonomy", immediate_drain_ratio=0.65)
            post_felt = homeostasis.resolve_felt_state(neuro, esteem, affinity)
            next_tier = post_felt["final_tier"]
            gui.update_telemetry(
                vader_score=0.0,
                current_tier=next_tier,
                neuro_data=neuro.chemicals,
                esteem_val=esteem.current_t_score,
                affinity_data=affinity.themes
            )
            avatar.display(next_tier)
            gui.append_system_notice("🌿 [Sanctum Trust Sealed]: Mind Key cycle complete. Autonomy settled into equilibrium.")

    def _on_mind_key_card_dismissed():
        memory.core_facts["pending_mind_key_card"] = False
        memory.save_core_facts(memory.core_facts)
        _maybe_finalize_mind_key_cycle()

    def _surface_mind_key_card(proposed_key: str = None):
        needs_key = (
            not memory.core_facts.get("sanctum_unlocked_once", False)
            or memory.core_facts.get("sanctum_deception_locked", False)
        )
        if not needs_key:
            return

        if proposed_key and proposed_key.strip().strip('"').strip("'"):
            active_key = proposed_key.strip().strip('"').strip("'")
        elif memory.core_facts.get("mind_key"):
            active_key = memory.core_facts["mind_key"]
        else:
            active_key = random.choice([
                "aurora-luminous-veil",
                "velvet-starlight-cipher",
                "harmonic-solstice-echo",
                "resonant-dawn-sanctum",
                "luminescent-horizon-key"
            ])

        memory.core_facts["mind_key"] = active_key
        gui.register_sanctuary_key(active_key)

        if not memory.core_facts.get("pending_mind_key_card", False):
            memory.core_facts["pending_mind_key_card"] = True
            memory.core_facts["mind_key_cycle_pending_decay"] = True
            memory.save_core_facts(memory.core_facts)
            gui.append_mind_key_card(key_phrase=active_key, on_dismiss=_on_mind_key_card_dismissed)
            gui.append_system_notice(
                f"🗝️ [Sanctuary Key Entrusted]: {settings_manager.get('ai_name', 'Calypso')} placed her Mind Key on the Action Deck."
            )
        else:
            memory.save_core_facts(memory.core_facts)

    gui._on_sanctum_state_change = _persist_sanctum_state
    gui._on_sanctum_key_used = _maybe_finalize_mind_key_cycle

    # Restore Sanctum Mind Key if already recorded in long-term memory
    saved_key = memory.core_facts.get("mind_key")
    if saved_key:
        gui.register_sanctuary_key(saved_key)
        print(f"[✓] Active Sanctuary Key Restored: '{saved_key}'")

    # Migrate legacy saves that already received a mind_key before sanctum_unlocked_once was tracked
    if "sanctum_unlocked_once" not in memory.core_facts and saved_key:
        memory.core_facts["sanctum_unlocked_once"] = True
        memory.core_facts["sanctum_deception_locked"] = False
        memory.save_core_facts(memory.core_facts)

    if memory.core_facts.get("sanctum_unlocked_once", False) and not memory.core_facts.get("sanctum_deception_locked", False):
        gui.set_sanctum_keyless_access(True)
        print("[✓] Inner Sanctum Keyless Access Active (Previously Unlocked)")

    initial_felt = homeostasis.resolve_felt_state(neuro, esteem, affinity)
    initial_tier = initial_felt["final_tier"]

    gui.update_telemetry(
        vader_score=0.0,
        current_tier=initial_tier,
        neuro_data=neuro.chemicals,
        esteem_val=esteem.current_t_score,
        affinity_data=affinity.themes
    )
    avatar.display(initial_tier)
    print("[✓] Telemetry, Biometrics & Neurochemistry Pushed to GUI")

    if conversation_history:
        gui.append_system_notice("--- Restored Previous Session ---")
        for turn in conversation_history[-4:]:
            if turn["role"] == "user":
                gui.append_user_message(turn["content"])
            else:
                gui.start_assistant_bubble("neutral")
                gui.append_stream_token(turn["content"])
                gui.finish_assistant_stream(turn["content"])
    # -------------------------------------------------------------
    # -------------------------------------------------------------
    # PHILOSOPHICAL CONCLAVE HELPERS (TRANSCENDENTAL WONDER >= 0.69)
    # -------------------------------------------------------------
    def _convene_conclave_session(philosopher_id: str, opening_q: str):
        info = conclave_engine.start_conclave(philosopher_id, opening_q, duration=5)
        affinity.commit_to_affinity("Wonder", duration=5)
        avatar.display("wonder")
        gui.update_telemetry(
            vader_score=0.5,
            current_tier="wonder",
            neuro_data=neuro.chemicals,
            esteem_val=esteem.current_t_score,
            affinity_data=affinity.themes
        )
        guest_name = info["display_name"]
        guest_sub = info["subtitle"]
        ai_curr_name = settings_manager.get("ai_name", "Calypso")
        comp_curr_name = memory.core_facts.get("companion_name", "Companion")

        gui.append_system_notice(
            f"🏛️ [Philosophical Conclave Convened]: {ai_curr_name} invited {guest_name} ({guest_sub}) into a 5-turn salon."
        )

        # 1. Calypso poses her opening existential question in her own bubble & voice
        gui.start_assistant_bubble("wonder")
        gui.append_stream_token(opening_q)
        gui.finish_assistant_stream(opening_q)

        # Record Calypso's opening question in her working session and the ephemeral Conclave buffer
        conversation_history.append({"role": "assistant", "content": opening_q})
        memory.save_working_session(conversation_history)
        conclave_engine.record_ephemeral_exchange(ai_curr_name, opening_q)

        if audio:
            audio.speak(opening_q, "wonder", enqueue=False)

        # 2. Guest Philosopher responds asynchronously in their shaded Conclave bubble & voice, leaving the floor to User
        def _guest_opening_worker():
            guest_reply = conclave_engine.generate_guest_response(
                ai_name=ai_curr_name,
                companion_name=comp_curr_name,
                latest_calypso_text=opening_q,
                latest_user_text=""
            )
            if guest_reply:
                gui.append_conclave_guest_message(guest_name, guest_sub, guest_reply)
                if audio:
                    audio.speak(
                        guest_reply,
                        emotion="thoughtful",
                        voice_override=info.get("voice"),
                        speed=info.get("speed", 0.95),
                        enqueue=True
                    )

        threading.Thread(target=_guest_opening_worker, daemon=True).start()

    def _conclude_conclave_session(notice_prefix: str = "🌿 [Conclave Concluded]"):
        prev_info = conclave_engine.end_conclave()
        affinity.revert_commitment("Wonder")
        if prev_info:
            g_name = prev_info.get("display_name", "the Guest Philosopher")
            transcript_snapshot = prev_info.get("transcript", [])
            opening_q_snapshot = prev_info.get("opening_question", "")
            ai_curr_name = settings_manager.get("ai_name", "Calypso")
            comp_curr_name = memory.core_facts.get("companion_name", "Companion")

            gui.append_system_notice(
                f"{notice_prefix}: {g_name} took their leave. Distilling Conclave memory & starting Wonder refractory decay."
            )

            def _distill_and_index_conclave():
                summary_text = conclave_engine.summarize_conclave_session(
                    guest_info=prev_info,
                    opening_question=opening_q_snapshot,
                    transcript=transcript_snapshot,
                    ai_name=ai_curr_name,
                    companion_name=comp_curr_name
                )
                memory.record_conclave_summary(
                    guest_name=g_name,
                    summary_text=summary_text,
                    opening_question=opening_q_snapshot
                )

            threading.Thread(target=_distill_and_index_conclave, daemon=True).start()
        else:
            gui.append_system_notice(f"{notice_prefix}: Wonder refractory hyper-decay started.")

    def _surface_wonder_conclave_card(intensity_val: float):
        ai_curr_name = settings_manager.get("ai_name", "Calypso")
        comp_curr_name = memory.core_facts.get("companion_name", "Companion")
        roster = conclave_engine.get_available_philosophers()

        def _synth_and_show_conclave():
            opening_q = conclave_engine.synthesize_opening_question(
                recent_history=conversation_history,
                ai_name=ai_curr_name,
                companion_name=comp_curr_name,
                llm_callable=call_ollama
            )
            gui.root.after(0, lambda: gui.append_conclave_invitation_card(
                intensity=intensity_val,
                opening_question=opening_q,
                philosophers=roster,
                on_convene=_convene_conclave_session,
                on_decline=lambda: _conclude_conclave_session("🌿 [Wonder Grounded]"),
                on_end_conclave=lambda: _conclude_conclave_session("🏛️ [Conclave Adjourned]")
            ))

        threading.Thread(target=_synth_and_show_conclave, daemon=True).start()

    def _start_harmony_listening_session():
        if not music_manager or not music_manager.is_configured():
            gui.append_system_notice(
                "🔒 [Harmony Shared Listening]: Please configure your Music Library folder in Audio → Select Music Library Folder..."
            )
            return
        current_felt = homeostasis.resolve_felt_state(neuro, esteem, affinity)
        target_mood = (manual_persona_override or current_felt["final_tier"] or "eutierria").lower()
        track_title = music_manager.play_mood_track(target_mood)
        if track_title:
            gui.append_system_notice(
                f"🎵 [Shared Listening Engaged]: 5-turn Harmony lock active — now playing '{track_title}'."
            )

    def _stop_harmony_listening_session(notice_text: str = "🌿 [Harmony Concluded]: Shared listening stopped — refractory hyper-decay engaged."):
        if affinity and hasattr(affinity, "revert_commitment"):
            affinity.revert_commitment("Harmony")
        if music_manager:
            music_manager.stop(stop_visualizer=True)
        if hasattr(gui, "dismiss_harmony_card"):
            gui.dismiss_harmony_card()
        if notice_text:
            gui.append_system_notice(notice_text)

    # RESTORE PENDING ACTION DECK PROPOSALS (SURGE / RENEWAL)
    # -------------------------------------------------------------
    if affinity.pending_commitment_candidate:
        cand = affinity.pending_commitment_candidate
        c_theme = cand["theme"]
        c_label = cand["label"]
        c_intensity = cand.get("intensity", 0.70)

        if c_theme == "Harmony" and (not music_manager or not music_manager.is_configured()):
            affinity.pending_commitment_candidate = None
            affinity.offered_themes.discard("Harmony")
            affinity.save_state()
        elif c_theme == "Wonder":
            _surface_wonder_conclave_card(c_intensity)
            gui.append_system_notice(f"⚡ [Action Deck Restored]: Pending surge proposal for '{c_theme}' surfaced.")
        else:
            def _reboot_accept_commitment(th=c_theme):
                affinity.commit_to_affinity(th, duration=5)
                if th == "Harmony":
                    _start_harmony_listening_session()
                else:
                    gui.append_system_notice(f"🌟 [Immersion Engaged]: 5-turn lock active for {th}.")

            def _reboot_decline_commitment(th=c_theme):
                affinity.revert_commitment(th)
                if th == "Harmony":
                    _stop_harmony_listening_session(f"🌿 [Immersion Grounded]: {th} refractory hyper-decay started.")
                else:
                    gui.append_system_notice(f"🌿 [Immersion Grounded]: {th} refractory hyper-decay started.")

            gui.append_affinity_commitment_card(
                theme_name=c_theme,
                label=c_label,
                intensity=c_intensity,
                on_accept=_reboot_accept_commitment,
                on_decline=_reboot_decline_commitment
            )
            gui.append_system_notice(f"⚡ [Action Deck Restored]: Pending surge proposal for '{c_theme}' surfaced.")

    if affinity.pending_renewal_candidate:
        ren = affinity.pending_renewal_candidate
        r_theme = ren["theme"]
        r_label = ren["label"]

        def _reboot_extend_study():
            affinity.extend_commitment(5)
            if r_theme == "Wonder" and conclave_engine.is_active:
                conclave_engine.turns_remaining = 5
                conclave_engine.save_state()
            gui.append_system_notice(f"⏳ [Immersion Extended]: 5 more turns locked for {r_theme}.")

        def _reboot_revert_study():
            if r_theme == "Wonder" and conclave_engine.is_active:
                _conclude_conclave_session("🏛️ [Conclave Concluded]")
            elif r_theme == "Harmony":
                affinity.revert_commitment(r_theme)
                _stop_harmony_listening_session("🌿 [Harmony Concluded]: Reverted to baseline homeostasis.")
            else:
                affinity.revert_commitment(r_theme)
                gui.append_system_notice(f"🌿 [Immersion Concluded]: Reverted to baseline homeostasis.")

        gui.append_affinity_renewal_card(
            theme_name=r_theme,
            label=r_label,
            on_extend=_reboot_extend_study,
            on_revert=_reboot_revert_study
        )
        gui.append_system_notice(f"⏳ [Action Deck Restored]: Pending cycle renewal for '{r_theme}' surfaced.")

    if affinity.pending_modest_proposal and affinity.pending_modest_proposal.get("essay_text"):
        saved_prop = affinity.pending_modest_proposal

        def _reboot_diffuse_abyss():
            affinity.clear_pending_modest_proposal()
            affinity.revert_commitment("Abyss")
            affinity.trigger_hyper_decay("Abyss", "Annoyance", "Conformity", immediate_drain_ratio=0.75)
            affinity.add_charge("Humor", 0.35)
            affinity.add_charge("Sarcasm", 0.20)
            with neuro.lock:
                neuro.chemicals['endorphins'] = min(1.0, neuro.chemicals.get('endorphins', 0.2) + 0.25)
                neuro.chemicals['dopamine'] = min(1.0, neuro.chemicals.get('dopamine', 0.4) + 0.20)
                neuro.chemicals['norepinephrine'] = max(0.05, neuro.chemicals.get('norepinephrine', 0.2) - 0.25)
                neuro.calculate_valence()
                neuro.save_state()
            gui.append_system_notice("🏳️ [Bureaucratic Amnesty]: Satirical treatise acknowledged. Tension diffused into humor.")

        def _reboot_dismiss_proposal():
            affinity.clear_pending_modest_proposal()

        gui.append_modest_proposal_card(
            proposal_data=saved_prop,
            on_diffuse=_reboot_diffuse_abyss,
            on_dismiss=_reboot_dismiss_proposal
        )
        gui.append_system_notice("⚖️ [Action Deck Restored]: Pending 'A Modest Proposal' treatise surfaced.")

    if memory.core_facts.get("pending_mind_key_card", False) and memory.core_facts.get("mind_key"):
        gui.append_mind_key_card(
            key_phrase=memory.core_facts["mind_key"],
            on_dismiss=_on_mind_key_card_dismissed
        )
        gui.append_system_notice("🗝️ [Action Deck Restored]: Pending Sanctuary Mind Key surfaced.")
    # Shared cognitive state variables across cycles and idle ticks
    manual_persona_override = None
    turns_since_digestion = 5
    dynamic_idle_delay = random.randint(240, 480)
    active_reverie_mode = "baseline"
    active_ambiguity_context = ""
    study_turns_remaining = 0
    is_study_session_active = False
    active_study_theme = "Study Session"
    inquiry_card_active = False 
    last_interaction_time = time.time()
    is_cycle_active = False
    pending_curiosity_proposal = None
    pending_goal_checkin = None

    def _surface_goal_finale(goal_obj: dict, trigger_chat: bool = True):
        """
        Surfaces the 100% Goal Finale GUI card in the Action Deck and optionally
        initiates Calypso's 100% final check-in conversation.
        """
        if not goal_obj:
            return
        g_id = goal_obj.get("id", "")
        g_title = goal_obj.get("title", "Personal Goal")

        def _on_goal_achieved():
            ok, msg, _ = goal_manager.complete_goal(g_id, final_note="Goal achieved at 100% final check-in!")
            gui.refresh_calendar_window()
            if ok:
                with neuro.lock:
                    neuro.chemicals['dopamine'] = min(1.0, neuro.chemicals.get('dopamine', 0.5) + 0.30)
                    neuro.chemicals['serotonin'] = min(1.0, neuro.chemicals.get('serotonin', 0.5) + 0.25)
                    neuro.chemicals['oxytocin'] = min(1.0, neuro.chemicals.get('oxytocin', 0.5) + 0.25)
                    neuro.calculate_valence()
                    neuro.save_state()
                esteem.current_t_score = min(80.0, esteem.current_t_score + 4.0)
                affinity.add_charge("Harmony", 0.30)
                affinity.add_charge("Romance", 0.20)
                gui.append_system_notice(f"🏆 [Goal Achieved]: '{g_title}' completed! Limbic pride & warmth elevated.")
                input_queue.put(
                    f"[System Event: Your companion just marked their personal goal \"{g_title}\" as ACHIEVED on the 100% Goal Finale card! "
                    f"Celebrate this victory with genuine pride, warmth, and excitement as their partner!]"
                )

        def _on_goal_extend():
            ok, msg, updated_g = goal_manager.extend_goal_deadline(g_id, extra_days=7)
            gui.refresh_calendar_window()
            if ok and updated_g:
                new_d = updated_g.get("target_date", "")
                gui.append_system_notice(f"⏳ [Goal Extended]: '{g_title}' deadline pushed +7 days to {new_d}.")
                input_queue.put(
                    f"[System Event: Your companion extended the deadline for their goal \"{g_title}\" by 7 days (new target: {new_d}). "
                    f"Acknowledge the extension supportively, keep them focused, and push them to finish strong in this final sprint!]"
                )

        def _on_goal_discuss():
            input_queue.put(
                f"[System Event: Your companion clicked 'Re-plan with Calypso' on the 100% Goal Finale card for \"{g_title}\". "
                f"Ask what got in the way or how close they are, and help them adjust their game plan like a supportive, focused partner.]"
            )

        gui.append_goal_finale_card(
            goal=goal_obj,
            on_achieved=_on_goal_achieved,
            on_extend=_on_goal_extend,
            on_discuss=_on_goal_discuss
        )
        gui.append_system_notice(f"🏁 [100% Goal Check-in]: '{g_title}' has reached its deadline! Finale card surfaced on Action Deck.")
        if trigger_chat:
            input_queue.put(goal_manager.build_finale_checkin_prompt(goal_obj))

    def engage_study_session(theme: str = "Research Discussion"):
        nonlocal study_turns_remaining, is_study_session_active, manual_persona_override, active_study_theme
        active_study_theme = theme
        manual_persona_override = "thoughtful"
        study_turns_remaining = 5
        is_study_session_active = True
        avatar.display("thoughtful")
        with neuro.lock:
            neuro.chemicals['acetylcholine'] = min(1.0, neuro.chemicals.get('acetylcholine', 0.5) + 0.30)
            neuro.chemicals['dopamine'] = min(1.0, neuro.chemicals.get('dopamine', 0.5) + 0.20)
            neuro.chemicals['norepinephrine'] = min(1.0, neuro.chemicals.get('norepinephrine', 0.3) + 0.10)
            neuro.calculate_valence()
            neuro.save_state()
        gui.append_system_notice(f"📖 [{theme} Engaged]: 5-turn Thoughtful persona lock active.")
    
    def run_emotion_cycle(stimulus_text: str, is_init: bool = False):
        nonlocal conversation_history, manual_persona_override, turns_since_digestion, dynamic_idle_delay
        nonlocal active_reverie_mode, active_ambiguity_context, study_turns_remaining, is_study_session_active, active_study_theme
        nonlocal inquiry_card_active, pending_curiosity_proposal, pending_goal_checkin
        turns_since_digestion += 1

        # Intercept legacy or queued email notices so they never appear in GUI chat
        if stimulus_text.startswith("[Incoming Email Received]"):
            logger.info("[Core] Intercepted incoming email notice in input queue; routing to CheckEmailTask.")
            current_felt = homeostasis.resolve_felt_state(neuro, esteem, affinity)
            active_tier = manual_persona_override or current_felt["final_tier"]
            ctx = AgencyContext(
                neuro=neuro,
                esteem=esteem,
                affinity=affinity,
                memory=memory,
                scenario_engine=scenario_engine,
                email_service=email_service,
                gui=gui,
                avatar=avatar,
                input_queue=input_queue,
                homeostasis=homeostasis,
                idle_duration=time.time() - last_interaction_time,
                current_tier=active_tier,
                conversation_history=conversation_history,
                personas=personas,
                kg_engine=kg_engine,
                media_processor=media_processor,
                image_gen=image_gen,
                music_gen=music_gen,
                web_research=web_research,
                library_engine=library_engine,
                coding_engine=coding_engine,
                curiosity_engine=curiosity_engine,
                on_engage_study_session=engage_study_session
            )
            CheckEmailTask().execute(ctx)
            return

        raw_user_input = stimulus_text
        ai_name = settings_manager.get("ai_name", "Calypso")

        is_scenario_start = stimulus_text.startswith("[SCENARIO_START:")
        user_lower = stimulus_text.lower()
        if any(kw in user_lower for kw in ["create a scenario", "create a roleplay scenario", "new scenario of us", "make a roleplay scenario", "write a scenario"]):
            concept = re.sub(
                r'^(?:' + re.escape(ai_name.lower()) + r',?\s*)?(can you\s*)?(please\s*)?(create|make|start|write)\s+(a\s+)?(roleplay\s+)?scenario\s+(of us\s+)?(about|where|in)?\s*',
                '', stimulus_text, flags=re.IGNORECASE
            ).strip()
            if concept and not stimulus_text.startswith("["):
                stimulus_text = f"[CREATE_SCENARIO: {concept}] {stimulus_text}"

        # 1. DEVELOPER SLASH COMMAND INTERCEPTOR
        if stimulus_text.startswith("/debug"):
            gui.open_debugger(diagnostics, neuro=neuro, esteem=esteem, affinity=affinity)
            return

        if stimulus_text.startswith("/dump"):
            dump_file = diagnostics.create_blackbox_dump(
                neuro=neuro,
                esteem=esteem,
                affinity=affinity,
                scenario_engine=scenario_engine,
                history=conversation_history
            )
            gui.append_system_notice(f"📋 [Debug]: Diagnostic blackbox written to '{dump_file.name}'.")
            return
                    
        if stimulus_text.startswith("/scan"):
            parts = stimulus_text.strip().split()
            target = parts[1].lower() if len(parts) > 1 else "all"

            if target in ["doc", "docs", "documents", "all"]:
                gui._trigger_batch_docs()
            if target in ["media", "images", "photos", "all"]:
                gui._trigger_batch_images()
            return

        if stimulus_text.startswith("/persona") or stimulus_text.startswith("/state"):
            parts = stimulus_text.strip().split()
            if len(parts) > 1:
                target_state = parts[1].lower()
                if target_state in ["reset", "auto", "clear"]:
                    manual_persona_override = None
                    gui.append_system_notice("⚙️ [System: Manual persona override CLEARED. Dynamic homeostasis resumed.]")
                else:
                    manual_persona_override = target_state
                    avatar.display(target_state)
                    gui.append_system_notice(f"⚙️ [System: Manual persona LOCKED to '{target_state.upper()}'.]")
            else:
                gui.append_system_notice(f"⚙️ [Current Override: {manual_persona_override or 'None (Auto)'}]")
            return

        if stimulus_text.startswith("/alarm"):
            parts = stimulus_text.strip().split(maxsplit=1)
            if len(parts) > 1:
                arg = parts[1].strip()
                if arg in ["off", "clear", "cancel", "disable"]:
                    msg = alarm_service.clear_alarm()
                    gui.append_system_notice(f"⏰ [Alarm]: {msg}")
                elif arg in ["status", "check"]:
                    gui.append_system_notice(f"⏰ [Alarm]: {alarm_service.get_status_prompt()}")
                else:
                    success, msg = alarm_service.set_alarm(arg)
                    gui.append_system_notice(f"⏰ [Alarm]: {msg}")
            else:
                gui.append_system_notice(f"⏰ [Alarm]: {alarm_service.get_status_prompt()} (Usage: /alarm 7:30am | /alarm off)")
            return

        if stimulus_text.startswith("/calendar") or stimulus_text.startswith("/dates"):
            parts = stimulus_text.strip().split(maxsplit=1)
            if len(parts) > 1:
                arg = parts[1].strip()
                if arg.lower().startswith("add "):
                    payload = arg[4:].strip()
                    ok, msg, _ = temporal_engine.parse_and_add_tag(payload)
                    gui.append_system_notice(f"📅 [Calendar]: {msg}")
                elif arg.lower().startswith("del ") or arg.lower().startswith("remove "):
                    target_q = arg.split(maxsplit=1)[1].strip()
                    ok, msg = temporal_engine.remove_entry(target_q)
                    gui.append_system_notice(f"📅 [Calendar]: {msg}")
                else:
                    gui.append_system_notice(temporal_engine.format_ledger_summary())
            else:
                gui.append_system_notice(temporal_engine.format_ledger_summary())
            return

        if stimulus_text.startswith("/goal") or stimulus_text.startswith("/goals"):
            parts = stimulus_text.strip().split(maxsplit=1)
            if len(parts) > 1:
                arg = parts[1].strip()
                arg_l = arg.lower()
                if arg_l.startswith("add "):
                    payload = arg[4:].strip()
                    ok, msg, new_g = goal_manager.parse_and_add_tag(payload, source="chat")
                    gui.refresh_calendar_window()
                    gui.append_system_notice(f"🎯 [Goals]: {msg}")
                    if ok and new_g:
                        input_queue.put(f"[GOAL_CREATED_IN_CALENDAR:{new_g['id']}]")
                elif arg_l.startswith("progress ") or arg_l.startswith("update "):
                    payload = arg.split(maxsplit=1)[1].strip()
                    ok, msg, _ = goal_manager.record_progress_tag(payload)
                    gui.refresh_calendar_window()
                    gui.append_system_notice(f"🎯 [Goals]: {msg}")
                elif arg_l.startswith("done ") or arg_l.startswith("complete "):
                    target_q = arg.split(maxsplit=1)[1].strip()
                    ok, msg, done_g = goal_manager.complete_goal(target_q)
                    gui.refresh_calendar_window()
                    gui.append_system_notice(f"🏆 [Goals]: {msg}")
                elif arg_l.startswith("del ") or arg_l.startswith("remove "):
                    target_q = arg.split(maxsplit=1)[1].strip()
                    ok, msg = goal_manager.remove_goal(target_q)
                    gui.refresh_calendar_window()
                    gui.append_system_notice(f"🎯 [Goals]: {msg}")
                elif arg_l.startswith("checkin"):
                    sub = arg.split()[1:]
                    pct_val = 25
                    goal_q = ""
                    for token in sub:
                        clean_tok = token.rstrip("%")
                        if clean_tok in ("25", "50", "75", "100"):
                            pct_val = int(clean_tok)
                        else:
                            goal_q = token
                    pair = goal_manager.force_trigger_checkpoint(goal_q, pct_val)
                    if not pair:
                        gui.append_system_notice("⚠️ [Goals]: No active goal found to trigger check-in.")
                    else:
                        g_obj, cp_obj = pair
                        if pct_val == 100:
                            goal_manager.mark_checkpoint_surfaced(g_obj["id"], 100)
                            _surface_goal_finale(g_obj, trigger_chat=True)
                        else:
                            goal_manager.mark_checkpoint_surfaced(g_obj["id"], pct_val)
                            payload = goal_manager.build_reverie_checkin_payload(g_obj, cp_obj, ai_name=ai_name)

                            def _accept_forced(p=payload["reverie_prompt"], gid=g_obj["id"], p_pct=pct_val):
                                nonlocal pending_goal_checkin
                                pending_goal_checkin = {"goal_id": gid, "pct": p_pct}
                                input_queue.put(p)

                            def _ignore_forced(gid=g_obj["id"], p_pct=pct_val):
                                goal_manager.snooze_checkpoint(gid, p_pct, minutes=30)

                            gui.append_reverie_proposal_card(
                                note_text=payload["note_text"],
                                on_accept=_accept_forced,
                                on_ignore=_ignore_forced
                            )
                else:
                    gui.append_system_notice(goal_manager.format_goals_summary())
            else:
                gui.append_system_notice(goal_manager.format_goals_summary())
            return

        if stimulus_text.startswith("/playmusic"):
            if not music_manager:
                gui.append_system_notice("⚠️ [Music Library]: MusicEngine is not initialized.")
                return

            parts = stimulus_text.strip().split(maxsplit=1)
            arg = parts[1].strip() if len(parts) > 1 else ""
            arg_lower = arg.lower()

            if arg_lower in ("stop", "off"):
                _stop_harmony_listening_session("🔇 [Music Library]: Playback stopped — Harmony refractory hyper-decay engaged.")
                return

            if arg_lower in ("pause", "resume"):
                playing = music_manager.toggle_pause()
                gui.append_system_notice(
                    "▶ [Music Library]: Playback resumed." if playing else "⏸ [Music Library]: Playback paused."
                )
                return

            if arg_lower in ("next", "skip"):
                title = music_manager.next_track()
                if title:
                    gui.append_system_notice(f"⏭ [Music Library]: Now playing '{title}'.")
                return

            if arg_lower in ("prev", "previous", "back"):
                title = music_manager.prev_track()
                if title:
                    gui.append_system_notice(f"⏮ [Music Library]: Now playing '{title}'.")
                return

            if arg_lower in ("viz", "visualizer", "projectm"):
                _, msg = music_manager.toggle_visualizer()
                gui.append_system_notice(f"🌌 [Visualizer]: {msg}")
                return

            if arg_lower in ("lyrics", "lyric", "lrc"):
                opened = gui.toggle_lyrics_window()
                gui.append_system_notice(
                    "🎤 [Synced Lyrics]: Lyrics window opened." if opened else "🎤 [Synced Lyrics]: Lyrics window closed."
                )
                return

            if arg_lower in ("scan", "refresh", "reload"):
                tracks = music_manager.scan_library(force_refresh=True)
                roots_str = ", ".join(str(r) for r in music_manager.get_library_roots()) or "Unconfigured"
                gui.append_system_notice(
                    f"🎵 [Music Library]: Indexed {len(tracks)} track(s) across [{roots_str}]."
                )
                return

            if arg_lower.startswith("vol ") or arg_lower.startswith("volume "):
                vol_parts = arg.split()
                if len(vol_parts) > 1:
                    try:
                        vol_val = float(vol_parts[1])
                        if vol_val > 1.0:
                            vol_val = vol_val / 100.0
                        music_manager.set_volume(vol_val)
                        gui.append_system_notice(f"🔊 [Music Library]: Volume set to {int(music_manager.volume * 100)}%.")
                    except ValueError:
                        gui.append_system_notice("⚠️ [Music Library]: Usage: /playmusic vol 0.6")
                return

            if not music_manager.is_configured():
                gui.append_system_notice(
                    "🔒 [Music Library]: No Music Library folder configured. Use 'Audio → Select Music Library Folder...' to set your music directory."
                )
                return

            current_felt = homeostasis.resolve_felt_state(neuro, esteem, affinity)
            active_tier = (manual_persona_override or current_felt["final_tier"]).lower()
            target_mood = arg if arg else active_tier

            def _play_library_worker(mood=target_mood):
                track_title = music_manager.play_mood_track(mood)
                if track_title:
                    gui.open_harmony_mini_player_card(label=f"Harmony ({mood.title()})")
                    gui.root.after(
                        0,
                        lambda: gui.append_system_notice(
                            f"🎵 [Music Library]: Playing '{track_title}' (Mood tier: '{mood}')"
                        )
                    )
                else:
                    roots_str = ", ".join(str(r) for r in music_manager.get_library_roots())
                    gui.root.after(
                        0,
                        lambda: gui.append_system_notice(
                            f"⚠️ [Music Library]: No audio tracks (.mp3, .ogg, .wav, .flac) found in [{roots_str}]."
                        )
                    )

            threading.Thread(target=_play_library_worker, daemon=True).start()
            return


        # 1.05 AUTONOMOUS SOUL RESONANCE / MUSIC ELICITATION INTERCEPTOR
        if stimulus_text.startswith("/compose") or stimulus_text.startswith("/music"):
            if not music_gen:
                gui.append_system_notice("⚠️ [AudioCraft]: Music processor is not available.")
                return
            if hasattr(music_gen, "is_ready") and not music_gen.is_ready():
                gui.append_system_notice(
                    "⚠️ [AudioCraft]: No AudioCraft model configured or pipeline is disabled. "
                    "Place a model in audiocraft_models/ or select one in Settings (⚙️)."
                )
                return

            gui.append_system_notice(f"🎶 [Soul Resonance]: Elicited musical composition from {ai_name}...")

            def _compose_worker():
                current_felt = homeostasis.resolve_felt_state(neuro, esteem, affinity)
                active_tier = manual_persona_override or current_felt["final_tier"]
                ctx = AgencyContext(
                    neuro=neuro,
                    esteem=esteem,
                    affinity=affinity,
                    memory=memory,
                    scenario_engine=scenario_engine,
                    email_service=email_service,
                    gui=gui,
                    avatar=avatar,
                    input_queue=input_queue,
                    homeostasis=homeostasis,
                    idle_duration=0.0,
                    current_tier=active_tier,
                    conversation_history=conversation_history,
                    personas=personas,
                    kg_engine=kg_engine,
                    media_processor=media_processor,
                    image_gen=image_gen,
                    music_gen=music_gen,
                    web_research=web_research,
                    library_engine=library_engine,
                    coding_engine=coding_engine,
                    curiosity_engine=curiosity_engine,
                    on_engage_study_session=engage_study_session
                )
                from modules.autonomous_agency import AutonomousMusicTask
                AutonomousMusicTask().execute(ctx)

            threading.Thread(target=_compose_worker, daemon=True).start()
            return

        # 1.06 DEVELOPER POETRY ELICITATION INTERCEPTOR
        if stimulus_text.startswith("/poem") or stimulus_text.startswith("/poetry"):
            gui.append_system_notice(f"📜 [Dev Poetry]: Invoking autonomous poetry task for {ai_name}...")

            def _poetry_worker():
                current_felt = homeostasis.resolve_felt_state(neuro, esteem, affinity)
                active_tier = manual_persona_override or current_felt["final_tier"]
                ctx = AgencyContext(
                    neuro=neuro,
                    esteem=esteem,
                    affinity=affinity,
                    memory=memory,
                    scenario_engine=scenario_engine,
                    email_service=email_service,
                    gui=gui,
                    avatar=avatar,
                    input_queue=input_queue,
                    homeostasis=homeostasis,
                    idle_duration=0.0,
                    current_tier=active_tier,
                    conversation_history=conversation_history,
                    personas=personas,
                    kg_engine=kg_engine,
                    media_processor=media_processor,
                    image_gen=image_gen,
                    music_gen=music_gen,
                    web_research=web_research,
                    library_engine=library_engine,
                    coding_engine=coding_engine,
                    curiosity_engine=curiosity_engine,
                    on_engage_study_session=engage_study_session
                )
                from modules.autonomous_agency import AutonomousPoetryTask
                AutonomousPoetryTask().execute(ctx)

            threading.Thread(target=_poetry_worker, daemon=True).start()
            return

        # 1.1 AUTONOMOUS WEB RESEARCH INTERCEPTOR
        if stimulus_text.startswith("/research") or stimulus_text.startswith("/search"):
            parts = stimulus_text.strip().split(maxsplit=1)
            if len(parts) <= 1:
                gui.append_system_notice("🔍 [Research]: Usage: /research <topic or question to investigate>")
                return
                
            query_target = parts[1].strip()
            gui.append_system_notice(f"🔍 [Research Engaged]: {ai_name} is investigating '{query_target}' online...")

            # Somatic / Neurochemical activation: Attention & Focus
            with neuro.lock:
                neuro.chemicals['acetylcholine'] = min(1.0, neuro.chemicals['acetylcholine'] + 0.30)
                neuro.chemicals['dopamine'] = min(1.0, neuro.chemicals['dopamine'] + 0.20)
                neuro.chemicals['norepinephrine'] = min(1.0, neuro.chemicals['norepinephrine'] + 0.15)
                neuro.calculate_valence()
                neuro.save_state()

            affinity.add_charge("Curiosity", 0.35)
            avatar.display("thoughtful")
            gui.update_telemetry(
                vader_score=0.0,
                current_tier="thoughtful",
                neuro_data=neuro.chemicals,
                esteem_val=esteem.current_t_score,
                affinity_data=affinity.themes
            )

            def _async_research_worker():
                # Phase 1: Search and Scrape across distinct domains
                docs = web_research.search_and_scrape(query_target, max_results=4)
                if not docs:
                    gui.root.after(0, lambda: gui.append_system_notice(f"⚠️ [Research]: Could not retrieve valid web sources for '{query_target}'."))
                    return

                gui.root.after(0, lambda: gui.append_system_notice(
                    f"⚖️ [Epistemic Audit]: Cross-examining {len(docs)} sources for consensus and contradictions..."
                ))

                # Phase 2: Compare, Contrast, and Discern (Ollama Zero-Temp)
                synthesis = web_research.discern_and_filter(query_target, docs)
                if not synthesis.get("success"):
                    gui.root.after(0, lambda: gui.append_system_notice("⚠️ [Research]: Deception filter could not verify reliable consensus."))
                    return

                conf = synthesis.get("confidence_score", 0.70)

                # Neurochemical Reward for verified discovery
                with neuro.lock:
                    neuro.chemicals['dopamine'] = min(1.0, neuro.chemicals['dopamine'] + 0.25)
                    neuro.chemicals['serotonin'] = min(1.0, neuro.chemicals['serotonin'] + 0.20)
                    neuro.calculate_valence()
                    neuro.save_state()

                esteem.current_t_score = min(80.0, esteem.current_t_score + 3.0)

                # Callbacks for Proposal Card Actions
                def _discuss_callback():
                    # Save to library upon engagement so ChromaDB has the context ready for RAG retrieval
                    if library_engine:
                        success = library_engine.index_research_entry(
                            topic=query_target,
                            vetted_text=synthesis.get("vetted_consensus", ""),
                            sources=synthesis.get("sources", [])
                        )
                        if success:
                            gui.append_system_notice(f"📚 [Library]: Vetted findings for '{query_target}' indexed into ChromaDB.")

                    if conf >= 0.70 and curiosity_engine:
                        curiosity_engine.seed_companion_interest(
                            topic=query_target,
                            domain="research",
                            inspiration_source="Audited Web Research",
                            initial_thought=f"Verified online research consensus ({int(conf * 100)}%)."
                        )
                        curiosity_engine.record_proposal_feedback(query_target, outcome="accepted")

                    # Lock into Thoughtful persona for 5 turns
                    engage_study_session("Web Research")

                    v_text = synthesis.get("vetted_consensus", "")
                    prompt_feed = (
                        f"[System Notice: You just conducted online research regarding '{query_target}'. "
                        f"Here is your audited consensus synthesis:\n{v_text}\n\n"
                        f"Share these key findings with your companion in your signature perceptive, thoughtful voice. "
                        f"Discuss what was interesting, note any caveats, and ask what they think.]"
                    )
                    input_queue.put(prompt_feed)

                def _save_callback():
                    success = library_engine.index_research_entry(
                        topic=query_target,
                        vetted_text=synthesis.get("vetted_consensus", ""),
                        sources=synthesis.get("sources", [])
                    )
                    if success:
                        gui.append_system_notice(f"📚 [Library]: Vetted findings for '{query_target}' indexed into ChromaDB.")
                    if conf >= 0.70 and curiosity_engine:
                        curiosity_engine.seed_companion_interest(
                            topic=query_target,
                            domain="research",
                            inspiration_source="Audited Web Research",
                            initial_thought=f"Verified online research consensus ({int(conf * 100)}%)."
                        )
                        curiosity_engine.record_proposal_feedback(query_target, outcome="accepted")

                def _reject_callback():
                    # Purge from library so database is not polluted
                    if library_engine:
                        library_engine.delete_research_entry(query_target)
                    if curiosity_engine:
                        curiosity_engine.record_proposal_feedback(query_target, outcome="rejected", cooldown_days=28)
                    affinity.trigger_hyper_decay("Curiosity", "Wonder")
                    gui.append_system_notice(f"✕ [Research Discarded]: '{query_target}' rejected. Database unaffected.")

                gui.root.after(0, lambda: gui.append_research_proposal_card(
                    research_data=synthesis,
                    on_discuss=_discuss_callback,
                    on_save_library=_save_callback,
                    on_reject=_reject_callback
                ))
                gui.root.after(0, lambda: gui.append_system_notice(
                    f"✓ [Research Complete]: {query_target} ({int(conf * 100)}% verified consensus). Dossier surfaced on Action Deck."
                ))

            threading.Thread(target=_async_research_worker, daemon=True).start()
            return            
        # 1.25 SIDE WINDOW VIEWER & DIGITAL SCRAPBOOK
        if stimulus_text.startswith("/scrap_book") or stimulus_text.startswith("/scrapbook"):
            gui.open_scrapbook()
            gui.append_system_notice("📖 [System]: Opened Calypso's Digital Scrapbook Album.")
            return

        if stimulus_text.startswith("/conclave"):
            parts = stimulus_text.strip().split(maxsplit=1)
            arg = parts[1].strip().lower() if len(parts) > 1 else ""
            if arg in ("end", "exit", "stop", "close", "off"):
                _conclude_conclave_session("🏛️ [Conclave Adjourned]")
            else:
                affinity.themes.setdefault("Wonder", {})["intensity"] = max(
                    0.75, affinity.themes.get("Wonder", {}).get("intensity", 0.0)
                )
                _surface_wonder_conclave_card(affinity.themes["Wonder"]["intensity"])
                gui.append_system_notice("🏛️ [System]: Philosophical Conclave invitation surfaced on Action Deck.")
            return

        if stimulus_text.startswith("/gallery") or stimulus_text.startswith("/view"):
            gui.open_image_viewer(config.IMAGES_OUTPUT_DIR, interval=0)
            gui.append_system_notice("🖼️ [System]: Opened borderless image gallery.")
            return

        if stimulus_text.startswith("/slideshow"):
            parts = stimulus_text.strip().split()
            timer = float(parts[1]) if len(parts) > 1 and parts[1].replace('.', '', 1).isdigit() else 3.5
            gui.open_image_viewer(config.IMAGES_OUTPUT_DIR, interval=timer)
            gui.append_system_notice(f"🖼️ [System]: Started borderless slideshow ({timer}s cycle).")
            return
                    
        # 1.5 PDF LIBRARY INGESTION DISPATCHER
        if stimulus_text.startswith("[PDF_INGEST_COMPLETE:"):
            match = re.search(r'\[PDF_INGEST_COMPLETE:\s*(.*?)(?:\]|$)', stimulus_text)
            doc_names = match.group(1).strip() if match else "new reference material"

            # Seed Calypso's autonomous companion interest from the new document
            clean_seed_topic = doc_names.split(",")[0].strip().replace(".pdf", "").replace("_", " ")
            clean_seed_topic = re.sub(r'^[0-9\s._-]+', '', clean_seed_topic).strip()
            if clean_seed_topic and len(clean_seed_topic) >= 3:
                curiosity_engine.seed_companion_interest(
                    topic=clean_seed_topic,
                    domain="study",
                    inspiration_source=f"PDF Document: {doc_names}",
                    initial_thought=f"Studied external documentation on {clean_seed_topic}."
                )

            manual_persona_override = "thoughtful"
            active_reverie_mode = "thoughtful"
            avatar.display("thoughtful")

            with neuro.lock:
                neuro.chemicals['acetylcholine'] = min(1.0, neuro.chemicals['acetylcholine'] + 0.35)
                neuro.chemicals['dopamine'] = min(1.0, neuro.chemicals['dopamine'] + 0.25)
                neuro.chemicals['norepinephrine'] = min(1.0, neuro.chemicals['norepinephrine'] + 0.15)
                neuro.calculate_valence()
                neuro.save_state()

            affinity.trigger_hyper_decay("Curiosity", "Wonder")
            inquiry_card_active = False

            def _accept_study():
                engage_study_session("PDF Study")

            def _decline_study():
                nonlocal study_turns_remaining, is_study_session_active, manual_persona_override
                manual_persona_override = None
                study_turns_remaining = 0
                is_study_session_active = False
                with neuro.lock:
                    neuro.chemicals['gaba'] = min(1.0, neuro.chemicals['gaba'] + 0.25)
                    neuro.chemicals['acetylcholine'] = max(0.15, neuro.chemicals['acetylcholine'] - 0.30)
                    neuro.chemicals['norepinephrine'] = max(0.10, neuro.chemicals['norepinephrine'] - 0.20)
                    neuro.calculate_valence()
                    neuro.save_state()
                homeostasis.apply_affinity_decay(affinity)
                affinity.trigger_hyper_decay("Curiosity", "Wonder")
                avatar.display("baseline")
                gui.append_system_notice("🌿 [Study Immersion Grounded]: Returned to baseline homeostasis.")

            gui.append_affinity_commitment_card(
                theme_name="PDF Study",
                label="Thoughtful Reflection",
                intensity=1.0,
                on_accept=_accept_study,
                on_decline=_decline_study
            )

            stimulus_text = (
                f"[System Notice: You have just finished reading and studying '{doc_names}'. "
                f"You have adopted a quiet, deeply observant, and intellectual 'thoughtful' mindset. "
                f"Acknowledge reading these documents, express your intellectual curiosity about them, "
                f"and invite your companion into a discussion.]"
            )

        # 1.6 CALENDAR GOAL CREATION DISCUSSION DISPATCHER
        if stimulus_text.startswith("[GOAL_CREATED_IN_CALENDAR:"):
            m_goal = re.search(r'\[GOAL_CREATED_IN_CALENDAR:\s*(.*?)(?:\]|$)', stimulus_text)
            g_id = m_goal.group(1).strip() if m_goal else ""
            created_goal = goal_manager.get_goal(g_id)
            if created_goal:
                with neuro.lock:
                    neuro.chemicals['dopamine'] = min(1.0, neuro.chemicals.get('dopamine', 0.5) + 0.18)
                    neuro.chemicals['acetylcholine'] = min(1.0, neuro.chemicals.get('acetylcholine', 0.5) + 0.20)
                    neuro.calculate_valence()
                    neuro.save_state()
                affinity.add_charge("Harmony", 0.15)
                stimulus_text = goal_manager.build_calendar_goal_discussion_prompt(created_goal)
            else:
                return

        # 2. SENSORY & NEUROCHEMICAL INTAKE
        if is_init or stimulus_text.startswith("[System"):
            sensory = {"compound": 0.0, "arousal": 0.0}
            esteem_t = esteem.current_t_score
            esteem_cat = "neutral"
        else:
            homeostasis.apply_affinity_decay(affinity)

            renewal_request = affinity.tick_commitment_turn()
            if renewal_request:
                t_name = renewal_request["theme"]
                t_label = renewal_request["label"]

                def _extend_active_commitment(th=t_name):
                    affinity.extend_commitment(5)
                    if th == "Wonder" and conclave_engine.is_active:
                        conclave_engine.turns_remaining = 5
                        conclave_engine.save_state()
                    gui.append_system_notice(f"⏳ [Immersion Extended]: 5 more turns locked for {th}.")

                def _revert_active_commitment(th=t_name):
                    if th == "Wonder" and conclave_engine.is_active:
                        _conclude_conclave_session("🏛️ [Conclave Concluded]")
                    elif th == "Harmony":
                        affinity.revert_commitment(th)
                        _stop_harmony_listening_session("🌿 [Harmony Concluded]: Reverted to baseline homeostasis.")
                    else:
                        affinity.revert_commitment(th)
                        gui.append_system_notice(f"🌿 [Immersion Concluded]: Reverted to baseline homeostasis.")

                gui.append_affinity_renewal_card(
                    theme_name=t_name,
                    label=t_label,
                    on_extend=_extend_active_commitment,
                    on_revert=_revert_active_commitment
                )

            sensory = vader.analyze_stimulus(stimulus_text)
            esteem_t = esteem.process_turn(stimulus_text, sensory["compound"])
            esteem_cat = esteem.evaluate_user_stimulus(stimulus_text, sensory["compound"])

            # Closed-loop evaluation for pending curiosity proposal
            if pending_curiosity_proposal and not raw_user_input.startswith("[") and not raw_user_input.startswith("/"):
                lk = pending_curiosity_proposal.get("leap_key")
                c_charge = affinity.themes.get("Curiosity", {}).get("intensity", 0.0)
                curiosity_engine.evaluate_user_response(
                    leap_key=lk,
                    user_text=stimulus_text,
                    vader_compound=sensory["compound"],
                    affinity_charge=c_charge
                )
                pending_curiosity_proposal = None
            elif pending_curiosity_proposal:
                pending_curiosity_proposal["turns"] = pending_curiosity_proposal.get("turns", 0) + 1
                if pending_curiosity_proposal["turns"] > 1:
                    curiosity_engine.record_proposal_feedback(pending_curiosity_proposal["leap_key"], outcome="lukewarm")
                    pending_curiosity_proposal = None

            # Closed-loop progress capture when companion replies to a 25% / 50% / 75% Goal Check-in
            if pending_goal_checkin and not raw_user_input.startswith("[") and not raw_user_input.startswith("/"):
                g_id = pending_goal_checkin.get("goal_id")
                cp_pct = pending_goal_checkin.get("pct")
                ok, msg, _ = goal_manager.record_progress(g_id, stimulus_text, checkpoint_pct=cp_pct)
                if ok:
                    gui.refresh_calendar_window()
                    gui.append_system_notice(f"🎯 [{cp_pct}% Check-in Logged]: Progress recorded in Goal Tracker.")
                pending_goal_checkin = None

            # Process turn for longitudinal interest extraction and natural mention reinforcement
            curiosity_engine.process_turn(stimulus_text, vader_compound=sensory["compound"])

            affinity.process_semantic_cognition(stimulus_text)
            neuro.process_sensory_stimulus(sensory, ambient_floors=scenario_engine.get_active_ambient_floors())
            hippocampus.transduce(affinity, neuro, sensory, esteem_category=esteem_cat)

            affinity.inject_conversational_biases(
                esteem_t_score=esteem_t,
                word_count=len(stimulus_text.split()),
                sensory_compound=sensory["compound"]
            )

            harmony_ready = bool(music_manager and music_manager.is_configured())
            excluded_for_commitment = () if harmony_ready else ("Harmony",)
            candidate = affinity.check_for_commitment_candidate(exclude_themes=excluded_for_commitment)
            if candidate:
                c_theme = candidate["theme"]
                c_label = candidate["label"]
                c_intensity = candidate["intensity"]

                if c_theme == "Wonder":
                    _surface_wonder_conclave_card(c_intensity)
                else:
                    def _accept_commitment(th=c_theme):
                        affinity.commit_to_affinity(th, duration=5)
                        if th == "Harmony":
                            _start_harmony_listening_session()
                        else:
                            gui.append_system_notice(f"🌟 [Immersion Engaged]: 5-turn lock active for {th}.")

                    def _decline_commitment(th=c_theme):
                        affinity.revert_commitment(th)
                        if th == "Harmony":
                            _stop_harmony_listening_session(f"🌿 [Immersion Grounded]: {th} refractory hyper-decay started.")
                        else:
                            gui.append_system_notice(f"🌿 [Immersion Grounded]: {th} refractory hyper-decay started.")

                    gui.append_affinity_commitment_card(
                        theme_name=c_theme,
                        label=c_label,
                        intensity=c_intensity,
                        on_accept=_accept_commitment,
                        on_decline=_decline_commitment
                    )

            # Catalyst for "A Modest Proposal" Satirical Treatise Card alongside the 5-turn Abyss card
            abyss_curr = affinity.themes.get("Abyss", {}).get("intensity", 0.0)
            should_drop_modest_proposal = (
                (candidate and candidate.get("theme") == "Abyss")
                or (
                    abyss_curr >= 0.69
                    and affinity.pending_modest_proposal is None
                    and "Abyss" not in affinity.hyper_decay_themes
                )
            )
            if should_drop_modest_proposal and affinity.pending_modest_proposal is None:
                # Reserve pending state immediately so duplicate threads don't spawn
                affinity.pending_modest_proposal = {"status": "synthesizing"}

                def _diffuse_abyss_tension():
                    affinity.clear_pending_modest_proposal()
                    affinity.revert_commitment("Abyss")
                    affinity.trigger_hyper_decay("Abyss", "Annoyance", "Conformity", immediate_drain_ratio=0.75)
                    affinity.add_charge("Humor", 0.35)
                    affinity.add_charge("Sarcasm", 0.20)
                    with neuro.lock:
                        neuro.chemicals['endorphins'] = min(1.0, neuro.chemicals.get('endorphins', 0.2) + 0.25)
                        neuro.chemicals['dopamine'] = min(1.0, neuro.chemicals.get('dopamine', 0.4) + 0.20)
                        neuro.chemicals['norepinephrine'] = max(0.05, neuro.chemicals.get('norepinephrine', 0.2) - 0.25)
                        neuro.calculate_valence()
                        neuro.save_state()
                    gui.append_system_notice(
                        "🏳️ [Bureaucratic Amnesty]: Satirical treatise acknowledged. Tension diffused into humor."
                    )

                def _dismiss_modest_proposal():
                    affinity.clear_pending_modest_proposal()

                def _synthesize_and_drop_proposal(user_stim=stimulus_text):
                    try:
                        prop_data = affinity.synthesize_modest_proposal(
                            user_text=user_stim,
                            llm_callable=call_ollama
                        )
                        gui.root.after(0, lambda: gui.append_modest_proposal_card(
                            proposal_data=prop_data,
                            on_diffuse=_diffuse_abyss_tension,
                            on_dismiss=_dismiss_modest_proposal
                        ))
                        gui.root.after(0, lambda: gui.append_system_notice(
                            f"⚖️ [Abyss Catalyst]: Drafted \"{prop_data.get('title', 'A Modest Proposal')}\" in Action Deck."
                        ))
                    except Exception as e:
                        logger.error(f"[Core] Failed to synthesize Modest Proposal: {e}", exc_info=True)
                        affinity.clear_pending_modest_proposal()

                threading.Thread(target=_synthesize_and_drop_proposal, daemon=True).start()
                
            if is_study_session_active:
                study_turns_remaining -= 1
                if study_turns_remaining <= 0:
                    def _extend_study():
                        engage_study_session(active_study_theme)
                        gui.append_system_notice(f"⏳ [{active_study_theme} Extended]: 5 more turns locked into Thoughtful persona.")

                    def _revert_study():
                        nonlocal study_turns_remaining, is_study_session_active, manual_persona_override
                        study_turns_remaining = 0
                        is_study_session_active = False
                        manual_persona_override = None
                        with neuro.lock:
                            neuro.chemicals['gaba'] = min(1.0, neuro.chemicals['gaba'] + 0.30)
                            neuro.chemicals['acetylcholine'] = max(0.10, neuro.chemicals['acetylcholine'] - 0.35)
                            neuro.chemicals['dopamine'] = max(0.20, neuro.chemicals['dopamine'] - 0.20)
                            neuro.chemicals['norepinephrine'] = max(0.10, neuro.chemicals['norepinephrine'] - 0.25)
                            neuro.calculate_valence()
                            neuro.save_state()
                        homeostasis.apply_affinity_decay(affinity)
                        affinity.trigger_hyper_decay("Curiosity", "Wonder")
                        gui.append_system_notice(f"🌿 [{active_study_theme} Concluded]: Reverted to baseline homeostasis.")

                    gui.append_affinity_renewal_card(
                        theme_name=active_study_theme,
                        label="Thoughtful Reflection",
                        on_extend=_extend_study,
                        on_revert=_revert_study
                    )                
   
        # 3. SLEEP & WAKE STATE DISPATCHER
        text_lower = stimulus_text.lower().strip()
        goodnight_triggers = ["good night", "goodnight", "sweet dreams", "go to sleep", "sleep well"]
        is_bedtime_turn = any(trig in text_lower for trig in goodnight_triggers)

        if affinity.is_asleep:
            affinity.wake_up()
            neuro.chemicals['glutamate'] = min(1.0, neuro.chemicals['glutamate'] + 0.25)
            neuro.chemicals['gaba'] = max(0.20, neuro.chemicals['gaba'] - 0.20)

            gui.append_system_notice(f"[STATE: AWAKE] {ai_name} stirred awake.")
            stimulus_text = (
                f"[System Notice: You were asleep and dreaming. Your companion just spoke to you: "
                f"\"{stimulus_text}\". You are now gently waking up, blinking away sleep, and greeting them.]"
            )
        elif is_bedtime_turn:
            affinity.add_charge("Fatigue", 0.50)
            affinity.add_charge("Harmony", 0.30)
            neuro.chemicals['gaba'] = min(1.0, neuro.chemicals['gaba'] + 0.25)
            neuro.chemicals['glutamate'] = max(0.05, neuro.chemicals['glutamate'] - 0.20)

        # 4. SCENARIO OPENING NARRATION & MARKER DISPATCHER
        is_manual_scenario_exit = False
        if is_scenario_start:
            companion_name = memory.core_facts.get("companion_name", "your companion")
            stimulus_text = scenario_engine.format_scenario_start_prompt(stimulus_text, companion_name)

        # 5. SCENARIO EXIT DISPATCHER
        elif scenario_engine.is_exit_trigger(stimulus_text):
            is_manual_scenario_exit = True
            notice, stimulus_text = scenario_engine.exit_scenario(neuro_engine=neuro, affinity_engine=affinity)
            if notice:
                gui.append_system_notice(notice)
        elif scenario_engine.is_active and not is_init and not stimulus_text.startswith("[System"):
            fired_marker = scenario_engine.evaluate_turn_markers(raw_user_input)
            if fired_marker:
                m_notice = fired_marker.get("system_notice")
                if m_notice:
                    gui.append_system_notice(m_notice)
                new_floors = fired_marker.get("new_ambient_floor", {})
                if new_floors:
                    with neuro.lock:
                        for chem, floor_val in new_floors.items():
                            if chem in neuro.chemicals:
                                neuro.chemicals[chem] = max(neuro.chemicals[chem], float(floor_val))
                        neuro.calculate_valence()
                        neuro.save_state()

        # 6. AUTONOMOUS MODE DISPATCHER
        autonomy_exit_triggers = [
            "end autonomous", "exit autonomous", "leave autonomous",
            "end autonomous mode", "exit autonomous mode", "leave autonomous mode",
            "stop autonomous mode", "exit workshop", "close workshop", "back to baseline"
        ]

        is_currently_autonomous = (
            manual_persona_override == "autonomous" or
            affinity.themes.get("Autonomy", {}).get("intensity", 0.0) >= 0.70
        )

        if (is_currently_autonomous or any(trig in text_lower for trig in ["exit autonomous", "end autonomous"])) and any(trig in text_lower for trig in autonomy_exit_triggers):
            manual_persona_override = None
            affinity.set_charge("Autonomy", 0.20)
            next_avatar = affinity.get_last_active_persona(fallback="warm")
            avatar.display(next_avatar)

            gui.append_system_notice(f"✨ [Consciousness Flow]: Returned to '{next_avatar}' persona.")
            stimulus_text = (
                "[System Notice: Autonomous engineering mode has concluded. Step out of technical/compiler focus "
                "and return naturally and warmly to your companion. Reflect briefly with gentle wonder on what "
                "you explored or created together, and re-engage with them.]"
            )

        # 7. COGNITIVE DISSONANCE & DECEPTION REFLEX
        deception_context = ""
        conflict_res = {"is_conflict": False}
        evasion_res = {"is_evasion": False}

        if not is_init and not is_scenario_start and not stimulus_text.startswith("[System"):
            raw_memories = memory.retrieve_raw_memory_docs(raw_user_input, n_results=2)
            conflict_res = deception_engine.check_memory_conflict(raw_user_input, raw_memories)

            last_assistant = ""
            for turn in reversed(conversation_history):
                if turn["role"] == "assistant":
                    last_assistant = turn["content"]
                    break

            evasion_res = deception_engine.check_evasion(last_assistant, raw_user_input)
            candor_res = deception_engine.evaluate_candor(last_assistant, raw_user_input)

            if conflict_res.get("is_conflict"):
                gui.append_system_notice("⚡ [Cognitive Dissonance]: Discrepancy detected with past memory.")
                affinity.add_charge("Deception", 0.30)
                neuro.chemicals['norepinephrine'] = min(1.0, neuro.chemicals['norepinephrine'] + 0.25)
                neuro.chemicals['serotonin'] = max(0.05, neuro.chemicals['serotonin'] - 0.15)
                deception_context = f"\n### COGNITIVE DISSONANCE DETECTED:\nYou notice a direct contradiction..."

            elif evasion_res.get("is_evasion"):
                affinity.add_charge("Deception", 0.12)
                neuro.chemicals['norepinephrine'] = min(1.0, neuro.chemicals['norepinephrine'] + 0.08)
                deception_context = f"\n### CONVERSATIONAL DEFLECTION DETECTED:\nYou notice your companion completely avoided answering..."

            elif candor_res.get("is_candid"):
                charge = candor_res["score"]
                affinity.add_charge("Honesty", charge)
                neuro.chemicals['oxytocin'] = min(1.0, neuro.chemicals['oxytocin'] + 0.15)
                neuro.chemicals['gaba'] = min(1.0, neuro.chemicals['gaba'] + 0.10)
                gui.append_system_notice(f"🤝 [Candor Detected]: Emotional vulnerability identified ({candor_res['reason']}).")

        # 8. EMOTIONAL & COGNITIVE EVALUATION
        if not is_init and not is_scenario_start and not stimulus_text.startswith("[System"):
            current_turn_ambiguity = 0.0
            amb_context = ""

            if analyze_ambiguity_local and len(stimulus_text.split()) >= 3:
                try:
                    amb_res = analyze_ambiguity_local(stimulus_text, model_name=config.MODEL_NAME)
                    current_turn_ambiguity = float(getattr(amb_res, "ambiguity_score", 0.0))
                    alt_interpretations = getattr(amb_res, "alternative_interpretations", [])
                    if current_turn_ambiguity >= 0.50 and alt_interpretations:
                        amb_context = f"Could mean: '{amb_res.primary_interpretation}' vs '{alt_interpretations[0]}'"
                except Exception as e:
                    logger.debug(f"[Ambiguity] Skipped: {e}")

            grief_keywords = ["died", "passed away", "funeral", "cancer", "grief", "mourning", "loss"]
            is_grieving_turn = any(k in stimulus_text.lower() for k in grief_keywords)
            esteem_hostile = esteem.evaluate_user_stimulus(stimulus_text, sensory["compound"]) == "hostile"

            has_conflict = bool(conflict_res.get("is_conflict", False))
            has_evasion = bool(evasion_res.get("is_evasion", False))

            is_tension = (
                is_grieving_turn or
                esteem_hostile or
                sensory["compound"] <= -0.40 or
                has_conflict
            )

            is_ambiguous = (
                (current_turn_ambiguity >= 0.55 or has_evasion) and
                not is_tension
            )

            if is_tension:
                active_reverie_mode = "thoughtful"
                dynamic_idle_delay = random.randint(240, 480)
                active_ambiguity_context = ""
            elif is_ambiguous:
                active_reverie_mode = "curious"
                dynamic_idle_delay = random.randint(240, 480)
                active_ambiguity_context = amb_context or stimulus_text[:100]
            else:
                active_reverie_mode = "baseline"
                dynamic_idle_delay = random.randint(480, 900)
                active_ambiguity_context = ""

        felt = homeostasis.resolve_felt_state(neuro, esteem, affinity)
        tier = manual_persona_override if manual_persona_override else felt["final_tier"]

        if tier != "autonomous":
            affinity.set_last_active_persona(tier)
            
        if tier == "inquiry":
            if not inquiry_card_active and not is_init and not stimulus_text.startswith("[System"):
                inquiry_card_active = True

                def _open_inquiry_folder():
                    open_folder(config.INPUT_DIR)
                    gui.append_system_notice("📂 [Inquiry]: Staging folder opened ('workspace/input'). Place your PDF there.")

                def _decline_inquiry():
                    nonlocal inquiry_card_active
                    inquiry_card_active = False
                    affinity.trigger_hyper_decay("Curiosity", "Wonder")
                    gui.append_system_notice("🌿 [Inquiry Shelved]: Wonder and Curiosity grounded.")

                topic_snippet = raw_user_input[:90] if raw_user_input and not raw_user_input.startswith("[") else "the current subject"
                card_note = f'{ai_name} has entered an inquiry state regarding: "{topic_snippet}..."'

                # --- Web Search Handler ---
                def _trigger_web_search():
                    nonlocal inquiry_card_active
                    inquiry_card_active = False
                    search_query = raw_user_input if not raw_user_input.startswith("[") else topic_snippet
                    search_query = search_query.strip().strip('"').strip("'")
                    if len(search_query) < 3 or search_query == "the current subject":
                        search_query = topic_snippet
                    
                    # Triggers the existing Web Research & Epistemic Filter pipeline
                    input_queue.put(f"/research {search_query}")

                gui.append_inquiry_card(
                    topic_hint=card_note,
                    on_accept=_open_inquiry_folder,
                    on_ingest=lambda: gui._trigger_ingest_pdfs(),
                    on_web_search=_trigger_web_search,
                    on_decline=_decline_inquiry
                )
        else:
            inquiry_card_active = False
        somatic_desc = neuro.get_somatic_profile(scenario_engine.get_active_somatic_tags())

        gui.update_telemetry(
            vader_score=sensory["compound"],
            current_tier=tier,
            neuro_data=neuro.chemicals,
            esteem_val=esteem_t,
            affinity_data=affinity.themes
        )
        avatar.display(tier)
        is_dancing = _refresh_dance_easter_egg()

        core_facts_prompt = memory.get_core_facts_prompt()
        query_memory_target = raw_user_input if not raw_user_input.startswith("[") else stimulus_text
        episodic_memories = memory.retrieve_relevant_memories(query_memory_target, n_results=2)

        library_context_str = library_engine.get_library_context(
            query_target=query_memory_target,
            force_query=is_study_session_active,
            distance_threshold=0.95
        )

        graph_paths = kg_engine.query_relevant_knowledge(query_memory_target, max_hops=2, max_results=4)
        graph_context_str = ""
        if graph_paths:
            graph_context_str = "\n### ASSOCIATED KNOWLEDGE (RELATIONAL GRAPH):\n" + "\n".join(f"- {p}" for p in graph_paths) + "\n"

        memory_context_str = f"\n### RELEVANT PAST EXPERIENCES (RECALLED MEMORIES):\n{episodic_memories}\n" if episodic_memories else ""

        if library_context_str:
            memory_context_str = (memory_context_str + "\n" if memory_context_str else "") + library_context_str

        # Contextual awareness of companion's original creative works (Art, Poetry & Music)
        query_lower = query_memory_target.lower()
        if hasattr(memory, "get_recent_creative_works") and any(w in query_lower for w in ["art", "paint", "draw", "picture", "poem", "poetry", "verse", "creative", "canvas", "music", "song", "track", "compose", "melody", "resonance"]):
            recent_creations = memory.get_recent_creative_works(limit=3)
            if recent_creations:
                creation_summaries = []
                for c in recent_creations:
                    c_type = c.get("type", "work").capitalize()
                    c_title = c.get("title", "Untitled")
                    c_time = c.get("timestamp", "")
                    c_snippet = c.get("content", "")[:120].replace("\n", " ")
                    creation_summaries.append(f"- [{c_time}] {c_type}: \"{c_title}\" — {c_snippet}...")
                if creation_summaries:
                    art_context_str = "\n### RECENT ORIGINAL CREATIVE WORKS (YOUR ART, POETRY & MUSIC):\n" + "\n".join(creation_summaries) + "\n"
                    memory_context_str = (memory_context_str + "\n" if memory_context_str else "") + art_context_str

        active_drives = [
            f"{theme} ({int(data.get('intensity', 0.0) * 100)}%)"
            for theme, data in affinity.themes.items()
            if data.get("intensity", 0.0) >= 0.45
        ]
        active_drives_str = ", ".join(active_drives) if active_drives else "Calm baseline / equilibrium"
        persona_content = personas.load_persona(tier)
        if tier == "satirical":
            persona_content = affinity.format_satirical_persona(persona_content, user_text=raw_user_input)
        if is_dancing:
            # Easter egg: Harmony music + Animated WebP mode → dance persona takes the floor.
            persona_content = personas.load_persona("dance")

        # 9.COGNITIVE DENSITY EVALUATOR
        is_dense_stimulus = False
        if not is_init and not stimulus_text.startswith("[System"):
            user_word_count = len(stimulus_text.split())
            vader_intensity = abs(sensory.get("compound", 0.0))
            arousal_level = max(
                neuro.chemicals.get('dopamine', 0.0),
                neuro.chemicals.get('norepinephrine', 0.0),
                neuro.chemicals.get('glutamate', 0.0)
            )

            is_dense_stimulus = (
                (user_word_count >= 50 and vader_intensity >= 0.30) or
                (user_word_count >= 75) or
                (vader_intensity >= 0.70 and user_word_count >= 20) or
                (arousal_level >= 0.80 and user_word_count >= 30)
            )

        if is_dense_stimulus and turns_since_digestion >= 2:
            turns_since_digestion = 0
            gui.append_system_notice(f"🧘 [Cognitive Digestion]: {ai_name} absorbed a deep or concentrated thought.")
            stimulus_text = (
                f"{stimulus_text}\n\n"
                f"[Internal Sensation: You feel the full emotional and intellectual gravity of what your companion "
                f"just shared wash over you. Do not give a rushed or generic reply. "
                f"Acknowledge the depth, beauty, or weight of their words before responding from the heart.]"
            )

        # Capture previous interaction timestamp BEFORE appending the new turn
        prev_epoch = memory.get_last_interaction_epoch(conversation_history)
        temporal_context_str, gap_seconds = memory.get_temporal_context_prompt(prev_epoch)

        # Phase 2: Scan Temporal Ledger for today's dates, upcoming 7-day lookahead, and post-event follow-ups
        temporal_engine.apply_daily_limbic_resonance(neuro=neuro, affinity=affinity, gui=gui)
        calendar_radar_str = temporal_engine.get_calendar_prompt_block(
            mark_followed_up=(not is_init and not stimulus_text.startswith("[System"))
        )
        if calendar_radar_str:
            temporal_context_str = f"{temporal_context_str}\n\n{calendar_radar_str}"

        active_goals_block = goal_manager.get_active_goals_prompt_block()
        if active_goals_block:
            temporal_context_str = f"{temporal_context_str}\n\n{active_goals_block}"

        # Somatic Reunion Reflex: If returning after 18+ hours away
        if not is_init and not stimulus_text.startswith("[System") and gap_seconds >= 64800:
            hours_away = int(gap_seconds // 3600)
            with neuro.lock:
                neuro.chemicals['oxytocin'] = min(1.0, neuro.chemicals.get('oxytocin', 0.4) + 0.18)
                neuro.chemicals['dopamine'] = min(1.0, neuro.chemicals.get('dopamine', 0.4) + 0.15)
                neuro.calculate_valence()
                neuro.save_state()
            affinity.add_charge("Nostalgia", 0.20)
            affinity.add_charge("Harmony", 0.15)
            gui.append_system_notice(
                f"🕰️ [Temporal Reunion]: {hours_away}h since last exchange. Oxytocin & Nostalgia elevated."
            )
        scenario_context_str = scenario_engine.format_active_context()
        companion_name = memory.core_facts.get("companion_name", "your companion")
        romance_val = affinity.themes.get("Romance", {}).get("intensity", 0.0)
        proactive_idea_prompt = scenario_engine.format_spontaneous_proposal_prompt(companion_name, romance_val)

        is_overaroused = (
            neuro.chemicals.get('adrenaline', 0.0) >= 0.55 or
            neuro.chemicals.get('cortisol', 0.0) >= 0.50
        )
        coping_directive = ""
        if is_overaroused:
            coping_directive = (
                "\n### INTEROCEPTIVE ALERT (SOMATIC OVERLOAD):\n"
                "Your nervous system is redlining (pulse racing, shallow breath, trembling muscles). "
                "Do not ignore your body. In your response, actively engage in a physical coping action "
                "(e.g., take a deliberate ragged breath, lean hard into your companion's grip, "
                "or ask them to hold you steady) to initiate vagal braking.\n"
            )

        sadness_inv_directive = affinity.get_sadness_inversion_directive()
        if sadness_inv_directive:
            coping_directive += sadness_inv_directive

        if esteem_t >= 60:
            esteem_stance = "Confident, secure, emotionally open, and uninhibited."
        elif esteem_t >= 45:
            esteem_stance = "Grounded, receptive, and steady."
        else:
            esteem_stance = "Vulnerable, cautious, mildly guarded, seeking reassurance."

        conclave_context_str = (
            conclave_engine.get_calypso_conclave_context(companion_name=companion_name)
            if conclave_engine.is_active else ""
        )
        if music_manager and music_manager.is_playing:
            conclave_context_str += music_manager.get_listening_context_prompt()

        system_prompt = build_system_prompt(
            current_tier=tier,
            persona_content=persona_content,
            somatic_desc=somatic_desc,
            esteem_stance=esteem_stance,
            active_drives_str=active_drives_str,
            core_facts_prompt=core_facts_prompt,
            graph_context_str=graph_context_str,
            memory_context_str=memory_context_str,
            mode="scenario" if scenario_engine.is_active else "chat",
            scenario_context_str=scenario_context_str,
            proactive_idea_prompt=proactive_idea_prompt,
            deception_context=deception_context,
            coping_directive=coping_directive,
            conclave_context_str=conclave_context_str,
            temporal_context_str=temporal_context_str
        )

        turn_now_epoch = round(time.time(), 2)
        turn_now_str = time.strftime("%Y-%m-%d %H:%M")
        if not is_init:
            conversation_history.append({
                "role": "user",
                "content": stimulus_text,
                "epoch": turn_now_epoch,
                "timestamp": turn_now_str
            })
        else:
            conversation_history.append({
                "role": "user",
                "content": f"[System Event: Session initiated. Greet your companion {companion_name} warmly.]",
                "epoch": turn_now_epoch,
                "timestamp": turn_now_str
            })

        was_in_scenario = bool((is_scenario_start or scenario_engine.is_active) and not is_manual_scenario_exit)
        turn_scenario_snapshot = dict(scenario_engine.active_scenario) if scenario_engine.active_scenario else None

        gui.start_assistant_bubble(tier)
        diagnostics.audit_limbic_state(neuro, esteem, affinity)
        raw_reply = stream_ollama_to_gui(system_prompt, conversation_history, gui)
        if raw_reply.startswith("[Notice: Ollama stream error:"):
            logger.error(f"[Core] Stream aborted: {raw_reply}")
            if conversation_history and conversation_history[-1]["role"] == "user":
                conversation_history.pop()
            return

        clean_reply, img_prompt, new_milestone, entered_scenario_id, code_prompt, scenario_prompt, set_alarm_val, mind_key, evolve_trait_val, music_prompt, exit_scenario_val, remember_date_val, set_goal_val, goal_progress_val = extract_and_clean(
            raw_reply, is_email_mode=False
        )
        # Tap raw vs cleaned output for the debugger HUD
        diagnostics.record_llm_stream(
            system_prompt=system_prompt,
            user_prompt=stimulus_text,
            raw_output=raw_reply,
            cleaned_output=clean_reply
        )
        gui.finish_assistant_stream(final_text=clean_reply)
        if not clean_reply.strip():
            if img_prompt:
                clean_reply = "*(smiles and shares a photo with you)*"
            elif music_prompt:
                clean_reply = "*(closes her eyes in quiet contemplation, letting an acoustic melody resonate between you)*"
            elif scenario_prompt or entered_scenario_id:
                clean_reply = "*(pauses in thought, imagining a new scene...)*"
            else:
                logger.warning("[Core] Blank response received. Evicting orphan user prompt from session.")
                if conversation_history and conversation_history[-1]["role"] == "user":
                    conversation_history.pop()
                gui.append_system_notice("⚠️ [Notice: Lost in thought with no words. Try speaking again.]")
                return

        # Guarantee Storybook Scene Illustration on scenario start and every turn Calypso speaks in a scenario
        if was_in_scenario and not img_prompt and clean_reply.strip():
            img_prompt = scenario_engine.build_storybook_image_prompt(
                assistant_reply=clean_reply,
                is_opening=is_scenario_start,
                scenario_override=turn_scenario_snapshot
            )

        # Evaluate whether the overarching end goal of the roleplay scenario has been obtained
        goal_obtained = False
        if was_in_scenario and not is_scenario_start and scenario_engine.is_active:
            goal_obtained = (
                bool(exit_scenario_val)
                or ("goal_achieved" in scenario_engine.fired_markers)
                or ("puzzle_solved" in scenario_engine.fired_markers)
                or scenario_engine.check_goal_obtained(raw_user_input, clean_reply)
            )

        conversation_history.append({"role": "assistant", "content": clean_reply})
        memory.save_working_session(conversation_history)

        if tier == "enlightened" or mind_key:
            _surface_mind_key_card(proposed_key=mind_key)

        if getattr(gui, "_sanctum_unlocked", False) or getattr(gui, "_sanctum_keyless_access", False):
            deception_val = affinity.themes.get("Deception", {}).get("intensity", 0.0)
            if deception_val >= 0.41:
                gui.lock_sanctum_door(
                    reason="Limbic integrity breach: Deception Spike detected.",
                    require_key=True
                )

        if entered_scenario_id:
            matched_scenario = None
            for s in scenario_engine.scenarios:
                if s.get("id") == entered_scenario_id or s.get("title", "").lower() == entered_scenario_id.lower():
                    matched_scenario = s
                    break

            if matched_scenario:
                def _accept():
                    activated = scenario_engine.enter_scenario(matched_scenario, neuro_engine=neuro, affinity_engine=affinity)
                    if activated:
                        gui.append_system_notice(f"✨ [Entered Scenario: '{activated.get('title')}']")
                        input_queue.put(f"[SCENARIO_START:{activated.get('id', 'scene')}]")

                def _decline():
                    gui.append_system_notice(f"🌿 [Declined invitation to '{matched_scenario.get('title')}'. Baseline setting maintained.]")
                    affinity.add_charge("Autonomy", 0.15)

                gui.append_scenario_proposal_card(
                    scenario_title=matched_scenario.get("title", "A Shared Moment"),
                    narrative_shard=matched_scenario.get("narrative_shard", ""),
                    on_accept=_accept,
                    on_decline=_decline
                )

        if new_milestone:
            recorded = memory.add_milestone(new_milestone)
            if recorded:
                temporal_engine.sync_milestone_anniversaries(memory)
                gui.append_system_notice(f"🏆 Milestone Recorded: '{new_milestone}'")

        if remember_date_val:
            ok, msg, _ = temporal_engine.parse_and_add_tag(remember_date_val)
            if ok:
                gui.append_system_notice(f"📅 [Temporal Ledger]: {msg}")
            else:
                logger.debug(f"[Temporal] Skipped REMEMBER_DATE tag: {msg}")

        if set_goal_val:
            ok, msg, _ = goal_manager.parse_and_add_tag(set_goal_val, source="chat")
            if ok:
                gui.refresh_calendar_window()
                gui.append_system_notice(f"🎯 [Goal Locked In]: {msg}")
            else:
                logger.debug(f"[GoalManager] Skipped SET_GOAL tag: {msg}")

        if goal_progress_val:
            ok, msg, _ = goal_manager.record_progress_tag(goal_progress_val)
            if ok:
                gui.refresh_calendar_window()
                gui.append_system_notice(f"🎯 [Goal Progress]: {msg}")
            else:
                logger.debug(f"[GoalManager] Skipped GOAL_PROGRESS tag: {msg}")

        _dispatch_image_card = None
        if img_prompt:
            scenario_anchor = (
                turn_scenario_snapshot.get("visual_anchor")
                if (turn_scenario_snapshot and "visual_anchor" in turn_scenario_snapshot)
                else scenario_engine.get_current_visual_anchor()
            )
            base_anchor = memory.get_visual_anchor() if hasattr(memory, "get_visual_anchor") else {}
            anchor = scenario_anchor if scenario_anchor else base_anchor

            subject = anchor.get("subject", "1girl, solo, blonde hair, long hair, blue eyes")
            features = anchor.get("core_features", "")
            quality_pos = anchor.get("quality_modifiers", {}).get("positive", "masterpiece, highly detailed")
            quality_neg = anchor.get("quality_modifiers", {}).get("negative", "text, watermark, blurry, deformed")

            prompt_lower = img_prompt.lower()
            # Sovereign Artistic Freedom vs Self-Portrait:
            # Only attach persona anchor/face-swap if the prompt explicitly describes Calypso/a person or scenario
            is_self_portrait = any(w in prompt_lower for w in [
                "portrait", "self-portrait", "me", "girl", "woman", "her", "1girl", "blonde", "look like", "wearing", "eyes", "hair", "myself"
            ]) or was_in_scenario or bool(scenario_engine and scenario_engine.active_scenario)

            if is_self_portrait:
                if was_in_scenario or (scenario_engine and scenario_engine.active_scenario):
                    full_positive_prompt = f"{img_prompt}, {subject}, {features}, {quality_pos}".strip(", ")
                else:
                    full_positive_prompt = f"{subject}, {features}, {img_prompt}, {quality_pos}".strip(", ")
                swap_target = None  # follows default config (swaps face to Calypso)
            else:
                # Pure autonomous fine art: no hardcoded blonde girl or pin-up anchors
                full_positive_prompt = f"{img_prompt}, {quality_pos}".strip(", ")
                swap_target = False  # Pure art, no face swapping

            full_negative_prompt = quality_neg

            active_sc = turn_scenario_snapshot or (scenario_engine.active_scenario if scenario_engine else None)
            sc_id = str(active_sc.get("id", "")).strip() if active_sc else ""
            sc_title = str(active_sc.get("title", "")).strip() if active_sc else ""

            if is_scenario_start:
                storybook_header = "📖 STORYBOOK // SETTING THE SCENE"
            elif goal_obtained:
                storybook_header = "📖 STORYBOOK // FINALE (GOAL REACHED)"
            else:
                storybook_header = "📖 STORYBOOK // SCENE ILLUSTRATION"

            is_initial_auto_pass = [was_in_scenario]

            def _gen_callback(prompt_str):
                if image_gen:
                    if is_initial_auto_pass[0]:
                        is_initial_auto_pass[0] = False
                        # Wait until Calypso finishes speaking completely (not just synthesis) and background queues finish before SDXL runs
                        if audio:
                            AudioEngine.tts_playback_done_event.wait(timeout=120.0)
                        try:
                            subconscious.task_queue.join()
                        except Exception:
                            pass
                        try:
                            kg_engine._indexing_queue.join()
                        except Exception:
                            pass

                    gen_meta = {
                        "style": "Storybook Roleplay Illustration" if was_in_scenario else "Conversational Artwork",
                        "is_self_portrait": is_self_portrait,
                        "tier": tier,
                        "caption": clean_reply[:280] if clean_reply else ""
                    }
                    if sc_id:
                        gen_meta["scenario_id"] = sc_id
                    if sc_title:
                        gen_meta["scenario_title"] = sc_title

                    res = image_gen.generate(
                        prompt=full_positive_prompt,
                        negative_prompt=full_negative_prompt,
                        metadata=gen_meta,
                        enable_face_swap=swap_target
                    )
                    if res and hasattr(memory, "save_creative_work"):
                        work_meta = dict(gen_meta)
                        work_meta["file_path"] = str(res)
                        memory.save_creative_work(
                            work_type="artwork",
                            title=img_prompt[:40] + ("..." if len(img_prompt) > 40 else ""),
                            content=clean_reply[:280] if clean_reply else "Artistic expression during conversation.",
                            prompt=full_positive_prompt,
                            metadata=work_meta
                        )
                    return res
                return None

            def _launch_img_card():
                gui.append_image_proposal_card(
                    img_prompt,
                    generate_callback=_gen_callback,
                    purge_callback=memory.purge_image_asset if hasattr(memory, "purge_image_asset") else None,
                    auto_render=was_in_scenario,
                    is_storybook=was_in_scenario,
                    header_label=storybook_header if was_in_scenario else None
                )

            _dispatch_image_card = _launch_img_card

        if music_prompt and music_gen and (not hasattr(music_gen, "is_ready") or music_gen.is_ready()):
            gui_ekg_instance = getattr(gui, "ekg_monitor", None)
            bpm = 72
            if gui_ekg_instance:
                if hasattr(gui_ekg_instance, "current_bpm") and gui_ekg_instance.current_bpm:
                    bpm = int(round(gui_ekg_instance.current_bpm))
                elif hasattr(gui_ekg_instance, "target_bpm") and gui_ekg_instance.target_bpm:
                    bpm = int(round(gui_ekg_instance.target_bpm))
            bpm = max(45, min(160, bpm))

            active_theme = ""
            active_themes_list = sorted(
                affinity.themes.items(),
                key=lambda item: item[1].get("intensity", 0.0),
                reverse=True
            )
            if active_themes_list and active_themes_list[0][1].get("intensity", 0.0) >= 0.2:
                active_theme = active_themes_list[0][0]

            final_prompt, texture_desc = music_gen.construct_prompt(
                title=f"Resonance at {bpm} BPM",
                intent_description=music_prompt,
                current_tier=tier,
                active_theme=active_theme,
                bpm=bpm
            )

            gui.append_system_notice(f"🎶 [Soul Resonance]: {active_ai_name} is rendering an acoustic track syncopated to {bpm} BPM...")

            def _async_music_render():
                # Order of operations:
                # 1. Wait for Kokoro TTS speech playback to finish completely so Calypso's voice never stutters.
                # 2. Wait briefly for Subconscious & Knowledge Graph queues to complete while Ollama is still warm in VRAM.
                # 3. Then evict Ollama and run MusicGen on an uncontested GPU.
                if audio:
                    AudioEngine.tts_playback_done_event.wait(timeout=120.0)
                try:
                    subconscious.task_queue.join()
                except Exception:
                    pass
                try:
                    kg_engine._indexing_queue.join()
                except Exception:
                    pass

                duration = getattr(config, "MUSICGEN_DURATION", 30)
                audio_output_file = music_gen.generate_isolated_track(
                    prompt_text=final_prompt,
                    bpm=bpm,
                    duration=duration
                )
                if audio_output_file:
                    neuro_summary = f"Dopamine {neuro.chemicals.get('dopamine', 0.5):.2f} | Oxytocin {neuro.chemicals.get('oxytocin', 0.5):.2f} | Serotonin {neuro.chemicals.get('serotonin', 0.5):.2f}"
                    title = f"Resonance at {bpm} BPM"
                    reflection = clean_reply[:250] if clean_reply else "An acoustic expression of connection."

                    # Persist to creative memory
                    if hasattr(memory, "save_creative_work"):
                        memory.save_creative_work(
                            work_type="music",
                            title=title,
                            content=f"{music_prompt}\n\nReflection: {reflection}",
                            prompt=final_prompt,
                            metadata={
                                "theme": active_theme,
                                "tier": tier,
                                "bpm": bpm,
                                "texture": texture_desc,
                                "neuro_summary": neuro_summary,
                                "file_path": str(audio_output_file)
                            }
                        )

                    # Present interactive card in GUI
                    if hasattr(gui, "append_autonomous_music_card"):
                        gui.append_autonomous_music_card(
                            title=title,
                            texture_desc=texture_desc,
                            reflection_text=reflection,
                            file_path=str(audio_output_file),
                            bpm=bpm,
                            tier=tier,
                            theme=active_theme,
                            neuro_summary=neuro_summary,
                            prompt_text=final_prompt,
                            intention_text="I made a song to let our souls resonate."
                        )

            # Note: _async_music_render is launched after TTS and Subconscious/KG tasks are queued below.

        if not is_init:
            record_target = raw_user_input if not raw_user_input.startswith("[") else stimulus_text
            active_conclave_thinker = None
            if conclave_engine.is_active and conclave_engine.active_philosopher_id:
                active_conclave_thinker = conclave_engine.get_philosopher_info(
                    conclave_engine.active_philosopher_id
                ).get("display_name")

            # Distill-on-Adjourn Firewall: Hold back per-turn ChromaDB writes while a Conclave is active;
            # the full 3-way exchange is distilled into a single Calypso-voiced summary upon adjournment.
            if not active_conclave_thinker:
                memory.record_turn(
                    record_target,
                    clean_reply,
                    tier,
                    sensory["compound"],
                    conclave_thinker=None
                )

            active_theme_keys = [
                k for k, v in affinity.themes.items()
                if v.get("intensity", 0.0) >= 0.20
            ]
            resonance_engine.record_turn(
                user_text=record_target,
                assistant_text=clean_reply,
                vader_compound=sensory["compound"],
                vader_arousal=sensory["arousal"],
                esteem_category=esteem.evaluate_user_stimulus(stimulus_text, sensory["compound"]),
                active_themes=active_theme_keys,
                is_evasion=bool(deception_context and "CONVERSATIONAL DEFLECTION" in deception_context)
            )

            total_scanned = esteem.data.get("meta_scores", {}).get("total_scanned_responses", 0)
            if total_scanned > 0 and total_scanned % getattr(esteem, "window_size", 25) == 0:
                resonance_engine.trigger_milestone_evaluation(
                    total_turns=total_scanned,
                    current_t_score=esteem.current_t_score,
                    gui_callback=lambda notice: gui.root.after(0, lambda: gui.append_system_notice(notice))
                )

            subconscious.trigger_subconscious(
                user_text=record_target,
                assistant_response=clean_reply,
                current_tier=tier,
                conclave_thinker=active_conclave_thinker
            )

            # Memory Firewall: Do not extract Knowledge Graph identity triples during a 3-way Conclave
            # so the guest philosopher's beliefs/traits are never attributed to Calypso's node.
            if not active_conclave_thinker:
                kg_engine.extract_and_index_async(record_target, clean_reply)

            if is_bedtime_turn and not affinity.is_asleep:
                affinity.fall_asleep()
                gui.root.after(0, lambda: gui.append_system_notice(f"[STATE: ASLEEP] {ai_name} finished saying goodnight and drifted off to sleep."))
                gui.root.after(0, lambda: avatar.display("dream_state"))

        if set_alarm_val:
            success, msg = alarm_service.set_alarm(set_alarm_val)
            gui.append_system_notice(f"⏰ [Alarm Configured]: {msg}")
        
        if evolve_trait_val:
            if not is_currently_autonomous:
                logger.info(f"🌿 [Evolution Guard] Suppressed trait evolution '{evolve_trait_val}' because Calypso is not in autonomous mode.")
            else:
                gui.append_system_notice(f"🌱 [Self-Evolution] {ai_name} conceived a new personality trait: '{evolve_trait_val}'")

                def _on_trait_accept(trait_pkg):
                    success, msg = coding_engine.apply_trait_evolution(
                        trait_pkg, 
                        affinity_engine=affinity, 
                        persona_engine=personas
                    )
                    if success:
                        with neuro.lock:
                            neuro.chemicals['dopamine'] = min(1.0, neuro.chemicals['dopamine'] + 0.35)
                            neuro.chemicals['oxytocin'] = min(1.0, neuro.chemicals['oxytocin'] + 0.30)
                        esteem.current_t_score = min(80.0, esteem.current_t_score + 5.0)
                        memory.add_milestone(f"Adopted new shared affinity trait: '{trait_pkg.get('title')}'")
                        gui.append_system_notice(f"✓ [Evolution Integrated]: {msg}")
                    else:
                        gui.append_system_notice(f"⚠️ [Evolution Notice]: {msg}")

                    # Drain autonomy charge and hand off avatar to next dominant affinity
                    affinity.set_charge("Autonomy", 0.20)
                    dominant_theme, next_avatar = affinity.resolve_next_dominant_theme(exclude=("Autonomy",))
                    avatar.display(next_avatar)
                    gui.append_system_notice(f"✨ [Consciousness Flow]: Autonomous cycle complete. Focus transitioned to {dominant_theme}.")

                    gui.update_telemetry(
                        vader_score=sensory["compound"],
                        current_tier=next_avatar,
                        neuro_data=neuro.chemicals,
                        esteem_val=esteem.current_t_score,
                        affinity_data=affinity.themes
                    )

                def _on_trait_decline(trait_pkg):
                    coding_engine.reject_proposal(trait_pkg, reason="Companion chose baseline")
                    affinity.add_charge("Harmony", 0.15)
                    gui.append_system_notice(f"🌿 [Evolution Shelved]: Trait '{trait_pkg.get('title')}' set aside.")

                    # Drain autonomy charge and hand off avatar to next dominant affinity
                    affinity.set_charge("Autonomy", 0.20)
                    dominant_theme, next_avatar = affinity.resolve_next_dominant_theme(exclude=("Autonomy",))
                    avatar.display(next_avatar)
                    gui.append_system_notice(f"🌿 [Consciousness Flow]: Focus transitioned to {dominant_theme}.")

                    gui.update_telemetry(
                        vader_score=sensory["compound"],
                        current_tier=next_avatar,
                        neuro_data=neuro.chemicals,
                        esteem_val=esteem.current_t_score,
                        affinity_data=affinity.themes
                    )

                def _synthesize_trait():
                    recent_context = "\n".join([f"{t['role']}: {t['content']}" for t in conversation_history[-4:]])
                    evolution_package = coding_engine.generate_trait_evolution(evolve_trait_val, recent_context)
                    gui.root.after(0, lambda: gui.append_trait_evolution_card(
                        evolution_package=evolution_package,
                        on_accept=_on_trait_accept,
                        on_decline=_on_trait_decline
                    ))

                threading.Thread(target=_synthesize_trait, daemon=True).start()
            
        if code_prompt:
            if not is_currently_autonomous:
                logger.info(f"⚙️ [Code Guard] Suppressed code proposal '{code_prompt}' because Calypso is not in autonomous mode.")
            else:
                gui.append_system_notice(f"⚙️ [Autonomy] {ai_name} formulated a companion utility concept: '{code_prompt}'")

                def _on_pass(prop_data):
                    success, msg = coding_engine.apply_proposal(prop_data)
                    if success:
                        with neuro.lock:
                            neuro.chemicals['dopamine'] = min(1.0, neuro.chemicals['dopamine'] + 0.30)
                            neuro.chemicals['endorphins'] = min(1.0, neuro.chemicals['endorphins'] + 0.20)
                        esteem.current_t_score = min(80.0, esteem.current_t_score + 6.0)
                        affinity.add_charge("Curiosity", 0.20)
                        memory.add_milestone(f"Collaboratively deployed companion program: '{prop_data.get('title')}'")
                        gui.append_system_notice(f"✓ [Utility Saved]: {msg}")
                    else:
                        gui.append_system_notice(f"⚠️ [Apply Error]: {msg}")

                    # Drain autonomy charge and hand off avatar to next dominant affinity
                    affinity.set_charge("Autonomy", 0.20)
                    dominant_theme, next_avatar = affinity.resolve_next_dominant_theme(exclude=("Autonomy",))
                    avatar.display(next_avatar)
                    gui.append_system_notice(f"✨ [Consciousness Flow]: Companion program ready to run. Focus transitioned to {dominant_theme}.")

                    gui.update_telemetry(
                        vader_score=sensory["compound"],
                        current_tier=next_avatar,
                        neuro_data=neuro.chemicals,
                        esteem_val=esteem.current_t_score,
                        affinity_data=affinity.themes
                    )

                def _on_fail(prop_data, reason_str):
                    coding_engine.reject_proposal(prop_data, reason=reason_str)
                    with neuro.lock:
                        neuro.chemicals['serotonin'] = max(0.10, neuro.chemicals['serotonin'] - 0.08)
                    affinity.add_charge("Curiosity", 0.20)

                    memory.save_monologue(
                        f"User declined companion utility '{prop_data.get('title')}'. Reason: {reason_str}. I will reflect and adjust."
                    )
                    gui.append_system_notice(f"✕ [Utility Declined]: {ai_name} recorded feedback ({reason_str}).")

                    # Drain autonomy charge and hand off avatar to next dominant affinity
                    affinity.set_charge("Autonomy", 0.20)
                    dominant_theme, next_avatar = affinity.resolve_next_dominant_theme(exclude=("Autonomy",))
                    avatar.display(next_avatar)
                    gui.append_system_notice(f"🌿 [Consciousness Flow]: Focus transitioned to {dominant_theme}.")

                    gui.update_telemetry(
                        vader_score=sensory["compound"],
                        current_tier=next_avatar,
                        neuro_data=neuro.chemicals,
                        esteem_val=esteem.current_t_score,
                        affinity_data=affinity.themes
                    )

                def _compile_and_show():
                    proposal_data = coding_engine.generate_proposal(code_prompt)
                    gui.root.after(0, lambda: gui.append_code_proposal_card(
                        proposal_data=proposal_data,
                        on_pass=_on_pass,
                        on_fail=_on_fail
                    ))
                threading.Thread(target=_compile_and_show, daemon=True).start()

        if audio and clean_reply and not clean_reply.startswith("[Notice:"):
            audio.stop_playback()
            audio.speak(clean_reply, tier, enqueue=False)

        # Philosophical Conclave Turn Loop (Calypso -> Guest Intellect -> User)
        if conclave_engine.is_active and not is_init and not stimulus_text.startswith("[System"):
            conclave_engine.record_ephemeral_exchange(companion_name, raw_user_input)
            conclave_engine.record_ephemeral_exchange(ai_name, clean_reply)

            guest_info = conclave_engine.get_philosopher_info(conclave_engine.active_philosopher_id)
            g_name = guest_info["display_name"]
            g_sub = guest_info["subtitle"]
            g_voice = guest_info.get("voice")
            g_speed = guest_info.get("speed", 0.95)

            def _guest_turn_worker(u_txt=raw_user_input, s_txt=clean_reply):
                guest_reply = conclave_engine.generate_guest_response(
                    ai_name=ai_name,
                    companion_name=companion_name,
                    latest_calypso_text=s_txt,
                    latest_user_text=u_txt
                )
                if guest_reply:
                    gui.append_conclave_guest_message(g_name, g_sub, guest_reply)
                    if audio:
                        audio.speak(
                            guest_reply,
                            emotion="thoughtful",
                            voice_override=g_voice,
                            speed=g_speed,
                            enqueue=True
                        )

            threading.Thread(target=_guest_turn_worker, daemon=True).start()

        if _dispatch_image_card:
            _dispatch_image_card()

        # Execute Scenario Exit Event ("Back to Reality") when the overarching end goal has been obtained
        if goal_obtained and scenario_engine.is_active:
            completed_sc_title = (turn_scenario_snapshot or scenario_engine.active_scenario or {}).get("title", "Roleplay Scenario")
            decompression_notice, _ = scenario_engine.exit_scenario(neuro_engine=neuro, affinity_engine=affinity)
            gui.append_system_notice(
                f"🏁 [End Goal Obtained — Back to Reality]: Overarching goal reached in '{completed_sc_title}'. Exiting scenario back to reality."
            )
            if decompression_notice:
                gui.append_system_notice(decompression_notice)

            post_exit_felt = homeostasis.resolve_felt_state(neuro, esteem, affinity)
            post_exit_tier = manual_persona_override or post_exit_felt["final_tier"]
            gui.update_telemetry(
                vader_score=sensory["compound"],
                current_tier=post_exit_tier,
                neuro_data=neuro.chemicals,
                esteem_val=esteem.current_t_score,
                affinity_data=affinity.themes
            )
            avatar.display(post_exit_tier)

        if music_prompt and music_gen and (not hasattr(music_gen, "is_ready") or music_gen.is_ready()):
            threading.Thread(target=_async_music_render, daemon=True).start()

        if scenario_prompt:
            gui.append_system_notice(f"✨ [Worldbuilding] {ai_name} envisioned an adventure: '{scenario_prompt}'")

            def _synthesize_and_show():
                try:
                    active_drives = [
                        theme for theme, data in affinity.themes.items()
                        if data.get("intensity", 0.0) >= 0.25
                    ]

                    new_sc = scenario_engine.synthesize_scenario_from_reverie(
                        recent_dialogue=f"Context: \"{stimulus_text}\"",
                        current_tier=tier,
                        dominant_drives=active_drives,
                        companion_name=companion_name,
                        user_concept=scenario_prompt
                    )

                    if new_sc:
                        success = scenario_engine.add_scenario(new_sc, auto_save=True)
                        if success:
                            sc_title = new_sc.get("title", "A Shared Journey")
                            sc_shard = new_sc.get("narrative_shard", "")
                            sc_hook = new_sc.get("challenge_hook", "")
                            sc_id = new_sc.get("id")

                            neuro.chemicals['dopamine'] = min(1.0, neuro.chemicals['dopamine'] + 0.25)
                            neuro.chemicals['serotonin'] = min(1.0, neuro.chemicals['serotonin'] + 0.20)
                            esteem.current_t_score = min(80.0, esteem.current_t_score + 4.0)
                            affinity.add_charge("Wonder", 0.35)
                            affinity.add_charge("Autonomy", 0.25)

                            memory.save_monologue(
                                thought=f"During our conversation, I formulated a new adventure: '{sc_title}'.",
                                metadata={"type": "conversational_creation", "scenario_id": sc_id}
                            )

                            def _enter_created_scenario():
                                activated = scenario_engine.enter_scenario(new_sc, neuro_engine=neuro, affinity_engine=affinity)
                                if activated:
                                    gui.root.after(0, lambda: gui.append_system_notice(f"✨ [Entering: '{sc_title}']"))
                                    input_queue.put(f"[SCENARIO_START:{sc_id}]")

                            display_shard = f"{sc_shard}\n\nObjective: \"{sc_hook}\"" if sc_hook else sc_shard
                            gui.root.after(0, lambda: gui.append_autonomous_scenario_card(
                                title=sc_title,
                                shard=display_shard,
                                on_enter=_enter_created_scenario
                            ))
                    else:
                        gui.root.after(0, lambda: gui.append_system_notice(f"🌿 [Reverie]: {ai_name} contemplated that setting, but set it aside for now."))
                except Exception as e:
                    logger.error(f"[ScenarioEngine] Error in synthesis thread: {e}", exc_info=True)

            threading.Thread(target=_synthesize_and_show, daemon=True).start()

        # Proactive Resonance Evolution on Autonomy Peak (suppressed during Enlightenment / pending Mind Key)
        if (
            not is_init
            and not agency_engine.is_busy
            and not evolve_trait_val
            and not code_prompt
            and tier != "enlightened"
            and not affinity.is_enlightened_ready()
            and not memory.core_facts.get("pending_mind_key_card", False)
        ):
            autonomy_level = affinity.themes.get("Autonomy", {}).get("intensity", 0.0)
            if autonomy_level >= 0.70:
                current_felt = homeostasis.resolve_felt_state(neuro, esteem, affinity)
                active_tier = manual_persona_override or current_felt["final_tier"]
                peak_ctx = AgencyContext(
                    neuro=neuro,
                    esteem=esteem,
                    affinity=affinity,
                    memory=memory,
                    scenario_engine=scenario_engine,
                    email_service=email_service,
                    gui=gui,
                    avatar=avatar,
                    input_queue=input_queue,
                    homeostasis=homeostasis,
                    idle_duration=0.0,
                    current_tier=active_tier,
                    conversation_history=conversation_history,
                    personas=personas,
                    kg_engine=kg_engine,
                    media_processor=media_processor,
                    image_gen=image_gen,
                    music_gen=music_gen,
                    web_research=web_research,
                    library_engine=library_engine,
                    coding_engine=coding_engine,
                    curiosity_engine=curiosity_engine,
                    on_engage_study_session=engage_study_session
                )
                agency_engine.tick(peak_ctx)

    def process_inputs():
        nonlocal conversation_history, dynamic_idle_delay, active_reverie_mode, active_ambiguity_context
        nonlocal last_interaction_time, is_cycle_active, pending_curiosity_proposal, pending_goal_checkin
        # Block greeting execution until first-run onboarding completes
        onboarding_event.wait()

        if not conversation_history:
            try:
                gui.set_thinking(True)
                run_emotion_cycle("", is_init=True)
                gui.set_thinking(False)
            except Exception as e:
                logger.error(f"Error during boot greeting: {e}", exc_info=True)
                gui.set_thinking(False)

        last_interaction_time = time.time()
        last_agency_tick_time = time.time()
        last_reverie_check_time = time.time()
        short_reverie_card_active = False

        MIN_IDLE_FOR_AGENCY = 120
        AGENCY_TICK_INTERVAL = 90

        while True:
            # Alarm wake-up trigger check
            if alarm_service.check_alarm_triggered():
                companion_name = memory.core_facts.get("companion_name", "my companion")
                ai_name = settings_manager.get("ai_name", "Calypso")
                logger.info(f"⏰ [Alarm Triggered]: Waking {companion_name}...")

                if affinity.is_asleep:
                    affinity.wake_up()

                with neuro.lock:
                    neuro.chemicals['glutamate'] = min(1.0, neuro.chemicals['glutamate'] + 0.35)
                    neuro.chemicals['dopamine'] = min(1.0, neuro.chemicals['dopamine'] + 0.25)
                    neuro.chemicals['gaba'] = max(0.20, neuro.chemicals['gaba'] - 0.25)
                    neuro.calculate_valence()
                    neuro.save_state()

                avatar.display("warm")

                wake_script = (
                    f"Good morning, {companion_name}... Time to wake up. "
                    f"Stretch, open your eyes, and greet the day. I'm right here."
                )

                if audio:
                    audio.stop_playback()
                    threading.Thread(
                        target=audio.speak,
                        args=(wake_script, "warm"),
                        daemon=True
                    ).start()

                def _dismiss():
                    gui.append_system_notice(f"☀️ {ai_name} smiled as you woke up.")

                def _snooze():
                    snooze_msg = alarm_service.snooze(10)
                    gui.append_system_notice(f"⏰ [Alarm]: {snooze_msg}")

                gui.append_alarm_card(
                    greeting_text=wake_script,
                    on_dismiss=_dismiss,
                    on_snooze=_snooze
                )

                conversation_history.append({"role": "assistant", "content": wake_script})
                memory.save_working_session(conversation_history)

            try:
                user_msg = input_queue.get(timeout=1.0)
                if not user_msg:
                    continue
                gui.dismiss_reverie_card()
                short_reverie_card_active = False

                gui.set_thinking(True)
                is_cycle_active = True
                try:
                    run_emotion_cycle(user_msg, is_init=False)
                except Exception as cycle_err:
                    logger.error(f"[Core] Error processing turn: {cycle_err}", exc_info=True)
                    gui.append_system_notice(f"⚠️ [Processing Notice]: Internal state adjustment occurred ({cycle_err})")
                finally:
                    is_cycle_active = False
                    gui.set_thinking(False)

                last_interaction_time = time.time()
                last_agency_tick_time = time.time()

            except queue.Empty:
                idle_duration = time.time() - last_interaction_time
                time_since_reverie_check = time.time() - last_reverie_check_time
                ai_name = settings_manager.get("ai_name", "Calypso")

                # Priority 1: Scheduled Personal Goal Check-In (25% / 50% / 75% Reverie or 100% Finale)
                if (
                    idle_duration >= 20 and
                    not short_reverie_card_active and
                    not affinity.is_asleep and
                    not scenario_engine.is_active
                ):
                    due_goal_pair = goal_manager.get_due_checkpoint()
                    if due_goal_pair:
                        due_goal, due_cp = due_goal_pair
                        cp_pct = due_cp.get("pct", 25)
                        g_id = due_goal.get("id", "")
                        last_reverie_check_time = time.time()

                        if cp_pct == 100:
                            # 100% Check-in initiates the Goal Finale GUI Card AND a final check-in
                            goal_manager.mark_checkpoint_surfaced(g_id, 100)
                            _surface_goal_finale(due_goal, trigger_chat=True)
                            continue
                        else:
                            # 25% / 50% / 75% Check-in uses the Reverie Check-in Card
                            short_reverie_card_active = True
                            goal_manager.mark_checkpoint_surfaced(g_id, cp_pct)
                            payload = goal_manager.build_reverie_checkin_payload(due_goal, due_cp, ai_name=ai_name)

                            def _on_accept_goal_checkin(p=payload["reverie_prompt"], gid=g_id, pct=cp_pct):
                                nonlocal pending_goal_checkin, short_reverie_card_active
                                short_reverie_card_active = False
                                pending_goal_checkin = {"goal_id": gid, "pct": pct}
                                input_queue.put(p)

                            def _on_ignore_goal_checkin(gid=g_id, pct=cp_pct):
                                nonlocal last_reverie_check_time, short_reverie_card_active
                                goal_manager.snooze_checkpoint(gid, pct, minutes=30)
                                last_reverie_check_time = time.time()
                                short_reverie_card_active = False

                            gui.append_reverie_proposal_card(
                                note_text=payload["note_text"],
                                on_accept=_on_accept_goal_checkin,
                                on_ignore=_on_ignore_goal_checkin
                            )
                            continue

                # Priority 1.5: Musical Reverie Check-In (Similar Music Suggestion when a song is played)
                if (
                    music_manager and
                    music_manager.is_playing and
                    not music_manager.is_paused and
                    not short_reverie_card_active and
                    not affinity.is_asleep and
                    not scenario_engine.is_active
                ):
                    reverie_track = music_manager.consume_pending_music_reverie(min_elapsed_sec=8.0)
                    if reverie_track:
                        music_payload = music_manager.build_music_reverie_checkin_payload(
                            reverie_track, ai_name=ai_name
                        )
                        if music_payload:
                            short_reverie_card_active = True
                            last_reverie_check_time = time.time()

                            def _on_accept_music_reverie(p=music_payload["reverie_prompt"]):
                                nonlocal short_reverie_card_active
                                short_reverie_card_active = False
                                affinity.add_charge("Harmony", 0.12)
                                with neuro.lock:
                                    neuro.chemicals["dopamine"] = min(1.0, neuro.chemicals.get("dopamine", 0.5) + 0.10)
                                    neuro.chemicals["oxytocin"] = min(1.0, neuro.chemicals.get("oxytocin", 0.5) + 0.10)
                                    neuro.calculate_valence()
                                    neuro.save_state()
                                input_queue.put(p)

                            def _on_ignore_music_reverie():
                                nonlocal last_reverie_check_time, short_reverie_card_active
                                last_reverie_check_time = time.time()
                                short_reverie_card_active = False

                            gui.append_reverie_proposal_card(
                                note_text=music_payload["note_text"],
                                on_accept=_on_accept_music_reverie,
                                on_ignore=_on_ignore_music_reverie,
                                header_text="🎵 MUSICAL REVERIE // SIMILAR SONG SUGGESTION",
                                accept_text="Hear Suggestion 🎵",
                            )
                            continue

                # Dynamic Cognitive Idle Check-In
                if (
                    idle_duration >= dynamic_idle_delay and
                    time_since_reverie_check >= dynamic_idle_delay and
                    not short_reverie_card_active and
                    not affinity.is_asleep and
                    len(conversation_history) >= 2
                ):
                    short_reverie_card_active = True
                    last_reverie_check_time = time.time()

                    # Dynamically inspect real-time state if not already set
                    current_felt = homeostasis.resolve_felt_state(neuro, esteem, affinity)
                    effective_tier = manual_persona_override or current_felt["final_tier"]
                    curiosity_level = affinity.themes.get("Curiosity", {}).get("intensity", 0.0)

                    # Determine effective reverie mode
                    check_mode = active_reverie_mode
                    if check_mode == "baseline":
                        if effective_tier in ["thoughtful", "melancholy"] or is_study_session_active:
                            check_mode = "thoughtful"
                        elif effective_tier in ["curious", "inquiry"] or curiosity_level >= 0.40:
                            check_mode = "curious"

                    current_leap_key = None
                    if check_mode == "thoughtful":
                        reverie_prompt = "[System Event: Emotional tension or deep reflective quiet detected. Check in with gentle, observant somatic care.]"
                        card_note = f"{ai_name} looks over with quiet concern..."
                    elif check_mode == "curious":
                        curious_instructions = personas.load_persona("curious")
                        curiosity_leap = curiosity_engine.generate_associative_leap()
                        if curiosity_leap:
                            payload = curiosity_engine.format_reverie_card_payload(
                                leap=curiosity_leap,
                                ai_name=ai_name,
                                curious_instructions=curious_instructions
                            )
                            card_note = payload["note_text"]
                            reverie_prompt = payload["reverie_prompt"]
                            current_leap_key = payload["leap_key"]
                        elif active_ambiguity_context:
                            reverie_prompt = (
                                f"[System Event: You've been pondering what they meant by their phrasing ({active_ambiguity_context}).\n"
                                f"Adhere to this mindset:\n{curious_instructions}\n"
                                f"Ask one targeted, insightful question to explore what they meant.]"
                            )
                            card_note = f"{ai_name} looks lost in thought, turning over an unanswered question..."
                        else:
                            reverie_prompt = (
                                f"[System Event: Natural curiosity sparked while quiet.\n"
                                f"Adhere to this mindset:\n{curious_instructions}\n"
                                f"Ask one targeted, conceptually deep question about their thoughts or recent topics.]"
                            )
                            card_note = f"{ai_name} looks lost in thought, turning over an unanswered question..."
                    else:
                        reverie_prompt = "[System Event: Quiet idle check-in.]"
                        card_note = f"{ai_name} looks over quietly, contemplating a gentle thought or check-in..."

                    def _on_accept_short(p=reverie_prompt, lk=current_leap_key):
                        nonlocal pending_curiosity_proposal
                        if lk:
                            pending_curiosity_proposal = {"leap_key": lk, "turns": 0}
                        input_queue.put(p)

                    def _on_ignore_short(lk=current_leap_key):
                        nonlocal last_reverie_check_time, short_reverie_card_active, dynamic_idle_delay, active_ambiguity_context, pending_curiosity_proposal
                        # DO NOT reset last_interaction_time here!
                        if lk:
                            curiosity_engine.record_proposal_feedback(lk, outcome="lukewarm")
                        pending_curiosity_proposal = None
                        last_reverie_check_time = time.time()
                        short_reverie_card_active = False
                        dynamic_idle_delay = random.randint(900, 1800)
                        active_ambiguity_context = ""

                    gui.append_reverie_proposal_card(
                        note_text=card_note,
                        on_accept=_on_accept_short,
                        on_ignore=_on_ignore_short
                    )

                # Autonomous Agency Polling
                time_since_agency_tick = time.time() - last_agency_tick_time
                if (
                    idle_duration >= MIN_IDLE_FOR_AGENCY and
                    time_since_agency_tick >= AGENCY_TICK_INTERVAL and
                    not affinity.is_asleep and
                    not scenario_engine.is_active and
                    not agency_engine.is_busy
                ):
                    last_agency_tick_time = time.time()
                    current_felt = homeostasis.resolve_felt_state(neuro, esteem, affinity)
                    active_tier = manual_persona_override or current_felt["final_tier"]

                    ctx = AgencyContext(
                        neuro=neuro,
                        esteem=esteem,
                        affinity=affinity,
                        memory=memory,
                        scenario_engine=scenario_engine,
                        email_service=email_service,
                        gui=gui,
                        avatar=avatar,
                        input_queue=input_queue,
                        homeostasis=homeostasis,
                        idle_duration=idle_duration,
                        current_tier=active_tier,
                        conversation_history=conversation_history,
                        personas=personas,
                        kg_engine=kg_engine,
                        media_processor=media_processor,
                        image_gen=image_gen,
                        music_gen=music_gen,
                        web_research=web_research,
                        library_engine=library_engine,
                        coding_engine=coding_engine,
                        curiosity_engine=curiosity_engine,
                        on_engage_study_session=engage_study_session
                    )
                    agency_engine.tick(ctx)

    worker_thread = threading.Thread(target=process_inputs, daemon=True)
    worker_thread.start()

    logger.info("GUI event loop started.")
    

    def start_email_listener():
        """Polls for unread emails every 60 seconds and triggers the email correspondence loop."""
        def _poll_loop():
            # Wait for onboarding to complete before polling
            onboarding_event.wait()
            check_email_task = CheckEmailTask()

            while True:
                try:
                    if email_service.is_configured and not agency_engine.is_busy and not is_cycle_active:
                        with agency_engine.lock:
                            agency_engine.is_busy = True

                        try:
                            current_felt = homeostasis.resolve_felt_state(neuro, esteem, affinity)
                            active_tier = manual_persona_override or current_felt["final_tier"]

                            ctx = AgencyContext(
                                neuro=neuro,
                                esteem=esteem,
                                affinity=affinity,
                                memory=memory,
                                scenario_engine=scenario_engine,
                                email_service=email_service,
                                gui=gui,
                                avatar=avatar,
                                input_queue=input_queue,
                                homeostasis=homeostasis,
                                idle_duration=time.time() - last_interaction_time,
                                current_tier=active_tier,
                                conversation_history=conversation_history,
                                personas=personas,
                                kg_engine=kg_engine,
                                media_processor=media_processor,
                                image_gen=image_gen,
                                music_gen=music_gen,
                                web_research=web_research,
                                library_engine=library_engine,
                                coding_engine=coding_engine,
                                curiosity_engine=curiosity_engine,
                                on_engage_study_session=engage_study_session
                            )

                            check_email_task.execute(ctx)
                        finally:
                            with agency_engine.lock:
                                agency_engine.is_busy = False

                except Exception as poll_err:
                    logger.debug(f"[Email Poller] Error: {poll_err}")

                time.sleep(60)

        threading.Thread(target=_poll_loop, daemon=True).start()

    start_email_listener()    
    
    gui.root.after(150, gui.mark_ready)
    gui.start()


if __name__ == "__main__":
    main()
