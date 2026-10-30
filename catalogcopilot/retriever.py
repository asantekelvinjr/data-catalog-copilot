"""Retrieval over catalog documents.

Two modes so the benefit of each idea can be measured (see eval/run_eval.py):
  * "baseline": plain BM25 on the raw question.
  * "enhanced": BM25 + glossary synonym expansion (EN/FR) + a boost for the document type that
                fits the detected intent (e.g. glossary terms for "what is ..." questions).
"""
from __future__ import annotations

from dataclasses import dataclass

from .bm25 import BM25
from .loader import Catalog, Doc
from .text import normalize, tokenize

# intent -> {doc kind: multiplicative boost}
TYPE_BOOST = {
    "definition": {"term": 1.6},
    "pii": {"column": 1.25},
    "owner": {"asset": 1.3},
    "quality": {"asset": 1.3},
    "lineage_up": {"asset": 1.3},
    "lineage_down": {"asset": 1.3},
    "impact": {"asset": 1.3},
}


@dataclass
class Hit:
    doc: Doc
    score: float


class Retriever:
    def __init__(self, catalog: Catalog, mode: str = "enhanced"):
        if mode not in ("baseline", "enhanced"):
            raise ValueError("mode must be 'baseline' or 'enhanced'")
        self.catalog, self.mode = catalog, mode
        self.docs = catalog.docs
        self.index = BM25([tokenize(d.text) for d in self.docs])
        # normalised synonym phrases per glossary term, used for query expansion
        self._phrases = {
            tid: [normalize(s) for s in [t["name"], *t["synonyms"]]] for tid, t in catalog.terms.items()
        }

    def expand(self, query: str) -> list[str]:
        """Add the vocabulary of every glossary term whose synonym appears in the question."""
        tokens = tokenize(query)
        padded = f" {normalize(query)} "
        for tid, phrases in self._phrases.items():
            if any(f" {p} " in padded for p in phrases):
                t = self.catalog.terms[tid]
                tokens += tokenize(" ".join([t["name"], *t["synonyms"]]))
        return tokens

    def search(self, query: str, k: int = 5, intent: str | None = None) -> list[Hit]:
        q_tokens = self.expand(query) if self.mode == "enhanced" else tokenize(query)
        scores = self.index.scores(q_tokens)
        if self.mode == "enhanced" and intent in TYPE_BOOST:
            boost = TYPE_BOOST[intent]
            scores = [s * boost.get(d.kind, 1.0) for s, d in zip(scores, self.docs)]
        ranked = sorted(zip(self.docs, scores), key=lambda x: x[1], reverse=True)
        return [Hit(d, s) for d, s in ranked[:k] if s > 0]
