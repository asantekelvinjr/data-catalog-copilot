"""BM25 ranking implemented from scratch (Okapi BM25).

score(q, d) = sum over query terms t of  IDF(t) * f(t,d) * (k1 + 1) / (f(t,d) + k1 * (1 - b + b * |d| / avgdl))
IDF(t)      = ln(1 + (N - n_t + 0.5) / (n_t + 0.5))
"""
from __future__ import annotations

import math
from collections import Counter


class BM25:
    def __init__(self, corpus_tokens: list[list[str]], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.corpus = corpus_tokens
        self.n_docs = len(corpus_tokens)
        self.doc_len = [len(d) for d in corpus_tokens]
        self.avgdl = sum(self.doc_len) / max(self.n_docs, 1)
        self.term_freqs = [Counter(d) for d in corpus_tokens]
        df: Counter = Counter()
        for tf in self.term_freqs:
            df.update(tf.keys())
        self.idf = {t: math.log(1 + (self.n_docs - n + 0.5) / (n + 0.5)) for t, n in df.items()}

    def scores(self, query_tokens: list[str]) -> list[float]:
        out = [0.0] * self.n_docs
        for term in set(query_tokens):
            idf = self.idf.get(term)
            if idf is None:
                continue
            for i, tf in enumerate(self.term_freqs):
                f = tf.get(term, 0)
                if f == 0:
                    continue
                norm = f + self.k1 * (1 - self.b + self.b * self.doc_len[i] / self.avgdl)
                out[i] += idf * f * (self.k1 + 1) / norm
        return out
