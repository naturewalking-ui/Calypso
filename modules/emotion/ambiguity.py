# ambiguity.py

import logging
from ollama import chat
from pydantic import BaseModel, Field
from modules.config import config

logger = logging.getLogger("Calypso.Ambiguity")


# 1. Inherit from BaseModel and use the name matching the function call
class AmbiguityAnalysis(BaseModel):
    ambiguity_score: float = Field(
        description="Score from 0.0 (completely clear) to 1.0 (highly ambiguous)"
    )
    primary_interpretation: str = Field(
        description="The most likely intended meaning"
    )
    alternative_interpretations: list[str] = Field(
        description="Other ways this text could reasonably be interpreted"
    )
    ambiguity_type: str = Field(
        description="Type of ambiguity: Lexical, Syntactic, Referential, Semantic, or None"
    )


# 2. Local analyzer function defaulting to config.MODEL_NAME
def analyze_ambiguity_local(text: str, model_name: str = None) -> AmbiguityAnalysis:
    target_model = model_name or config.MODEL_NAME
    response = chat(
        model=target_model,
        messages=[
            {
                "role": "system",
                "content": "You are a linguistic analysis tool. Analyze the user text for ambiguity."
            },
            {
                "role": "user",
                "content": f"Analyze this text for ambiguity: '{text}'"
            }
        ],
        format=AmbiguityAnalysis.model_json_schema(),
        options={"temperature": 0.0}
    )
    return AmbiguityAnalysis.model_validate_json(response.message.content)


# --- Example Usage ---
if __name__ == "__main__":
    sample_text = "Visiting relatives can be boring."
    result = analyze_ambiguity_local(sample_text)

    print(f"Model: {config.MODEL_NAME}")
    print(f"Text: {sample_text}")
    print(f"Ambiguity Score: {result.ambiguity_score}")
    print(f"Type: {result.ambiguity_type}")
    print(f"Alternatives: {result.alternative_interpretations}")
