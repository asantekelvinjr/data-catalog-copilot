"""Rule-based intent detection. Deliberately simple and transparent: every rule is a regex you can read.

Order matters: the first matching intent wins (impact > lineage > definition > owner > quality > pii).
Definition is only confirmed later, when the top retrieved document is a glossary term.
"""
from __future__ import annotations

import re

from .text import normalize

RULES: list[tuple[str, str]] = [
    ("impact", r"\b(impact|break|breaks|affected|affect|casse|consequence|consequences)\b|\bif\b.*\b(change|changes|fail|fails|down|late)\b|\bsi\b.*\b(change|modifie|tombe|en retard)\b"),
    ("lineage_down", r"\b(downstream|depend|depends|dependent|feeds|feed|consume|consumes|used by|who uses|aval|alimente|utilise|utilisent|consommateurs?)\b"),
    ("lineage_up", r"\b(upstream|come from|comes from|coming from|source|sources|origin|origine|derived|built from|lineage|lignee|provenance|tracabilite|vient|viennent|provient|alimente par|amont|feed the|feeds the|inputs?|trained on|uses? as)\b"),
    ("definition", r"\b(what is|what s|what does|define|definition|explain|explique|sens de|signification|meaning|mean|means|c est quoi|qu est ce|que signifie|signifie|definis|definition)\b"),
    ("owner", r"\b(owner|owns|owned|accountable|in charge|steward|responsible|responsable|proprietaire|maintains|maintainer|contact)\b"),
    ("quality", r"\b(quality|qualite|null|nulls|freshness|fresh|refresh|refreshed|sla|rules|checks?|valid|validation|actualis\w*|mise a jour|how often|frequence|updated|real time|realtime|latency|up to date|how recent)\b"),
    ("pii", r"\b(pii|e ?mails?|phones?|telephones?|iban|birth ?dates?|date of birth|date de naissance|adresses?|addresses|address|personal|sensitive|gdpr|rgpd|personnelles?|sensibles?|anonym\w*|pseudonym\w*|identifier|identifiers|identify|identifiant|identifiants)\b"),
]
_COMPILED = [(name, re.compile(rx)) for name, rx in RULES]

# Note: "feeds" is ambiguous in English. "Which tables feed X?" asks for the sources of X (upstream),
# "What does X feed?" asks for its consumers (downstream). classify() handles the first shape with a
# dedicated pattern before falling back to the ordered rules.


def classify(question: str) -> str:
    q = normalize(question)
    # "Which tables feed the dashboard?" -> upstream (asking for the sources of something)
    if re.search(r"\b(which|what|quelles?|quels?)\b.*\b(tables?|assets?|sources?|datasets?)\b.*\b(feed|feeds|alimentent?|alimente)\b", q):
        return "lineage_up"
    for name, rx in _COMPILED:
        if rx.search(q):
            return name
    return "search"
