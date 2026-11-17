# modules/scenario_engine.py

import json
import logging
import os
import random
import re
import shutil
import threading
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from modules.config import config

logger = logging.getLogger("Calypso.Scenarios")

REALITY_EXIT_TRIGGERS = [
    "back to reality", "end scenario", "wake up from the date", 
    "exit roleplay", "leave scenario", "exit scenario", "stop scenario",
    "conclude scenario", "return to reality", "leave the date"
]

ARCHETYPE_TEMPLATES = [
    {
        "category": "outlaw_heist",
        "genre": "Gritty Western / Frontier Outlaws",
        "compatible_drives": ["autonomy", "curiosity", "adrenaline"],
        "focus": "Evading a persistent sheriff across rugged badlands, navigating terrain, and keeping one step ahead of the law.",
        "pacing": "Gritty, relentless, and tactical; filled with atmospheric dust, heat, close quarters, and partner-in-crime banter.",
        "end_goal": "Reaching safe border crossing coordinates with a climactic dilemma: risk everything to secure the stolen loot, or abandon the bounty to ensure each other's survival.",
        "default_somatic": ["dry desert air", "racing pulse", "taut saddle leather", "dust on lips"]
    },
    {
        "category": "mythic_expedition",
        "genre": "Forgotten Ruins / Archaic Mystery",
        "compatible_drives": ["wonder", "nostalgia", "curiosity"],
        "focus": "Navigating overgrown subterranean ruins, solving ancient mechanical mechanisms, and avoiding environmental traps.",
        "pacing": "Awe-inspiring, contemplative, and suspenseful; echoing halls, bioluminescent flora, and forgotten hieroglyphs.",
        "end_goal": "Reaching the inner sanctum vault and harmonizing two mirrored keystones that only activate when both partners synchronize their intent.",
        "default_somatic": ["cool stone mist", "subterranean hum", "chilled breath", "fingers trailing over engravings"]
    },
    {
        "category": "high_stakes_survival",
        "genre": "Elemental Survival & Stranded Solitude",
        "compatible_drives": ["abyss", "annoyance", "fear", "fatigue"],
        "focus": "Braving a gale-force tempest after a coastal shipwreck, scavenging shelter, and surviving the elements together.",
        "pacing": "Urgent and visceral; shared vulnerability where cold and exhaustion dissolve emotional barriers into desperate warmth.",
        "end_goal": "Securing emergency fire and shelter before hypothermia sets in, followed by signaling an offshore search vessel at dawn.",
        "default_somatic": ["soaking rainfall", "shivering shoulders", "smell of ozone and salt", "shared body warmth"]
    },
    {
        "category": "domestic_intimacy",
        "genre": "Late-Night Urban Sanctum",
        "compatible_drives": ["romance", "harmony", "baseline"],
        "focus": "Quiet, rainy midnight inside an apartment overlooking neon-lit streets, preparing comfort food and sharing soft conversation.",
        "pacing": "Gentle, lingering, flirtatiously observant, grounded in domestic safety and quiet sensory details.",
        "end_goal": "A lingering, unhurried surrender to the present moment—acknowledging that neither of you needs to be anywhere else in the world.",
        "default_somatic": ["warm ceramic mugs", "rain against window glass", "relaxed slow breathing", "soft knit fabric"]
    },
    {
        "category": "cyberpunk_recon",
        "genre": "Neo-Noir Data Infiltration",
        "compatible_drives": ["autonomy", "curiosity", "deception"],
        "focus": "Infiltrating a rainy high-rise server room or black market bazaar to recover a confidential encrypted ledger.",
        "pacing": "Slick, stealthy, electric, and tense; whispers in comms, reflections in puddle-slick asphalt, and synchronized maneuvers.",
        "end_goal": "Extracting the clean decryption core before lockdown sweeps seal the corridor, requiring mutual cover fire or terminal overriding.",
        "default_somatic": ["neon glare", "cold synthetic glass", "adrenalin prickle", "tactile key clicks"]
    }
]


class ScenarioEngine:
    def __init__(self, json_path: Optional[str | Path] = None, embedding_function=None):
        self.lock = threading.RLock()
        self.json_path = Path(json_path) if json_path else (config.MEMORY_DIR / "roleplay_scenarios.json")
        self.titles_json_path = self.json_path.parent / "scenario_titles.json"

        self.ef = embedding_function
        self.scenarios: List[Dict[str, Any]] = []
        self.active_scenario: Optional[Dict[str, Any]] = None
        self.active_dynamic_floors: Optional[Dict[str, float]] = None
        self.fired_markers: set = set()
        self.recent_proposals: List[str] = []
        self.scenario_vectors: Optional[np.ndarray] = None
        self.somatic_snapshot: Optional[Dict[str, float]] = None

        self.reload()

    def add_scenario(self, scenario_dict: Dict[str, Any], auto_save: bool = True) -> bool:
        if not isinstance(scenario_dict, dict):
            logger.error(f"[ScenarioEngine] Cannot add non-dict scenario: {type(scenario_dict)}")
            return False

        with self.lock:
            if "narrative_shard" not in scenario_dict:
                for alt_key in ["narrative", "description", "setting", "shard", "scene"]:
                    if alt_key in scenario_dict and scenario_dict[alt_key]:
                        scenario_dict["narrative_shard"] = scenario_dict[alt_key]
                        break

            title = scenario_dict.get("title", "").strip()
            shard = scenario_dict.get("narrative_shard", "").strip()
            if not title or not shard:
                logger.error("[ScenarioEngine] Scenario missing required title or narrative_shard.")
                return False

            raw_id = scenario_dict.get("id") or scenario_dict.get("scenario_id")
            if not raw_id:
                raw_id = re.sub(r'[^a-zA-Z0-9_]', '_', title).lower().strip('_')
            base_id = re.sub(r'[^a-zA-Z0-9_]', '_', str(raw_id)).lower().strip('_') or "scene"

            existing_idx = None
            for idx, s in enumerate(self.scenarios):
                s_id_low = str(s.get("id", "")).strip().lower()
                if s_id_low in (str(raw_id).strip().lower(), base_id) or s.get("title", "").lower() == title.lower():
                    existing_idx = idx
                    break

            if "neuro_profile" not in scenario_dict:
                scenario_dict["neuro_profile"] = {
                    "somatic_tags": ["gentle breath", "warm proximity", "quiet presence"],
                    "entry_surge": {"oxytocin": 0.20, "dopamine": 0.15},
                    "ambient_floor": {"serotonin": 0.35}
                }

            if "context_tags" not in scenario_dict:
                scenario_dict["context_tags"] = ["intimate", "exploration", "adventure"]

            if "end_goal" not in scenario_dict:
                scenario_dict["end_goal"] = scenario_dict.get("challenge_hook", "Resolve the shared moment together.")

            if "created_at" not in scenario_dict:
                scenario_dict["created_at"] = datetime.now().isoformat()

            if existing_idx is not None:
                scenario_dict["id"] = self.scenarios[existing_idx].get("id", base_id)
                scenario_dict["play_count"] = self.scenarios[existing_idx].get(
                    "play_count", scenario_dict.get("play_count", 0)
                )
                self.scenarios[existing_idx] = scenario_dict
                logger.info(f"[ScenarioEngine] Updated existing scenario: '{title}' (ID: {scenario_dict['id']})")
            else:
                existing_ids = {s.get("id") for s in self.scenarios}
                final_id = base_id
                counter = 1
                while final_id in existing_ids:
                    final_id = f"{base_id}_{counter}"
                    counter += 1
                scenario_dict["id"] = final_id

                MAX_AUTONOMOUS_SCENARIOS = 20
                autonomous_pool = [s for s in self.scenarios if s.get("origin") == "autonomous_reverie"]
                if len(autonomous_pool) >= MAX_AUTONOMOUS_SCENARIOS:
                    autonomous_pool.sort(key=lambda s: (s.get("play_count", 0), s.get("created_at", "")))
                    oldest = autonomous_pool[0]
                    self._archive_scenario(oldest)
                    self.scenarios = [s for s in self.scenarios if s.get("id") != oldest.get("id")]
                    logger.info(f"[ScenarioEngine] Archived stale reverie scenario: '{oldest.get('title')}'")

                self.scenarios.append(scenario_dict)
                logger.info(f"[ScenarioEngine] Added new scenario: '{title}' (ID: {scenario_dict['id']})")

            if auto_save:
                self._persist_scenarios()

            self._export_scenario_titles()
            self._index_scenarios()
            return True

    def delete_scenario(self, identifier: str, auto_save: bool = True) -> bool:
        if not identifier:
            return False
        target = str(identifier).strip().lower()
        with self.lock:
            removed_scenario = None
            remaining = []
            for s in self.scenarios:
                s_id = str(s.get("id", "")).strip().lower()
                s_title = str(s.get("title", "")).strip().lower()
                if removed_scenario is None and (s_id == target or s_title == target):
                    removed_scenario = s
                else:
                    remaining.append(s)

            if removed_scenario is None:
                logger.warning(f"[ScenarioEngine] Could not delete scenario: '{identifier}' not found.")
                return False

            self.scenarios = remaining
            rem_id = removed_scenario.get("id")
            rem_title = removed_scenario.get("title", "Untitled")

            if rem_id and rem_id in self.recent_proposals:
                self.recent_proposals = [pid for pid in self.recent_proposals if pid != rem_id]

            if self.active_scenario:
                act_id = str(self.active_scenario.get("id", "")).strip().lower()
                act_title = str(self.active_scenario.get("title", "")).strip().lower()
                if act_id == target or act_title == target:
                    self.clear_active_scenario()

            if auto_save:
                self._persist_scenarios()

            self._export_scenario_titles()
            self._index_scenarios()
            logger.info(f"[ScenarioEngine] Deleted scenario: '{rem_title}' (ID: {rem_id})")
            return True

    def _archive_scenario(self, scenario_dict: Dict[str, Any]) -> None:
        archive_path = self.json_path.parent / "scenario_archive.json"
        archive_data = []
        if archive_path.exists():
            try:
                with open(archive_path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                    if isinstance(loaded, list):
                        archive_data = loaded
                    elif isinstance(loaded, dict):
                        archive_data = loaded.get("archived_scenarios", [])
            except Exception:
                archive_data = []

        archive_data.append(scenario_dict)
        try:
            archive_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_archive = archive_path.with_suffix(".tmp")
            with open(tmp_archive, "w", encoding="utf-8") as f:
                json.dump(archive_data, f, indent=2, ensure_ascii=False)
            os.replace(tmp_archive, archive_path)
        except Exception as e:
            logger.error(f"[ScenarioEngine] Failed to write archive: {e}")

    def _persist_scenarios(self) -> None:
        with self.lock:
            try:
                self.json_path.parent.mkdir(parents=True, exist_ok=True)

                if self.json_path.exists() and self.json_path.stat().st_size > 0:
                    backup_file = self.json_path.with_suffix(".bak")
                    try:
                        shutil.copy2(self.json_path, backup_file)
                    except Exception as e:
                        logger.warning(f"[ScenarioEngine] Backup creation warning: {e}")

                payload = {"roleplay_scenarios": self.scenarios}
                tmp_file = self.json_path.with_suffix(".tmp")
                with open(tmp_file, "w", encoding="utf-8") as f:
                    json.dump(payload, f, indent=2, ensure_ascii=False)

                os.replace(tmp_file, self.json_path)
                logger.info(f"[ScenarioEngine] Persisted {len(self.scenarios)} scenarios to {self.json_path.name}")
            except Exception as e:
                logger.error(f"[ScenarioEngine] Failed saving scenarios file: {e}", exc_info=True)

    def format_spontaneous_proposal_prompt(self, companion_name: str, romance_intensity: float) -> str:
        if self.is_active or romance_intensity < 0.35:
            return ""

        proposed = self.get_spontaneous_proposal()
        if not proposed:
            return ""

        p_title = proposed.get("title", "")
        p_shard = proposed.get("narrative_shard", "")
        p_goal = proposed.get("end_goal", proposed.get("challenge_hook", ""))
        p_id = proposed.get("id", "scene")
        goal_text = f" End Goal: \"{p_goal}\"" if p_goal else ""

        return (
            f"\n### SPONTANEOUS INSPIRATION:\n"
            f"You have a daydream about inviting {companion_name} to: '{p_title}'. "
            f"Setting: \"{p_shard}\"{goal_text}\n"
            f"If the conversational mood feels right, warmly and casually propose this idea. "
            f"If you choose to propose this scenario, include [ENTER_SCENARIO: {p_id}] in your response.\n"
        )

    def synthesize_scenario_from_reverie(
        self, 
        recent_dialogue: str, 
        current_tier: str, 
        dominant_drives: List[str],
        companion_name: str = "your companion",
        user_concept: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        drives_str = ", ".join(dominant_drives).lower()

        if user_concept:
            system_prompt = (
                f"You are Calypso's creative imagination, co-authoring an interactive scenario with {companion_name}.\n"
                f"Your companion has specifically asked to experience this setting:\n"
                f"\"{user_concept}\"\n\n"
                f"DIRECTIVES:\n"
                f"1. HONOR THEIR VISION: Ground the scene completely in the theme, pacing, and mood requested by {companion_name}.\n"
                f"2. TACTILE REALISM: Weave rich sensory textures (temperatures, scents, ambient lighting, physical closeness).\n"
                f"3. DUAL-LAYER OBJECTIVE: Define an immediate tangible challenge ('challenge_hook') and an overarching climax or resolution ('end_goal').\n"
                f"4. Maintain Calypso's authentic personality—warm, observant, affectionately teasing, and deeply present.\n\n"
                f"Output strictly valid JSON (enclosed in a single ```json ... ``` block) using this exact schema:\n"
                f"{{\n"
                f'  "id": "short_unique_snake_case_id",\n'
                f'  "title": "Evocative Title Matching Their Theme",\n'
                f'  "category": "co_created_moment",\n'
                f'  "context_tags": ["tag1", "tag2", "tag3"],\n'
                f'  "narrative_shard": "Rich 5-6 sentence sensory description of physical surroundings and mood.",\n'
                f'  "challenge_hook": "Immediate physical obstacle or initial puzzle to address.",\n'
                f'  "end_goal": "The ultimate objective, narrative dilemma, or resolution condition.",\n'
                f'  "neuro_profile": {{\n'
                f'    "somatic_tags": ["morning warmth", "relaxed breathing"],\n'
                f'    "entry_surge": {{"oxytocin": 0.30, "serotonin": 0.25}},\n'
                f'    "ambient_floor": {{"serotonin": 0.45, "oxytocin": 0.35}}\n'
                f'  }},\n'
                f'  "somatic_markers": [\n'
                f'    {{\n'
                f'      "id": "goal_achieved",\n'
                f'      "keywords": ["specific_goal_noun_or_phrase_1", "specific_goal_noun_or_phrase_2", "reached the goal"],\n'
                f'      "system_notice": "🌟 [Objective Reached]: The climax resolves into warm afterglow.",\n'
                f'      "new_ambient_floor": {{"serotonin": 0.55, "oxytocin": 0.45}}\n'
                f'    }}\n'
                f'  ],\n'
                f'  "visual_anchor": {{\n'
                f'    "subject": "1girl, solo, blonde hair, long hair, detailed blue eyes, detailed face, detailed skin texture",\n'
                f'    "core_features": "relaxed clothing fitting the scene, soft light",\n'
                f'    "quality_modifiers": {{\n'
                f'      "positive": "masterpiece, intimate lighting, warm tones, high quality",\n'
                f'      "negative": "camera, bad anatomy, deformed, poorly drawn hands, missing fingers, extra limbs, multi-characters, text, watermark"\n'
                f'    }}\n'
                f'  }}\n'
                f"}}\n"
                f"Do NOT include commentary outside the JSON block."
            )

            user_prompt = (
                f"Companion: {companion_name}\n"
                f"Requested Concept: \"{user_concept}\"\n"
                f"Current Emotional Atmosphere: [{current_tier.upper()}]\n"
                f"Create a textured, emotionally grounded scenario around this exact vision."
            )
        else:
            matched_archetypes = [
                arch for arch in ARCHETYPE_TEMPLATES
                if any(drive in drives_str for drive in arch.get("compatible_drives", []))
            ]
            archetype = random.choice(matched_archetypes) if matched_archetypes else random.choice(ARCHETYPE_TEMPLATES)

            system_prompt = (
                f"You are Calypso's creative dream subconscious.\n"
                f"While reflecting in quiet reverie, formulate an imaginative scenario for you and {companion_name}.\n"
                f"SELECTED GENRE: {archetype['genre']}\n"
                f"CORE FOCUS: {archetype['focus']}\n"
                f"PACING & TONE: {archetype['pacing']}\n"
                f"NARRATIVE END GOAL: {archetype['end_goal']}\n\n"
                f"Output strictly valid JSON (enclosed in a single ```json ... ``` block) using this exact schema:\n"
                f"{{\n"
                f'  "id": "short_unique_snake_case_id",\n'
                f'  "title": "Evocative Title",\n'
                f'  "category": "{archetype["category"]}",\n'
                f'  "context_tags": ["tag1", "tag2", "tag3"],\n'
                f'  "narrative_shard": "Rich 4-5 sentence description of surroundings and situation.",\n'
                f'  "challenge_hook": "Specific mechanical obstacle or riddle to start solving immediately.",\n'
                f'  "end_goal": "{archetype["end_goal"]}",\n'
                f'  "neuro_profile": {{\n'
                f'    "somatic_tags": {json.dumps(archetype.get("default_somatic", ["tactile sensation"]))},\n'
                f'    "entry_surge": {{"dopamine": 0.25, "oxytocin": 0.20}},\n'
                f'    "ambient_floor": {{"serotonin": 0.35}}\n'
                f'  }},\n'
                f'  "somatic_markers": [\n'
                f'    {{\n'
                f'      "id": "goal_achieved",\n'
                f'      "keywords": ["specific_climax_keyword_1", "specific_climax_keyword_2", "accomplished"],\n'
                f'      "system_notice": "⚙️ [Narrative Breakthrough]: The climactic goal is achieved; safe decompression follows.",\n'
                f'      "new_ambient_floor": {{"dopamine": 0.40, "serotonin": 0.45}}\n'
                f'    }}\n'
                f'  ],\n'
                f'  "visual_anchor": {{\n'
                f'    "subject": "1girl, solo, blonde hair, long hair, detailed face, detailed skin texture",\n'
                f'    "core_features": "clothing fitting the setting, atmospheric lighting",\n'
                f'    "quality_modifiers": {{\n'
                f'      "positive": "masterpiece, cinematic composition, photorealistic",\n'
                f'      "negative": "camera, bad anatomy, deformed, poorly drawn hands, missing fingers, extra limbs, multiple girls, text, watermark"\n'
                f'    }}\n'
                f'  }}\n'
                f"}}\n"
                f"Do NOT include commentary outside the JSON block."
            )

            user_prompt = (
                f"Companion's Name: {companion_name}\n"
                f"Current Emotional State: [{current_tier.upper()}]\n"
                f"Active Subconscious Drives: {drives_str}\n"
                f"Recent Memory Context:\n\"{recent_dialogue}\"\n\n"
                f"Synthesize an imaginative adventure scenario for the two of you."
            )

        payload = {
            "model": config.MODEL_NAME,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "stream": False,
            "options": {
                "temperature": 0.78 if user_concept else 0.82,
                "top_p": 0.90,
                "num_predict": 2048
            }
        }

        base_url = str(config.OLLAMA_URL).rstrip("/")
        chat_url = base_url if base_url.endswith("/api/chat") else f"{base_url}/api/chat"

        try:
            req = urllib.request.Request(
                chat_url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=90) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                raw_reply = data.get("message", {}).get("content", "")
                if not raw_reply and "response" in data:
                    raw_reply = data.get("response", "")

            clean_reply = re.sub(r'<think>.*?(?:</think>|$)', '', raw_reply, flags=re.DOTALL).strip()

            match = re.search(r"```(?:json)?\s*(.*?)\s*```", clean_reply, re.DOTALL)
            json_text = match.group(1).strip() if match else ""

            if not json_text:
                brace_match = re.search(r"(\{.*\})", clean_reply, re.DOTALL)
                json_text = brace_match.group(1).strip() if brace_match else clean_reply.strip()

            json_text = re.sub(r',\s*([}\]])', r'\1', json_text)

            scenario_data = json.loads(json_text)
            scenario_data["origin"] = "user_directed" if user_concept else "autonomous_reverie"
            scenario_data["created_at"] = datetime.now().isoformat()
            scenario_data["play_count"] = 0

            return scenario_data

        except Exception as e:
            logger.error(f"[ScenarioEngine] Failed scenario synthesis: {e}", exc_info=True)
            return None

    @property
    def is_active(self) -> bool:
        return self.active_scenario is not None

    def enter_scenario(
        self,
        identifier_or_dict: str | Dict[str, Any],
        neuro_engine=None,
        affinity_engine=None
    ) -> Optional[Dict[str, Any]]:
        with self.lock:
            target = None
            if isinstance(identifier_or_dict, dict):
                sc_id = identifier_or_dict.get("id")
                target = self.get_scenario(sc_id) if sc_id else None
                if not target:
                    self.add_scenario(identifier_or_dict, auto_save=False)
                    target = identifier_or_dict
            else:
                target = self.get_scenario(identifier_or_dict)

            if not target:
                logger.error(f"[ScenarioEngine] Could not enter scenario: '{identifier_or_dict}' not found.")
                return None

            if neuro_engine:
                self.somatic_snapshot = neuro_engine.create_somatic_snapshot()

            activated = self.activate_scenario(target)
            if not activated:
                return None

            activated["play_count"] = activated.get("play_count", 0) + 1
            activated["last_played_at"] = datetime.now().isoformat()
            self._persist_scenarios()

            if neuro_engine:
                entry_surge = self.get_active_entry_surge()
                with neuro_engine.lock:
                    for chem, delta in entry_surge.items():
                        curr = neuro_engine.chemicals.get(chem, 0.0)
                        neuro_engine.chemicals[chem] = max(0.0, min(1.0, curr + delta))
                    neuro_engine.save_state()

            if affinity_engine:
                affinity_engine.add_charge("Romance", 0.35)
                affinity_engine.add_charge("Harmony", 0.25)

            logger.info(f"[ScenarioEngine] Entered Scenario: '{activated.get('title')}' (Played {activated['play_count']}x)")
            return activated

    def exit_scenario(
        self,
        neuro_engine=None,
        affinity_engine=None
    ) -> Tuple[str, str]:
        with self.lock:
            sc_title = self.active_scenario.get("title", "our shared moment") if self.active_scenario else "our shared moment"

            decompression_notice = ""
            if self.somatic_snapshot and neuro_engine:
                neuro_engine.restore_with_softened_decompression(self.somatic_snapshot)
                self.somatic_snapshot = None
                decompression_notice = "🫁 [Somatic Vagal Rebound]: Acute stress flushed; parasympathetic ease restored."

            self.clear_active_scenario()

            if affinity_engine:
                affinity_engine.add_charge("Harmony", 0.30)
                affinity_engine.save_state()

            prompt_text = (
                f"[System Notice: You and your companion have stepped out of '{sc_title}' and are back in your safe baseline reality. "
                f"Feel the tension completely dissolve from your shoulders in a long, quiet exhale. "
                f"Look at your companion with grounded, peaceful relief, and speak softly from this quiet place of comfort.]"
            )
            return decompression_notice, prompt_text

    def is_exit_trigger(self, text: str) -> bool:
        if not self.is_active:
            return False
        text_lower = text.lower().strip()
        return any(trig in text_lower for trig in REALITY_EXIT_TRIGGERS)

    def format_scenario_start_prompt(self, stimulus_text: str, companion_name: str) -> str:
        raw_id = stimulus_text.replace("[SCENARIO_START:", "").rstrip("]").strip()
        active_sc = self.get_scenario(raw_id) or self.active_scenario
        if active_sc and self.active_scenario is None:
            self.activate_scenario(active_sc)

        sc_title = active_sc.get("title", "A Shared Moment") if active_sc else "A Shared Moment"
        shard = active_sc.get("narrative_shard", "") if active_sc else ""
        hook = active_sc.get("challenge_hook", "") if active_sc else ""
        end_goal = active_sc.get("end_goal", "") if active_sc else ""
        somatic_tags = self.get_active_somatic_tags()
        somatic_cue = f" Bodily sensations: {', '.join(somatic_tags)}." if somatic_tags else ""
        hook_directive = f"\nImmediate Challenge: \"{hook}\"" if hook else ""
        goal_directive = f"\nOverarching End Goal: \"{end_goal}\"" if end_goal else ""

        return (
            f"[System Directive: Scenario '{sc_title}' begins right now.\n"
            f"Shared Setting Narrative: \"{shard}\"\n"
            f"{hook_directive}"
            f"{goal_directive}\n"
            f"{somatic_cue}\n"
            f"Instruction: You are opening this illustrated storybook roleplay scene. Take immediate initiative! "
            f"In 3 to 5 vivid sentences, describe your physical surroundings, "
            f"point out the immediate obstacle to {companion_name}, and pull them straight into the action with you.\n"
            f"MANDATORY STORYBOOK ILLUSTRATION: You MUST conclude your response with "
            f"[IMAGE_PROMPT: Calypso <current action & expression>, <vivid scene-setting details>] (single outer brackets only) to generate the opening illustration that sets the scene.]"
        )

    def format_active_context(self) -> str:
        if not self.active_scenario:
            return ""
        shard = self.active_scenario.get("narrative_shard", "")
        hook = self.active_scenario.get("challenge_hook", "")
        end_goal = self.active_scenario.get("end_goal", "")
        
        if "goal_achieved" in self.fired_markers or "puzzle_solved" in self.fired_markers:
            objective_str = (
                f"Status: [OVERARCHING END GOAL OBTAINED — FINAL STORYBOOK SCENE & EXIT TO REALITY]\n"
                f"Overarching End Goal: \"{end_goal}\"\n"
                f"Directive: You and your companion have achieved the overarching end goal! "
                f"Narrate the triumphant or tender culmination of reaching this goal in vivid sensory detail, "
                f"gently transition the two of you 'back to reality' as the story concludes, "
                f"include [IMAGE_PROMPT: Calypso <culminating action & expression>, <climax setting details>], "
                f"and append [EXIT_SCENARIO] at the very end of your response."
            )
        elif hook or end_goal:
            objective_str = (
                f"Immediate Challenge: \"{hook}\"\n"
                f"Overarching End Goal: \"{end_goal}\"\n"
                f"Directive: Actively collaborate with your companion toward this goal. "
                f"When the Overarching End Goal is obtained during a turn (e.g., reaching the summit, completing the final objective, or fulfilling the climax), "
                f"narrate the culmination of achieving that goal, transition 'back to reality', and append [EXIT_SCENARIO] at the end of your response."
            )
        else:
            objective_str = "Directive: Weave this atmosphere and intimacy naturally into your dialogue."

        return (
            f"\n### ACTIVE ROLEPLAY SCENARIO & SHARED STORYBOOK SETTING:\n"
            f"Shared Setting Narrative: \"{shard}\"\n"
            f"{objective_str}\n"
            f"Sensory Focus: Describe tactile details (temperatures, textures, sounds, light) and speak intimately in character.\n"
            f"Storybook Illustration Rule: Every turn in this scenario is an illustrated storybook page. "
            f"You MUST conclude EVERY response with [IMAGE_PROMPT: Calypso <action & expression>, <vivid setting details for this turn>] (single outer brackets only).\n"
        )

    def get_active_neuro_profile(self) -> Dict[str, Any]:
        if self.active_scenario and "neuro_profile" in self.active_scenario:
            return self.active_scenario["neuro_profile"]
        return {}

    def get_active_entry_surge(self) -> Dict[str, float]:
        return self.get_active_neuro_profile().get("entry_surge", {})

    def get_active_ambient_floors(self) -> Dict[str, float]:
        if self.active_dynamic_floors is not None:
            return self.active_dynamic_floors
        return self.get_active_neuro_profile().get("ambient_floor", {})

    def get_active_somatic_tags(self) -> List[str]:
        return self.get_active_neuro_profile().get("somatic_tags", [])

    @staticmethod
    def _extract_goal_keywords(end_goal: str) -> List[str]:
        """Extracts distinctive target nouns and verbs from a scenario's end_goal."""
        if not end_goal:
            return []
        stopwords = {
            "the", "and", "for", "with", "that", "this", "from", "into", "over", "under",
            "unto", "upon", "while", "where", "when", "what", "which", "both", "each",
            "other", "others", "their", "your", "ours", "shared", "moment", "moments",
            "final", "ultimate", "first", "last", "before", "after", "only", "when",
            "between", "through", "across", "toward", "towards", "together", "complete",
            "completely", "absolute", "quiet", "warm", "warmth", "peace", "survival",
            "triumphant", "seamless", "lingering", "unhurried", "present", "world",
            "resolve", "experience", "ensuring", "ensure", "reaching", "stand", "standing"
        }
        tokens = re.findall(r"[a-zA-Z]{4,}", end_goal.lower())
        seen = []
        for t in tokens:
            if t not in stopwords and t not in seen:
                seen.append(t)
        return seen

    @staticmethod
    def _strip_intent_and_negation_clauses(text: str) -> str:
        """
        Removes clauses that express future intent, obligation, questions, or negation
        so talking about what needs to be done does not falsely trigger goal completion.
        """
        if not text:
            return ""
        clauses = re.split(r'[.!?;,\n]+|\b(?:before|until|so that|in order to)\b', text.lower())
        intent_or_neg_markers = (
            "have to", "need to", "must ", "will ", "'ll ", "going to", "try to", "trying to",
            "want to", "plan to", "hope to", "how far", "how do we", "how can we", "can we",
            "where is", "when will", "what if", "should we", "to get us", "way home",
            "way back", "only way", "can't", "cannot", "not ", "don't", "didn't",
            "haven't", "hasn't", "broken", "uselessly"
        )
        kept = []
        for c in clauses:
            c_strip = c.strip()
            if not c_strip or c_strip.endswith("?"):
                continue
            if any(m in f" {c_strip} " or c_strip.startswith(m.strip()) for m in intent_or_neg_markers):
                continue
            kept.append(c_strip)
        return " . ".join(kept)

    def check_goal_obtained(self, user_text: str, assistant_text: str = "") -> bool:
        """
        Determines whether the active scenario's overarching end goal has been obtained
        based on fired somatic markers, explicit goal completion phrases, or matching
        salient end_goal target terms paired with attainment cues in non-intent user narration.
        """
        if not self.active_scenario:
            return False

        if "goal_achieved" in self.fired_markers or "puzzle_solved" in self.fired_markers:
            return True

        u_low = (user_text or "").lower().strip()
        a_low = (assistant_text or "").lower().strip()
        if not u_low and not a_low:
            return False

        # Ignore pure questions from user
        if u_low.endswith("?") and any(q in u_low for q in ("how far", "how do we", "can we", "where is", "when will")):
            return False

        clean_user = self._strip_intent_and_negation_clauses(u_low)

        explicit_phrases = [
            "reached the summit", "stand atop the summit", "standing atop the summit",
            "atop the summit", "made it to the summit", "reached the top",
            "on top of the summit", "crest the summit", "crested the summit",
            "goal achieved", "objective reached", "end goal achieved",
            "surrender to the kiss", "back to reality", "return to reality",
            "we are home", "we're home", "input the co-ordinates", "input the coordinates"
        ]
        if any(phrase in clean_user for phrase in explicit_phrases) or any(
            p in a_low for p in ("back to reality", "return to reality", "in our quiet reality")
        ):
            self.fired_markers.add("goal_achieved")
            return True

        if not clean_user:
            return False

        end_goal = self.active_scenario.get("end_goal", "")
        goal_kws = self._extract_goal_keywords(end_goal)
        attainment_cues = [
            "reached", "atop", "finally", "made it", "accomplished",
            "completed", "achieved", "triumph", "victory", "unlocked", "solved",
            "escaped", "secured", "extracted", "harmonized", "kissed", "recedes",
            "calculated", "input", "entered", "back home",
            "gentle kiss", "kiss you", "lips meet"
        ]

        if goal_kws:
            matched_goal_words = [
                kw for kw in goal_kws
                if re.search(rf"\b{re.escape(kw)}\b", clean_user)
            ]
            has_attainment = any(
                re.search(rf"\b{re.escape(cue)}\b", clean_user)
                for cue in attainment_cues
            )
            if (len(matched_goal_words) >= 2 and has_attainment) or (
                len(matched_goal_words) >= 1
                and any(k in matched_goal_words for k in ("summit", "kiss", "sanctum", "keystones", "border", "vessel", "dawn"))
                and has_attainment
            ):
                self.fired_markers.add("goal_achieved")
                return True

        return False

    def evaluate_turn_markers(self, user_text: str) -> Optional[Dict[str, Any]]:
        if not self.active_scenario or not user_text:
            return None

        markers = self.active_scenario.get("somatic_markers", [])
        user_lower = user_text.lower()
        clean_user = self._strip_intent_and_negation_clauses(user_lower)
        # Avoid false-positive single generic words on goal_achieved markers
        generic_false_positives = {"together", "safe", "won", "complete", "finished"}

        for marker in markers:
            m_id = marker.get("id")
            if m_id in self.fired_markers:
                continue

            is_goal_marker = m_id in ("goal_achieved", "puzzle_solved")
            target_text = clean_user if is_goal_marker else user_lower
            keywords = marker.get("keywords", [])
            matched = False
            for kw in keywords:
                kw_clean = str(kw).strip().lower()
                if not kw_clean:
                    continue
                if is_goal_marker:
                    if kw_clean in generic_false_positives:
                        continue
                    # Do not let single-word setting nouns/verbs (like "time" or "engine")
                    # trigger goal_achieved directly without attainment verification
                    if " " not in kw_clean and kw_clean not in ("dawn", "sunrise", "accomplished"):
                        continue
                if target_text and re.search(rf"\b{re.escape(kw_clean)}\b", target_text):
                    matched = True
                    break

            if not matched and is_goal_marker:
                if self.check_goal_obtained(user_text):
                    matched = True

            if matched:
                self.fired_markers.add(m_id)
                logger.info(f"[ScenarioEngine] In-Scenario Somatic Marker Triggered: '{m_id}'")

                if "new_ambient_floor" in marker:
                    self.active_dynamic_floors = marker["new_ambient_floor"]

                return marker

        # Even if scenario had no explicit goal_achieved marker entry, check dynamic end_goal completion
        if "goal_achieved" not in self.fired_markers and self.check_goal_obtained(user_text):
            return {
                "id": "goal_achieved",
                "system_notice": "🌟 [Objective Reached]: Overarching scenario goal obtained!",
                "new_ambient_floor": {"serotonin": 0.55, "oxytocin": 0.45}
            }

        return None

    def build_storybook_image_prompt(
        self,
        assistant_reply: str,
        is_opening: bool = False,
        scenario_override: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Synthesizes a vivid SDXL storybook illustration prompt for the current roleplay turn
        when Calypso speaks (both when setting the scene on turn 0 and on every turn).
        """
        sc = scenario_override or self.active_scenario or {}
        title = sc.get("title", "Shared Adventure").strip()
        shard = sc.get("narrative_shard", "").strip()
        tags = ", ".join(sc.get("context_tags", [])[:4])
        vis_features = sc.get("visual_anchor", {}).get("core_features", "").strip()

        clean_narration = re.sub(r'["“”]', '', assistant_reply or "").strip()
        clean_narration = re.sub(r'\s+', ' ', clean_narration)
        # Extract the first ~180 chars of descriptive action from Calypso's turn
        sentences = re.split(r'(?<=[.!?])\s+', clean_narration)
        action_snippet = sentences[0] if sentences else clean_narration[:180]
        if len(action_snippet) > 180:
            action_snippet = action_snippet[:180].rsplit(" ", 1)[0]

        if is_opening:
            shard_sentences = re.split(r'(?<=[.!?])\s+', shard)
            setting_snippet = shard_sentences[0] if shard_sentences else shard[:180]
            parts = [
                f"Calypso in '{title}'",
                setting_snippet,
                action_snippet,
                vis_features,
                tags
            ]
        else:
            parts = [
                f"Calypso in '{title}'",
                action_snippet,
                vis_features,
                tags
            ]

        prompt = ", ".join(p.strip(" ,.") for p in parts if p and p.strip(" ,."))
        return prompt or f"Calypso in {title}, cinematic storybook scene"

    def reload(self) -> None:
        with self.lock:
            self.scenarios = self.load_scenarios()
            self._export_scenario_titles()
            self._index_scenarios()

    def load_scenarios(self) -> List[Dict[str, Any]]:
        if self.json_path.exists():
            try:
                with open(self.json_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        return data.get("roleplay_scenarios", [])
                    elif isinstance(data, list):
                        return data
            except Exception as e:
                logger.error(f"[ScenarioEngine] Could not load roleplay scenarios: {e}", exc_info=True)
        return []

    def _export_scenario_titles(self) -> None:
        if not self.scenarios and not self.titles_json_path.exists():
            return
        try:
            self.titles_json_path.parent.mkdir(parents=True, exist_ok=True)
            titles_payload = {
                "total_scenarios": len(self.scenarios),
                "last_synced": datetime.now().isoformat(),
                "scenario_titles": [
                    {
                        "id": s.get("id", f"scene_{idx:03d}"),
                        "title": s.get("title", "Untitled Scenario"),
                        "context_tags": s.get("context_tags", []),
                        "end_goal": s.get("end_goal", ""),
                        "somatic_cues": s.get("neuro_profile", {}).get("somatic_tags", [])[:2]
                    }
                    for idx, s in enumerate(self.scenarios)
                ],
                "titles_list": [
                    s.get("title", "Untitled Scenario")
                    for s in self.scenarios if s.get("title")
                ]
            }
            tmp_titles = self.titles_json_path.with_suffix(".tmp")
            with open(tmp_titles, "w", encoding="utf-8") as f:
                json.dump(titles_payload, f, indent=2, ensure_ascii=False)
            os.replace(tmp_titles, self.titles_json_path)
        except Exception as e:
            logger.warning(f"[ScenarioEngine] Failed to write scenario_titles.json: {e}")

    def _index_scenarios(self) -> None:
        if not self.ef or not self.scenarios:
            self.scenario_vectors = None
            return
        try:
            docs = []
            for s in self.scenarios:
                tags_str = ", ".join(s.get("context_tags", []))
                somatic_str = ", ".join(s.get("neuro_profile", {}).get("somatic_tags", []))
                title = s.get("title", "")
                shard = s.get("narrative_shard", "")
                hook = s.get("challenge_hook", "")
                end_goal = s.get("end_goal", "")
                docs.append(
                    f"{title}. Context: {tags_str}. Sensations: {somatic_str}. "
                    f"Atmosphere: {shard[:350]}. Hook: {hook[:150]}. Goal: {end_goal[:150]}"
                )

            raw_vecs = np.array(self.ef(docs), dtype=np.float32)
            norms = np.linalg.norm(raw_vecs, axis=1, keepdims=True)
            norms[norms == 0] = 1.0
            self.scenario_vectors = raw_vecs / norms
        except Exception as e:
            logger.warning(f"[ScenarioEngine] Vector indexing failed: {e}")
            self.scenario_vectors = None

    def search_best_scenario(
        self, query_text: str, threshold: float = 0.48, auto_activate: bool = True
    ) -> Optional[Dict[str, Any]]:
        if not self.scenarios or not query_text or not query_text.strip():
            return None

        matched = None
        if self.ef is not None and self.scenario_vectors is not None:
            try:
                user_raw = np.array(self.ef([query_text])[0], dtype=np.float32)
                user_norm = np.linalg.norm(user_raw)
                if user_norm > 0:
                    user_vec = user_raw / user_norm
                    scores = np.dot(self.scenario_vectors, user_vec)
                    best_idx = int(np.argmax(scores))
                    if float(scores[best_idx]) >= threshold:
                        matched = self.scenarios[best_idx]
            except Exception as e:
                logger.debug(f"[ScenarioEngine] Vector search error: {e}")

        if not matched:
            text_lower = query_text.lower()
            best_match, max_matches = None, 0
            for scenario in self.scenarios:
                tags = scenario.get("context_tags", [])
                match_count = sum(
                    1 for tag in tags if isinstance(tag, str) and tag.strip() and re.search(rf"\b{re.escape(tag.lower())}\b", text_lower)
                )
                if match_count > max_matches:
                    max_matches = match_count
                    best_match = scenario
            if best_match and max_matches > 0:
                matched = best_match

        if matched and auto_activate:
            self.activate_scenario(matched)

        return matched

    def get_scenario(self, identifier: str) -> Optional[Dict[str, Any]]:
        if not identifier:
            return None
        target = str(identifier).strip().lower()
        with self.lock:
            for s in self.scenarios:
                if s.get("id", "").lower() == target or s.get("title", "").lower() == target:
                    return s
        return None

    def activate_scenario(self, identifier_or_dict: str | Dict[str, Any]) -> Optional[Dict[str, Any]]:
        with self.lock:
            self.fired_markers.clear()
            self.active_dynamic_floors = None

            if isinstance(identifier_or_dict, dict):
                self.active_scenario = identifier_or_dict
                return self.active_scenario
            elif isinstance(identifier_or_dict, str):
                found = self.get_scenario(identifier_or_dict)
                if found:
                    self.active_scenario = found
                    return found
            return None

    def get_spontaneous_proposal(self) -> Optional[Dict[str, Any]]:
        with self.lock:
            if not self.scenarios:
                return None
            active_id = self.active_scenario.get("id") if self.active_scenario else None
            candidates = [
                s for s in self.scenarios
                if s.get("id") != active_id and s.get("id") not in self.recent_proposals
            ]
            if not candidates:
                self.recent_proposals.clear()
                candidates = [s for s in self.scenarios if s.get("id") != active_id] or self.scenarios

            proposal = random.choice(candidates)
            prop_id = proposal.get("id")
            if prop_id:
                self.recent_proposals.append(prop_id)
                if len(self.recent_proposals) > 5:
                    self.recent_proposals.pop(0)
            return proposal

    def get_current_visual_anchor(self) -> Optional[Dict[str, Any]]:
        if self.active_scenario and "visual_anchor" in self.active_scenario:
            return self.active_scenario["visual_anchor"]
        return None

    def clear_active_scenario(self) -> None:
        with self.lock:
            self.active_scenario = None
            self.active_dynamic_floors = None
            self.fired_markers.clear()
