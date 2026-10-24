"""Text helpers shared by FAQ discovery and manual question entry."""

import re
import unicodedata


def normalise_question(text: str) -> str:
    """Lowercase, trim, and remove punctuation for FAQ question deduplication."""
    text = unicodedata.normalize("NFKC", text).casefold()
    text = re.sub(r"[^\w\s]", " ", text)
    return " ".join(text.split())
