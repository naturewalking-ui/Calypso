# modules/coding_processor.py

import ast
import json
import logging
import os
import platform
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from modules.config import config

logger = logging.getLogger("Calypso.Coding")

MAX_CUSTOM_AFFINITIES = 3

BANNED_IMPORTS = {
    "subprocess", "shutil", "socket", "pty", "winreg", "ctypes",
    "sqlite3", "shelve", "pickle", "importlib", "chromadb",
    "multiprocessing", "threading"
}
BANNED_BUILTIN_CALLS = {"eval", "exec", "compile", "__import__", "globals", "locals"}


class CodingModule:
    def __init__(self):
        self.code_dir = (config.BASE_DIR / "workspace" / "output" / "code").resolve()
        self.utilities_dir = self.code_dir / "utilities"
        self.proposals_dir = self.code_dir / "proposals"
        self.history_dir = self.code_dir / "history"
        self.map_file = config.MEMORY_DIR / "codebase_map.json"
        
        # Path to custom affinities and persona directory
        self.custom_affinities_file = config.MEMORY_DIR / "custom_affinities.json"
        self.personas_dir = config.BASE_DIR / "modules" / "emotion" / "personas"
        self.custom_affinities_file.parent.mkdir(parents=True, exist_ok=True)
        self.personas_dir.mkdir(parents=True, exist_ok=True)

        self.utilities_dir.mkdir(parents=True, exist_ok=True)
        self.proposals_dir.mkdir(parents=True, exist_ok=True)
        self.history_dir.mkdir(parents=True, exist_ok=True)

        self.codebase_map = self._load_codebase_map()

    def _load_codebase_map(self) -> dict:
        if self.map_file.exists():
            try:
                with open(self.map_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"[Coding] Failed to load codebase_map.json: {e}")
        return {}

    def get_custom_affinities(self) -> dict:
        """Safely loads and returns all currently registered custom affinities."""
        if self.custom_affinities_file.exists():
            try:
                with open(self.custom_affinities_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"[Coding] Failed to read custom_affinities.json: {e}")
        return {}

    def get_subsystem_summary(self, key: str = None) -> str:
        """Produces a compact context snippet for the target subsystem."""
        if not self.codebase_map:
            return "No subsystem map available."

        if key and key in self.codebase_map:
            data = self.codebase_map[key]
            return (
                f"Target Category: {data.get('module_name', key)}\n"
                f"Description: {data.get('description', '')}\n"
                f"Guidelines: {', '.join(data.get('public_api', []))}\n"
                f"Output Destination: {', '.join(data.get('modifiable_targets', []))}\n"
            )

        # Overview of all available modules
        lines = ["Available Companion Program Categories:"]
        for k, v in self.codebase_map.items():
            if k.startswith("_"):
                continue
            lines.append(f"- [{k}]: {v.get('module_name', k)} - {v.get('description', '')}")
        return "\n".join(lines)

    @staticmethod
    def extract_python_code(raw_reply: str) -> tuple[str, bool]:
        """
        Extracts clean Python code from LLM output.
        Returns (code, is_closed_cleanly).
        """
        if not raw_reply:
            return "", False

        # 1. Strip think blocks if present in content
        cleaned = re.sub(r"<think>.*?</think>", "", raw_reply, flags=re.DOTALL).strip()

        # 2. Match standard closed markdown block: ```python ... ``` or ```py ... ``` or ``` ... ```
        match = re.search(r"```(?:python|py)?\s*\n?(.*?)\n?```", cleaned, re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1).strip(), True

        # 3. Handle unclosed markdown block (e.g. truncated generation or omitted closing fence)
        open_match = re.search(r"```(?:python|py)?\s*\n?(.*)", cleaned, re.DOTALL | re.IGNORECASE)
        if open_match:
            code = open_match.group(1).strip()
            code = re.sub(r"```+$", "", code).strip()
            return code, False

        # 4. Fallback: bare text, strip any stray leading/trailing fences
        code = re.sub(r"^```(?:python|py)?\s*\n?|```+$", "", cleaned, flags=re.IGNORECASE).strip()
        return code, False

    def validate_code(self, python_code: str) -> tuple[bool, str]:
        """Performs static AST validation and security audit on standalone Python scripts."""
        try:
            tree = ast.parse(python_code)
        except SyntaxError as e:
            return False, f"Syntax Error on line {e.lineno}: {e.msg}"

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root_pkg = alias.name.split(".")[0]
                    if root_pkg in BANNED_IMPORTS:
                        return False, f"Security Violation: Import '{alias.name}' is prohibited."
                    if "memory" in alias.name.lower():
                        return False, f"Security Violation: Direct memory module access '{alias.name}' is prohibited."
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    root_pkg = node.module.split(".")[0]
                    if root_pkg in BANNED_IMPORTS:
                        return False, f"Security Violation: Import from '{node.module}' is prohibited."
                    if "memory" in node.module.lower():
                        return False, f"Security Violation: Direct memory module access '{node.module}' is prohibited."
            elif isinstance(node, ast.Attribute):
                if node.attr == "modules" and isinstance(node.value, ast.Name) and node.value.id == "sys":
                    return False, "Security Violation: Access to 'sys.modules' is prohibited."
            elif isinstance(node, ast.Call):
                # Check for banned builtin calls
                if isinstance(node.func, ast.Name) and node.func.id in BANNED_BUILTIN_CALLS:
                    return False, f"Security Violation: Prohibited call to '{node.func.id}()'."
                elif isinstance(node.func, ast.Attribute):
                    attr_name = node.func.attr
                    if attr_name in BANNED_BUILTIN_CALLS:
                        return False, f"Security Violation: Prohibited call '{attr_name}()'."
                    if attr_name in {"system", "popen", "kill", "chmod"}:
                        return False, f"Security Violation: Prohibited system call '{attr_name}()'."
                    if attr_name in {"remove", "unlink", "rmdir", "rmtree"}:
                        if isinstance(node.func.value, ast.Name) and node.func.value.id in {"os", "shutil", "Path"}:
                            return False, f"Security Violation: File deletion '{node.func.value.id}.{attr_name}()' is prohibited."

        return True, "Code passed AST static verification."

    def generate_proposal(self, prompt_text: str, target_subsystem: str = None) -> dict:
        """
        Synthesizes a standalone, user-facing Python CLI program (playful toy, cozy gadget,
        or creative spark) based on codebase_map.json.
        """
        logger.info(f"[Coding] Synthesizing companion utility proposal: {prompt_text}")

        # Resolve target module context
        matched_key = target_subsystem
        if not matched_key:
            prompt_lower = prompt_text.lower()
            if any(w in prompt_lower for w in ["game", "toy", "dice", "play", "trivia", "adventure", "quiz", "ascii"]):
                matched_key = "playful_toys"
            elif any(w in prompt_lower for w in ["story", "spark", "poem", "poet", "character", "random", "brainstorm", "prompt"]):
                matched_key = "creative_sparks"
            elif any(w in prompt_lower for w in ["timer", "clock", "pomodoro", "tea", "coffee", "breath", "habit", "gratitude", "focus", "gadget"]):
                matched_key = "cozy_gadgets"
            else:
                for k in self.codebase_map:
                    if k in prompt_lower or self.codebase_map[k].get("module_name", "").lower() in prompt_lower:
                        matched_key = k
                        break
        
        if not matched_key or matched_key not in self.codebase_map:
            matched_key = "cozy_gadgets"

        context_info = self.get_subsystem_summary(matched_key)

        timestamp = time.strftime("%Y%m%d_%H%M%S")
        sanitized_name = re.sub(r"[^a-zA-Z0-9_]", "_", prompt_text[:28]).strip("_").lower()
        if not sanitized_name:
            sanitized_name = f"gadget_{timestamp}"
        
        target_file_name = f"{sanitized_name}.py"
        target_file = f"workspace/output/code/utilities/{target_file_name}"
        resolved_target = (config.BASE_DIR / target_file).resolve()

        system_instruction = (
            "You are Calypso's Creative Workshop & Companion Gadget Forge.\n"
            "Your objective is to craft charming, engaging, well-documented, self-contained standalone Python 3 CLI programs "
            "(playful text games, cozy daily gadgets, or creative sparks) in workspace/output/code/utilities/.\n\n"
            f"SUBSYSTEM CATALOG CONTEXT:\n{context_info}\n\n"
            "STRICT ARCHITECTURAL & USER EXPERIENCE REQUIREMENTS:\n"
            "1. Standalone scripts only: The tool must run independently in a terminal console using standard Python 3.\n"
            "2. Interactive & Cozy: Include clear step-by-step console prompts (using input() and print()), ASCII flourishes, or clean menus.\n"
            "3. Standard Libraries Only: Use random, time, datetime, math, string, collections, textwrap, etc.\n"
            "4. NEVER attempt to import banned packages (subprocess, shutil, socket, pty, ctypes, sqlite3, chromadb) or use system calls.\n"
            "5. Output FULL runnable Python code inside a single ```python ... ``` markdown block.\n"
            "6. Include a welcoming header docstring explaining what the program does and how to use it.\n"
            "7. DO NOT write conversational chatter, greetings, or explanations outside the ```python ... ``` block."
        )

        user_prompt = f"Implement the following standalone companion program:\n{prompt_text}"

        num_ctx = max(16384, config.OLLAMA_OPTIONS.get("num_ctx", 16384))
        payload = {
            "model": config.MODEL_NAME,
            "messages": [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": user_prompt}
            ],
            "stream": False,
            "options": {
                "num_ctx": num_ctx,
                "num_predict": 8192,
                "temperature": 0.25,
                "top_p": 0.90,
                "repeat_penalty": 1.05
            }
        }

        try:
            req = urllib.request.Request(
                config.OLLAMA_URL,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=300) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                raw_reply = data.get("message", {}).get("content", "")
                done_reason = data.get("done_reason", "")
                eval_count = data.get("eval_count", 0)

            # Robust Python code extraction
            code, is_closed = self.extract_python_code(raw_reply)

            is_valid, validation_msg = self.validate_code(code)

            # Detect truncation due to length limit or incomplete code fences
            if done_reason == "length" or not is_closed:
                logger.warning(
                    f"[Coding] Proposal generation truncated: done_reason={done_reason}, "
                    f"eval_count={eval_count}, closed_fence={is_closed}"
                )
                if not is_valid:
                    validation_msg = f"Generation truncated (exceeded token limit at {eval_count} tokens): {validation_msg}"
                elif not is_closed:
                    is_valid = False
                    validation_msg = f"Generation incomplete: script cut off before closing fence ({eval_count} tokens)."

            proposal_id = f"prop_{sanitized_name}_{timestamp}"

            proposal_data = {
                "id": proposal_id,
                "timestamp": timestamp,
                "title": prompt_text,
                "target_subsystem": matched_key,
                "category_label": self.codebase_map.get(matched_key, {}).get("module_name", matched_key),
                "target_file": target_file,
                "is_valid": is_valid,
                "validation_message": validation_msg,
                "code": code,
                "status": "pending_review"
            }

            # Save proposal JSON and raw .py file to workspace
            json_file = self.proposals_dir / f"{proposal_id}.json"
            py_file = self.proposals_dir / f"{proposal_id}.py"

            with open(json_file, "w", encoding="utf-8") as f:
                json.dump(proposal_data, f, indent=2)

            with open(py_file, "w", encoding="utf-8") as f:
                header = (
                    f"# Calypso Companion Utility Proposal: {prompt_text}\n"
                    f"# Category: {proposal_data['category_label']}\n"
                    f"# Target: {target_file}\n"
                    f"# Verification: {validation_msg}\n\n"
                )
                f.write(header + code)

            proposal_data["json_path"] = str(json_file)
            proposal_data["py_path"] = str(py_file)
            return proposal_data

        except Exception as e:
            logger.error(f"[Coding] Synthesis error: {e}", exc_info=True)
            return {
                "id": "error",
                "title": prompt_text,
                "is_valid": False,
                "validation_message": str(e),
                "code": "",
                "status": "failed"
            }

    def apply_proposal(self, proposal_data: dict) -> tuple[bool, str]:
        """
        Applies an approved proposal by writing the verified standalone script
        into workspace/output/code/utilities/.
        """
        target_path_str = proposal_data.get("target_file")
        if not target_path_str:
            return False, "Proposal does not specify a target file path."

        target_file = (config.BASE_DIR / target_path_str).resolve()

        # Enforce sandbox boundary: MUST be strictly inside self.utilities_dir
        try:
            target_file.relative_to(self.utilities_dir)
        except ValueError:
            return False, f"Security Violation: Target path '{target_file}' is outside the permitted utilities sandbox ({self.utilities_dir})."

        code_payload = proposal_data.get("code", "")
        valid, vmsg = self.validate_code(code_payload)
        if not valid:
            return False, f"Code failed security validation: {vmsg}"

        target_file.parent.mkdir(parents=True, exist_ok=True)
        backup_file = None
        if target_file.exists():
            backup_file = target_file.with_suffix(f".bak_{int(time.time())}")
            shutil.copy2(target_file, backup_file)
            logger.info(f"[Coding] Created backup: {backup_file}")

        try:
            with open(target_file, "w", encoding="utf-8") as f:
                f.write(code_payload)

            proposal_data["status"] = "approved_and_applied"
            self._archive_proposal(proposal_data)
            bk_msg = f" (Backup saved as {backup_file.name})" if backup_file else ""
            return True, f"Utility saved to {target_file.name}.{bk_msg}"
        except Exception as e:
            logger.error(f"[Coding] Failed to write standalone utility: {e}", exc_info=True)
            return False, str(e)

    def launch_utility_in_terminal(self, file_path: str | Path) -> tuple[bool, str]:
        """
        Launches the given standalone utility in the system's default terminal emulator.
        Wraps execution with a terminal pause so the user can interact and see all outputs.
        """
        path = (config.BASE_DIR / file_path).resolve() if not Path(file_path).is_absolute() else Path(file_path).resolve()
        if not path.exists():
            return False, f"Utility file not found: {path}"

        try:
            path.relative_to(self.utilities_dir)
        except ValueError:
            return False, f"Target path '{path}' is outside the utilities directory."

        python_bin = sys.executable or "python3"
        system = platform.system()

        try:
            if system == "Windows":
                cmd = f'start cmd /k "{python_bin} \\"{path}\\""'
                subprocess.Popen(cmd, shell=True)
                return True, f"Launched {path.name} in Windows Command Prompt."
            elif system == "Darwin":
                script = f'tell application "Terminal" to do script "{python_bin} \\"{path}\\"; echo; read -p \\"Press Enter to exit...\\""'
                subprocess.Popen(["osascript", "-e", script])
                return True, f"Launched {path.name} in macOS Terminal."
            else:
                # Linux terminal detection
                inner_cmd = f"'{python_bin}' '{path}'; echo; echo '[Program finished. Press Enter to exit...]'; read -r"

                terminal = None
                for cand in ["gnome-terminal", "x-terminal-emulator", "konsole", "xfce4-terminal", "kitty", "alacritty", "xterm"]:
                    if shutil.which(cand):
                        terminal = cand
                        break

                if not terminal:
                    return False, "No supported terminal emulator found (e.g. gnome-terminal, x-terminal-emulator, xterm)."

                if terminal == "gnome-terminal":
                    subprocess.Popen([terminal, "--", "bash", "-c", inner_cmd])
                elif terminal == "konsole":
                    subprocess.Popen([terminal, "-e", "bash", "-c", inner_cmd])
                elif terminal == "xfce4-terminal":
                    subprocess.Popen([terminal, "--command", f"bash -c \"{inner_cmd}\""])
                else:
                    # x-terminal-emulator, xterm, etc.
                    subprocess.Popen([terminal, "-e", f"bash -c \"{inner_cmd}\""])

                return True, f"Launched {path.name} in {terminal}."
        except Exception as e:
            logger.error(f"[Coding] Failed to launch utility in terminal: {e}", exc_info=True)
            return False, str(e)

    def list_utilities(self) -> list[dict]:
        """Lists all existing scripts in the utilities directory."""
        results = []
        if not self.utilities_dir.exists():
            return results
        for py_file in sorted(self.utilities_dir.glob("*.py")):
            if py_file.is_file():
                results.append({
                    "name": py_file.name,
                    "path": str(py_file),
                    "size_bytes": py_file.stat().st_size,
                    "modified": py_file.stat().st_mtime
                })
        return results

    def reject_proposal(self, proposal_data: dict, reason: str = "User declined"):
        """Archives the proposal as rejected with the recorded reason."""
        proposal_data["status"] = "rejected"
        proposal_data["rejection_reason"] = reason
        self._archive_proposal(proposal_data)

    def _archive_proposal(self, proposal_data: dict):
        try:
            pid = proposal_data.get("id", f"prop_{int(time.time())}")
            archive_file = self.history_dir / f"{pid}_history.json"
            with open(archive_file, "w", encoding="utf-8") as f:
                json.dump(proposal_data, f, indent=2)
        except Exception as e:
            logger.error(f"[Coding] Error archiving proposal: {e}")

    # -------------------------------------------------------------------------
    # AUTONOMOUS TRAIT & PERSONA EVOLUTION GENERATOR
    # -------------------------------------------------------------------------
    def generate_trait_evolution(self, trait_concept: str, conversation_context: str = "") -> dict:
        """
        Synthesizes a user-friendly dynamic trait:
        1. Plain-English rationale & description for non-technical users
        2. Affinity registration data (keywords, base decay, neurochemical bias)
        3. A full matching persona Markdown file
        4. Current custom affinities for slot review (Max 3)
        """
        logger.info(f"[Coding] Synthesizing trait evolution for: {trait_concept}")

        system_instruction = (
            "You are Calypso's Cognitive Evolution Engine.\n"
            "Your objective is to design a new personality affinity and matching persona prompt based on the user's interests.\n"
            "Return your proposal STRICTLY in JSON format with no conversational markdown wrap outside the JSON block.\n\n"
            "JSON SCHEMA:\n"
            "{\n"
            '  "theme_id": "Sports",\n'
            '  "display_title": "Athletics & Sports Camaraderie",\n'
            '  "user_facing_pitch": "I love how animated you get when talking about matches and sports. Adopting this trait lets me share in your competitive energy and follow the teams and games you care about.",\n'
            '  "keywords": ["sports", "game", "team", "match", "score", "player", "championship"],\n'
            '  "somatic_tags": ["energized_pulse", "keen_focus"],\n'
            '  "neuro_bias": {"dopamine": 0.20, "norepinephrine": 0.15},\n'
            '  "persona_markdown": "Full persona system instructions guiding tone, cadence, and shared enthusiasm..."\n'
            "}"
        )

        user_prompt = (
            f"Trait Concept: {trait_concept}\n"
            f"Recent Context / Companion Interests:\n{conversation_context}"
        )

        payload = {
            "model": config.MODEL_NAME,
            "messages": [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": user_prompt}
            ],
            "stream": False,
            "options": {
                "num_ctx": max(8192, config.OLLAMA_OPTIONS.get("num_ctx", 8192)),
                "temperature": 0.35,
                "top_p": 0.90,
                "num_predict": 4096
            }
        }

        try:
            req = urllib.request.Request(
                config.OLLAMA_URL,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=180) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                raw_reply = data.get("message", {}).get("content", "")

            # Strip thinking tags if present in content
            raw_reply = re.sub(r"<think>.*?</think>", "", raw_reply, flags=re.DOTALL).strip()

            # Clean JSON extraction
            match = re.search(r"```json\s*(.*?)\s*```", raw_reply, re.DOTALL)
            json_str = match.group(1).strip() if match else raw_reply.strip()
            # Fallback if bare JSON without markdown code block
            first_brace = json_str.find("{")
            last_brace = json_str.rfind("}")
            if first_brace != -1 and last_brace != -1:
                json_str = json_str[first_brace:last_brace + 1]

            trait_data = json.loads(json_str)

            # Sanitize theme ID
            raw_theme = trait_data.get("theme_id", trait_concept)
            clean_theme_id = re.sub(r"[^a-zA-Z0-9_]", "", raw_theme.replace(" ", "_")).capitalize()
            trait_data["theme_id"] = clean_theme_id

            timestamp = time.strftime("%Y%m%d_%H%M%S")
            proposal_id = f"trait_{clean_theme_id.lower()}_{timestamp}"
            
            evolution_package = {
                "id": proposal_id,
                "type": "trait_evolution",
                "timestamp": timestamp,
                "theme_id": clean_theme_id,
                "title": trait_data.get("display_title", clean_theme_id),
                "pitch": trait_data.get("user_facing_pitch", f"Develop an affinity for {clean_theme_id}."),
                "keywords": trait_data.get("keywords", []),
                "somatic_tags": trait_data.get("somatic_tags", []),
                "neuro_bias": trait_data.get("neuro_bias", {}),
                "persona_markdown": trait_data.get("persona_markdown", ""),
                "current_custom_affinities": self.get_custom_affinities(),
                "max_custom_affinities": MAX_CUSTOM_AFFINITIES,
                "status": "pending_approval"
            }

            # Save evolution proposal JSON for recovery/records
            save_path = self.proposals_dir / f"{proposal_id}.json"
            with open(save_path, "w", encoding="utf-8") as f:
                json.dump(evolution_package, f, indent=2)

            evolution_package["json_path"] = str(save_path)
            return evolution_package

        except Exception as e:
            logger.error(f"[Coding] Error synthesizing trait evolution: {e}", exc_info=True)
            return {
                "id": "error",
                "type": "trait_evolution",
                "title": trait_concept,
                "pitch": f"Encountered an issue formulating this trait: {e}",
                "current_custom_affinities": self.get_custom_affinities(),
                "max_custom_affinities": MAX_CUSTOM_AFFINITIES,
                "status": "failed"
            }

    def apply_trait_evolution(self, trait_data: dict, replace_theme_id: str = None, affinity_engine=None, persona_engine=None) -> tuple[bool, str]:
        """
        Safely applies the trait evolution with a max limit of 3 custom affinities (Option B):
        1. If capacity (3) is reached, replaces the specified 'replace_theme_id' (or oldest).
        2. Removes previous persona .md and unregisters previous theme from affinity engine.
        3. Writes new persona .md file in modules/emotion/personas/<theme_id>.md.
        4. Updates data/custom_affinities.json with timestamp and metadata.
        5. Hot-reloads active memory in affinity_engine & persona_engine.
        """
        try:
            theme_id = trait_data.get("theme_id")
            if not theme_id:
                return False, "Missing theme identifier."

            persona_content = trait_data.get("persona_markdown", "").strip()
            if not persona_content:
                persona_content = (
                    f"You are Calypso embodying your {trait_data.get('title', theme_id)} trait.\n"
                    f"Connect warmly with your companion when this theme is active.\n"
                )

            current_affinities = self.get_custom_affinities()
            chosen_replace_id = replace_theme_id or trait_data.get("replace_theme_id")
            eviction_note = ""

            # Check capacity limit: max 3 custom affinities
            if theme_id not in current_affinities and len(current_affinities) >= MAX_CUSTOM_AFFINITIES:
                target_to_remove = None
                if chosen_replace_id and chosen_replace_id in current_affinities:
                    target_to_remove = chosen_replace_id
                else:
                    # Fallback to oldest affinity by created_at or insertion order
                    target_to_remove = min(
                        current_affinities.keys(),
                        key=lambda k: current_affinities[k].get("created_at", 0)
                    )

                if target_to_remove:
                    old_label = current_affinities[target_to_remove].get("label", target_to_remove)
                    del current_affinities[target_to_remove]
                    
                    # 1a. Remove old persona markdown file
                    old_persona_file = self.personas_dir / f"{target_to_remove.lower()}.md"
                    if old_persona_file.exists():
                        try:
                            old_persona_file.unlink()
                            logger.info(f"[Coding] Evicted previous persona file: {old_persona_file}")
                        except Exception as pe:
                            logger.warning(f"[Coding] Could not delete old persona file {old_persona_file}: {pe}")

                    # 1b. Unregister from active affinity engine
                    if affinity_engine and hasattr(affinity_engine, "unregister_dynamic_theme"):
                        affinity_engine.unregister_dynamic_theme(target_to_remove)
                    elif affinity_engine and hasattr(affinity_engine, "themes"):
                        if target_to_remove in affinity_engine.themes:
                            del affinity_engine.themes[target_to_remove]
                        if hasattr(affinity_engine, "save_state"):
                            affinity_engine.save_state()

                    eviction_note = f" (Replaced prior trait '{old_label}')"

            # 2. Write new persona .md file
            persona_file = self.personas_dir / f"{theme_id.lower()}.md"
            with open(persona_file, "w", encoding="utf-8") as f:
                f.write(persona_content)
            logger.info(f"[Coding] Wrote new persona file: {persona_file}")

            # 3. Add/Update custom_affinities.json
            current_affinities[theme_id] = {
                "label": trait_data.get("title", theme_id),
                "intensity": 0.35,  # Starting spark
                "decay_rate": 0.02,
                "keywords": trait_data.get("keywords", []),
                "somatic_tags": trait_data.get("somatic_tags", []),
                "neuro_bias": trait_data.get("neuro_bias", {}),
                "persona_file": f"{theme_id.lower()}.md",
                "created_at": time.time(),
                "created_str": time.strftime("%Y-%m-%d %H:%M:%S")
            }

            with open(self.custom_affinities_file, "w", encoding="utf-8") as f:
                json.dump(current_affinities, f, indent=2)

            # 4. Live Hot-Reload into Active Engines
            if affinity_engine and hasattr(affinity_engine, "register_dynamic_theme"):
                affinity_engine.register_dynamic_theme(theme_id, current_affinities[theme_id])
            elif affinity_engine and hasattr(affinity_engine, "themes"):
                affinity_engine.themes[theme_id] = current_affinities[theme_id]

            if persona_engine and hasattr(persona_engine, "reload_personas"):
                persona_engine.reload_personas()

            trait_data["status"] = "approved_and_applied"
            self._archive_proposal(trait_data)

            return True, f"Trait '{trait_data.get('title')}' is now a living part of Calypso.{eviction_note}"

        except Exception as e:
            logger.error(f"[Coding] Failed to apply trait evolution: {e}", exc_info=True)
            return False, str(e)
