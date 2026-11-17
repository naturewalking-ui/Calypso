# modules/emotion/personas.py

from pathlib import Path
from modules.config import config


class PersonaEngine:
    def __init__(self, personas_dir: Path = None):
        self.personas_dir = personas_dir or config.PERSONAS_DIR
        self.personas_dir.mkdir(parents=True, exist_ok=True)

    def get_persona_name(self, identifier: str) -> str:
        """Resolves a tier name, state tag, or filename into a standard persona name."""
        clean = identifier.strip().lower()
        clean = clean.replace("[", "").replace("]", "").replace("persona", "").replace(".md", "").strip()
        return clean.replace(" ", "_")

    def load_persona(self, identifier: str) -> str:
        """
        Loads the persona Markdown file based on canonical state tag.
        Falls back to neutral.md, then a hardcoded string if neither exists.
        """
        persona_name = self.get_persona_name(identifier)
        file_path = self.personas_dir / f"{persona_name}.md"

        if file_path.exists():
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    return f.read().strip()
            except Exception as e:
                print(f"[PERSONA ERROR] Could not read {file_path}: {e}")

        neutral_path = self.personas_dir / "neutral.md"
        if neutral_path.exists():
            try:
                with open(neutral_path, "r", encoding="utf-8") as f:
                    return f.read().strip()
            except Exception:
                pass

        return "You are Calypso, a thoughtful and emotionally aware companion."
