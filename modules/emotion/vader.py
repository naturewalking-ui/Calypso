# Modules/Emotion/vader_engine.py

import nltk
from nltk.sentiment.vader import SentimentIntensityAnalyzer

try:
    nltk.data.find('sentiment/vader_lexicon.zip')
except LookupError:
    nltk.download('vader_lexicon')


# modules/emotion/vader.py

class VaderEngine:
    def __init__(self):
        self.sia = SentimentIntensityAnalyzer()

    def analyze_stimulus(self, user_text: str) -> dict:
        if not user_text or not user_text.strip():
            return {"compound": 0.0, "arousal": 0.0}

        scores = self.sia.polarity_scores(user_text)
        compound = round(float(scores["compound"]), 3)
        arousal = round(abs(compound), 3)

        return {
            "compound": compound,
            "arousal": arousal
        }

    # Alias so both .analyze() and .analyze_stimulus() work seamlessly
    def analyze(self, user_text: str) -> dict:
        return self.analyze_stimulus(user_text)
