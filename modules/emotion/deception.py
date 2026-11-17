# modules/emotion/deception.py

import json
import logging
import re
import urllib.request
import numpy as np
from modules.config import config

logger = logging.getLogger("Calypso.Deception")


class DeceptionEngine:
    def __init__(self, embedding_function=None):
        self.ef = embedding_function

    def check_evasion(self, last_assistant_msg: str, user_msg: str) -> dict:
        """
        Detects conversational redirection/evasion:
        Did Calypso ask a direct question that the user completely deflected?
        """
        if not last_assistant_msg or not user_msg or not self.ef:
            return {"is_evasion": False, "confidence": 0.0}

        # 1. Check if Calypso's previous message asked a question
        questions = [s.strip() for s in re.split(r'[.!\n]', last_assistant_msg) if '?' in s]
        if not questions:
            return {"is_evasion": False, "confidence": 0.0}

        target_question = questions[-1]  # The most recent question she asked

        # 2. Exclude common direct one-word answers from evasion checks
        user_lower = user_msg.lower().strip()
        common_answers = {"yes", "no", "yeah", "nope", "maybe", "idk", "i don't know", 
                          "not sure", "probably", "sure", "never", "always", "fine", "ok"}
        if any(user_lower.startswith(ans) for ans in common_answers):
            return {"is_evasion": False, "confidence": 0.0}

        # 3. Compute semantic similarity between Question and User Response
        try:
            vecs = np.array(self.ef([target_question, user_msg]), dtype=np.float32)
            norm_q = np.linalg.norm(vecs[0])
            norm_u = np.linalg.norm(vecs[1])
            if norm_q > 0 and norm_u > 0:
                sim = float(np.dot(vecs[0] / norm_q, vecs[1] / norm_u))
                
                # If similarity is unusually low (< 0.12), the user pivoted the subject entirely
                if sim < 0.12 and len(user_msg.split()) > 3:
                    logger.info(f"[Deception] Evasion flagged: Q='{target_question}' -> A='{user_msg}' (Sim: {sim:.2f})")
                    return {
                        "is_evasion": True,
                        "confidence": round(1.0 - sim, 2),
                        "question": target_question
                    }
        except Exception as e:
            logger.debug(f"[Deception] Evasion check error: {e}")

        return {"is_evasion": False, "confidence": 0.0}

    def check_memory_conflict(self, user_msg: str, memory_docs: list) -> dict:
        """
        Performs an epistemic contradiction check between the user's latest claim
        and top recalled memory fragments.
        """
        if not user_msg or not memory_docs:
            return {"is_conflict": False, "reason": ""}

        # Exclude questions or trivial chatter from contradiction scanning
        if user_msg.strip().endswith("?") or len(user_msg.split()) < 4:
            return {"is_conflict": False, "reason": ""}

        context_facts = "\n".join([f"- {doc}" for doc in memory_docs[:2]])

        # Fast micro-check payload (capped at 50 tokens, zero temperature)
        prompt = (
            f"You are a factual consistency auditor.\n"
            f"RECALLED MEMORY FACTS:\n{context_facts}\n\n"
            f"NEW USER STATEMENT: \"{user_msg}\"\n\n"
            f"Does the NEW USER STATEMENT directly and factually contradict any RECALLED MEMORY FACT?\n"
            f"Ignore tone or opinions. Only flag explicit mutually exclusive facts.\n"
            f"Output JSON ONLY: {{\"conflict\": true/false, \"reason\": \"brief explanation\"}}"
        )

        payload = {
            "model": config.MODEL_NAME,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "options": {
                "temperature": 0.0,
                "num_predict": 60
            }
        }

        req = urllib.request.Request(
            config.OLLAMA_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )

        try:
            with urllib.request.urlopen(req, timeout=12) as response:
                result = json.loads(response.read().decode("utf-8"))
                raw_out = result.get("message", {}).get("content", "").strip()

                # Clean potential markdown wrapping
                clean_json = re.sub(r'```(?:json)?|```', '', raw_out).strip()
                data = json.loads(clean_json)

                if data.get("conflict") is True:
                    logger.info(f"[Deception] Contradiction detected: {data.get('reason')}")
                    return {
                        "is_conflict": True,
                        "reason": data.get("reason", "Contradicts established past memory.")
                    }
        except Exception as e:
            logger.debug(f"[Deception] Conflict scan skipped or timed out: {e}")

        return {"is_conflict": False, "reason": ""}
        
    def evaluate_candor(self, last_assistant_msg: str, user_msg: str) -> dict:
        """
        Evaluates active honesty:
        1. Responsive depth to Calypso's questions (Inverse Evasion).
        2. First-person vulnerability and admission markers.
        """
        if not user_msg or len(user_msg.split()) < 3:
            return {"is_candid": False, "score": 0.0, "reason": ""}

        user_lower = user_msg.lower().strip()
        candor_score = 0.0
        reasons = []

        # 1. Vulnerability / Admission Patterns (Natural language honesty)
        vulnerability_patterns = [
            r"\bi (feel|felt|was afraid|worried|struggled|messed up|screwed up)\b",
            r"\b(to be (honest|fair)|admittedly|truthfully|honestly)\b",
            r"\b(i was wrong|my fault|my mistake|i apologize|i shouldn't have)\b",
            r"\b(i don't (know|understand)|i'm (scared|unsure|confused|overwhelmed))\b"
        ]
        
        matches = [p for p in vulnerability_patterns if re.search(p, user_lower)]
        if matches:
            candor_score += 0.25 * len(matches)
            reasons.append("vulnerable disclosure/admission")

        # 2. Inverse Evasion: Did user deeply answer a personal question?
        if last_assistant_msg and self.ef:
            questions = [s.strip() for s in re.split(r'[.!\n]', last_assistant_msg) if '?' in s]
            if questions:
                target_q = questions[-1]
                # Is Calypso's question personal/reflective?
                is_reflective_q = any(w in target_q.lower() for w in ["feel", "think", "mean", "why", "you", "happen", "remember"])
                
                if is_reflective_q:
                    try:
                        vecs = np.array(self.ef([target_q, user_msg]), dtype=np.float32)
                        norm_q = np.linalg.norm(vecs[0])
                        norm_u = np.linalg.norm(vecs[1])
                        if norm_q > 0 and norm_u > 0:
                            sim = float(np.dot(vecs[0] / norm_q, vecs[1] / norm_u))
                            # High semantic engagement with a personal question
                            if sim >= 0.42 and len(user_msg.split()) >= 6:
                                candor_score += 0.20
                                reasons.append("thoughtful question response")
                    except Exception:
                        pass

        candor_score = min(1.0, candor_score)
        return {
            "is_candid": candor_score >= 0.20,
            "score": round(candor_score, 2),
            "reason": ", ".join(reasons)
        }        
