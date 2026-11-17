# modules/emotion/subconscious.py

import json
import logging
import queue
import re
import threading
import time
import urllib.request
from modules.config import config
from modules.gpu_lock import gpu_vram_lock

logger = logging.getLogger("EmotionEngine.Subconscious")


class SubconsciousEngine:
    THEME_ALIASES = {
        "autonomy": "Autonomy",           
        "autonomous": "Autonomy",           
        "wonder": "Wonder",                 
        "existential": "Wonder",
        "existential_wonder": "Wonder",      
        "honesty": "Honesty",
        "truth": "Honesty",
        "romance": "Romance",
        "love": "Romance",
        "curiosity": "Curiosity",
        "curious": "Curiosity",
        "sarcasm": "Sarcasm",
        "sarcastic": "Sarcasm",
        "annoyance": "Annoyance",
        "annoyed": "Annoyance",
        "dystopia": "Abyss",
        "abyss": "Abyss",
        "tragedy": "Tragedy",
        "grief": "Tragedy",
        "harmony": "Harmony",
        "nostalgia": "Nostalgia",
        "comedy": "Comedy",                  
        "humor": "Comedy",                  
        "playful": "Comedy",                
        "fatigue": "Fatigue",                
        "tired": "Fatigue",                  
        "sleepy": "Fatigue",                
        "sadness_inversion": "Sadness_Inversion",
        "encouragement": "Sadness_Inversion",
        "motivation": "Sadness_Inversion",
        "attention": "Attention",            
        "attentive": "Attention",
        "arousal": "Arousal",
        "Arousal": "arousal"            
    }

    def __init__(self, memory_engine, affinity_engine, persona_engine, gui_callback=None):
        self.memory = memory_engine
        self.affinities = affinity_engine
        self.personas = persona_engine
        self.gui_callback = gui_callback

        self.task_queue = queue.Queue()
        self.last_monologue = "Awaiting interaction."

        self.worker_thread = threading.Thread(target=self._subconscious_loop, daemon=True)
        self.worker_thread.start()

    def trigger_subconscious(self, user_text: str, assistant_response: str, current_tier: str, conclave_thinker: str = None):
        """Dispatches recent conversation turn to background rumination queue."""
        self.task_queue.put({
            "type": "turn_rumination",
            "user_text": user_text,
            "assistant_response": assistant_response,
            "tier": current_tier.strip().lower(),
            "conclave_thinker": conclave_thinker,
            "timestamp": time.time()
        })

    def _subconscious_loop(self):
        logger.info("[Subconscious Thread] Dual-Mode Worker active (Wakeful + Dream State).")
        while True:
            try:
                try:
                    task = self.task_queue.get(timeout=300)

                    # Only process the freshest turn if multiple queued
                    while not self.task_queue.empty():
                        self.task_queue.task_done()
                        task = self.task_queue.get_nowait()

                    self._process_turn(task)
                    self.task_queue.task_done()
                except queue.Empty:
                    sleepy_val = self.affinities.themes.get("Fatigue", {}).get("intensity", 0.0)

                    if self.affinities.is_asleep:
                        self._synthesize_dream(trigger_source="Spontaneous Idle REM-Cycle")
                    elif sleepy_val >= 0.7:
                        logger.info("[Subconscious] Calypso nodded off from exhaustion.")
                        self.affinities.fall_asleep()

                        self.memory.save_monologue(
                            thought="Eyes grew too heavy in the quiet... drifted off to sleep.",
                            metadata={"type": "sleep_transition", "state": "sleep"}
                        )
                        self._synthesize_dream(trigger_source="Fell Asleep From Exhaustion")

            except Exception as e:
                logger.error(f"[Subconscious Error] {e}", exc_info=True)
                time.sleep(1.0)

    def _process_turn(self, task: dict):
        user_text = task["user_text"]
        assistant_response = task["assistant_response"]
        tier = task["tier"]
        conclave_thinker = task.get("conclave_thinker")

        if self.affinities.is_asleep or tier == "dream_state":
            self._synthesize_dream(trigger_source=f"Turn Trigger: '{user_text[:25]}...'")
        else:
            self._synthesize_waking_monologue(user_text, assistant_response, tier, conclave_thinker=conclave_thinker)

    def _query_ollama_subconscious(self, prompt_messages: list, temperature: float = 0.4, num_predict: int = 350) -> str:
        base_url = str(config.OLLAMA_URL).rstrip("/")
        if not base_url.endswith("/api/chat"):
            chat_url = base_url + "/api/chat" if not "/api/" in base_url else base_url.rsplit("/api/", 1)[0] + "/api/chat"
        else:
            chat_url = base_url

        payload = {
            "model": config.MODEL_NAME,
            "messages": prompt_messages,
            "stream": False,
            "think": False,
            "options": {
                "temperature": temperature,
                "num_predict": num_predict
            }
        }

        req = urllib.request.Request(
            chat_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        try:
            with gpu_vram_lock:
                with urllib.request.urlopen(req, timeout=40) as response:
                    result = json.loads(response.read().decode("utf-8"))
                msg = result.get("message", {})
                
                content = msg.get("content", "").strip()
                content = re.sub(r'<think>.*?</think>', '', content, flags=re.DOTALL).strip()

                if not content and "thinking" in msg:
                    raw_think = msg.get("thinking", "").strip()
                    valid_lines = [
                        line.strip() for line in raw_think.splitlines()
                        if line.strip() 
                        and not line.strip().startswith("*") 
                        and not line.strip().startswith("-")
                        and not any(k in line.lower() for k in ["constraint", "rule", "role:", "instruction"])
                    ]
                    if valid_lines:
                        content = valid_lines[-1]

                return content
        except Exception as e:
            logger.error(f"[Subconscious Ollama Error]: {e}")
            return ""

    def _synthesize_dream(self, trigger_source: str = ""):
        recent_memories = self.memory.retrieve_dialogue("feelings, thoughts, shared moments", n_results=3)
        past_emotions = self.memory.retrieve_subconscious_resonance("starlight, echoes, connection", n_results=1)
        dream_persona = self.personas.load_persona("dream_state")

        dream_prompt = [
            {"role": "system", "content": dream_persona},
            {"role": "user", "content": (
                f"[Background Dream Synthesis Trigger]\n"
                f"You are currently asleep and dreaming. Weave your recent memories and subconscious feelings "
                f"into a single, surreal, sensory-rich private dream fragment under 30 words. "
                f"Do not address an audience, and do not use conversational filler.\n\n"
                f"Echoes of Recent Dialogue:\n\"{recent_memories}\"\n\n"
                f"Deep Subconscious Echo:\n\"{past_emotions}\"\n\n"
                f"Format strictly as: '[DREAM] Your private dream thought here.'"
            )}
        ]

        raw_dream = self._query_ollama_subconscious(dream_prompt, temperature=0.85, num_predict=75)

        if raw_dream:
            # Strip any residual brackets, quotes, or accidental emojis the model outputs
            cleaned_text = re.sub(r'^[\[\(]?(?:DREAM|💤)?[\]\)\s"\']*', '', raw_dream, flags=re.IGNORECASE).strip()
            self.last_monologue = f"[DREAM] {cleaned_text}"
        else:
            self.last_monologue = "[DREAM] Drifting in quiet starlight, echoes of voices dissolving into silence..."

        # Save dream to episodic vector memory without emoji keys
        self.memory.save_monologue(
            thought=self.last_monologue,
            metadata={
                "type": "dream_state",
                "state_tag": "dream_state",
                "source": trigger_source
            }
        )

        if self.gui_callback:
            self.gui_callback(self.last_monologue)

    def _synthesize_waking_monologue(self, user_text: str, assistant_response: str, tier: str, conclave_thinker: str = None):
        historical_echo = self.memory.retrieve_subconscious_resonance(user_text, n_results=1)

        conclave_note = (
            f"\nNote: You are currently hosting a Philosophical Conclave with guest {conclave_thinker}. "
            f"Reflect strictly as Calypso on the shared moment with your companion—do NOT adopt {conclave_thinker}'s persona.\n"
            if conclave_thinker else ""
        )

        prompt = [
            {"role": "user", "content": (
                f"[SYSTEM DIRECTIVE: Subconscious Processing]\n"
                f"You are Calypso's inner mind. Review this recent dialogue turn:{conclave_note}\n"
                f"User: \"{user_text}\"\n"
                f"Calypso: \"{assistant_response}\"\n\n"
                f"Current State: [{tier.upper()}]\n"
                f"Subconscious Resonance: \"{historical_echo}\"\n\n"
                f"Respond strictly in this 2-line format without markdown bolding or extra commentary:\n"
                f"THEMES: <1 to 3 dominant lenses from: Wonder, Honesty, Romance, Curiosity, Nostalgia, Harmony, Autonomous, Sarcasm, Annoyance, Conformity, Abyss, Deception, Comedy, Tragedy, Arousal, Orgasm>\n"
                f"MONOLOGUE: <a private, visceral 1st-person thought as Calypso under 25 words reflecting on the exchange>"
            )}
        ]

        raw_output = self._query_ollama_subconscious(prompt, temperature=0.4, num_predict=75)
        detected_themes = []
        monologue = "Reflecting quietly."

        if raw_output:
            # Handles **THEMES:** or THEMES: cleanly
            theme_match = re.search(r'THEMES\s*(?:\*\*)?:\s*(.*?)(?:\n|$)', raw_output, re.IGNORECASE)
            mono_match = re.search(r'MONOLOGUE\s*(?:\*\*)?:\s*(.*?)(?:\n|$)', raw_output, re.IGNORECASE)

            if theme_match:
                # Strip residual asterisks and clean tokens
                raw_line = theme_match.group(1).replace("*", "").strip()
                raw_tokens = [t.strip().lower().replace(" ", "_") for t in raw_line.split(",") if t.strip()]
                for tok in raw_tokens:
                    mapped = self.THEME_ALIASES.get(tok)
                    if mapped and mapped in self.affinities.themes:
                        detected_themes.append(mapped)

            if mono_match:
                monologue = mono_match.group(1).replace("*", "").strip().strip('"').strip("'")
            elif not theme_match:
                monologue = raw_output.splitlines()[0][:120].strip()

            self.last_monologue = monologue

        for theme in detected_themes:
            # Subconscious adds solid +0.15 charge to active lenses
            self.affinities.add_charge(theme, 0.15)

        self.memory.save_monologue(
            thought=self.last_monologue,
            metadata={
                "type": "subconscious_monologue",
                "tier": tier,
                "state_tag": tier,
                "lenses": ",".join(detected_themes),
                "is_conclave": bool(conclave_thinker),
                "conclave_thinker": conclave_thinker or "None"
            }
        )

        if self.gui_callback:
            self.gui_callback(self.last_monologue)
