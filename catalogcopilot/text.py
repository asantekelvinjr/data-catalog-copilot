"""Tiny text-processing helpers shared by retrieval, intent detection and guardrails.

Everything is written by hand (no NLTK / spaCy) so the behaviour is easy to read and to explain.
"""
from __future__ import annotations

import re
import unicodedata

# Small English + French stop-word list. The assistant is used by a French company,
# so questions can come in either language.
STOPWORDS = {
    # English
    "a", "an", "the", "of", "is", "are", "to", "in", "on", "for", "and", "or", "what", "which",
    "who", "how", "does", "do", "did", "with", "from", "by", "me", "my", "i", "it", "this", "that",
    "be", "if", "as", "at", "can", "there", "where", "when", "than", "then", "about", "into",
    # French
    "le", "la", "les", "un", "une", "des", "du", "de", "d", "l", "et", "ou", "est", "sont", "quoi",
    "que", "qui", "quel", "quelle", "quels", "quelles", "pour", "dans", "sur", "par", "en", "ce",
    "c", "qu", "au", "aux", "se", "sa", "son", "ses", "mes", "mon", "ma",
}


def normalize(text: str) -> str:
    """Lowercase, strip accents, turn punctuation into spaces."""
    text = text.lower().replace("’", " ").replace("'", " ")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def stem(token: str) -> str:
    """Very light plural stripping: payments -> payment, impayes -> impaye."""
    if len(token) > 3 and token.endswith("s") and not token.endswith(("ss", "us", "is")):
        return token[:-1]
    return token


def tokenize(text: str, drop_stopwords: bool = True) -> list[str]:
    tokens = [stem(t) for t in normalize(text).split()]
    if drop_stopwords:
        tokens = [t for t in tokens if t not in STOPWORDS]
    return tokens
