"""The assistant: guardrails -> intent -> retrieval / graph -> grounded, cited answer.

It never invents facts: every sentence in an answer comes from the catalog, and every answer ends
with the catalog ids it used. `grounded_prompt()` shows how the same retrieved passages would be
handed to a language model, so an LLM can be plugged in without changing the rest.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import lineage
from .guardrails import REFUSAL, AuditLog, check_request, redact
from .intents import classify
from .loader import Catalog
from .retriever import Hit, Retriever
from .text import tokenize

LAYER_PRIORITY = {"core": 0, "mart": 1, "consumer": 2, "staging": 3, "raw": 4}
VERSION_TOKEN = re.compile(r"^v\d+$")


@dataclass
class Answer:
    question: str
    intent: str
    text: str
    sources: list[str] = field(default_factory=list)
    refused: bool = False
    hits: list[Hit] = field(default_factory=list)

    def __str__(self) -> str:
        src = f"\nSources: {', '.join(self.sources)}" if self.sources else ""
        return self.text + src


class Assistant:
    def __init__(self, catalog: Catalog, retriever: Retriever | None = None, audit: AuditLog | None = None):
        self.catalog = catalog
        self.retriever = retriever or Retriever(catalog)
        self.audit = audit or AuditLog(None)
        self._aliases = self._build_aliases()

    # ------------------------------------------------------------ entity linking
    def _build_aliases(self) -> dict[str, list[frozenset[str]]]:
        """Token sets that identify an asset in a question, e.g. core.fact_payment -> {fact, payment}."""
        aliases: dict[str, list[frozenset[str]]] = {}
        for aid, a in self.catalog.assets.items():
            short = aid.split(".", 1)[1]
            toks = [t for t in tokenize(short, drop_stopwords=False) if not VERSION_TOKEN.match(t)]
            variants = [frozenset(toks)]
            if a["layer"] == "staging":  # people say "staging customers" for stg_customers
                variants.append(frozenset("staging" if t == "stg" else t for t in toks))
            aliases[aid] = variants
        return aliases

    def resolve_assets(self, question: str) -> list[str]:
        q_tokens = set(tokenize(question, drop_stopwords=False))
        matched = [(aid, v) for aid, variants in self._aliases.items() for v in variants if v <= q_tokens]
        # drop an asset whose alias is strictly contained in a longer matched alias (e.g. "customer" in "dim customer")
        keep = [(aid, v) for aid, v in matched if not any(v < w for _, w in matched)]
        seen, out = set(), []
        for aid, _ in sorted(keep, key=lambda x: (LAYER_PRIORITY[self.catalog.assets[x[0]]["layer"]], x[0])):
            if aid not in seen:
                seen.add(aid)
                out.append(aid)
        return out

    def _asset_from_hits(self, hits: list[Hit]) -> str | None:
        for h in hits:
            if h.doc.asset_id:
                return h.doc.asset_id
        return None

    # --------------------------------------------------------------------- main
    def ask(self, question: str) -> Answer:
        allowed, reason = check_request(question)
        if not allowed:
            ans = Answer(question, "refused", REFUSAL, refused=True)
            self.audit.write(question=question, intent="refused", refused=True, reason=reason, sources=[])
            return ans

        intent = classify(question)
        hits = self.retriever.search(question, k=5, intent=intent)
        explicit = self.resolve_assets(question)

        if intent == "definition" and not (hits and hits[0].doc.kind == "term"):
            intent = "search"  # "what is" about something that is not a glossary term

        if len(explicit) >= 2 and intent in ("search", "lineage_up", "lineage_down"):
            ans = self._path(question, explicit)  # two assets named: show how data flows between them
            ans.intent, ans.hits = "lineage_path", hits
            self.audit.write(question=question, intent=ans.intent, refused=False, sources=ans.sources)
            return ans

        handler = {
            "impact": self._impact, "lineage_up": self._lineage_up, "lineage_down": self._lineage_down,
            "definition": self._definition, "owner": self._owner, "quality": self._quality,
            "pii": self._pii, "search": self._search,
        }[intent]
        ans = handler(question, hits, explicit)
        ans.intent, ans.hits = intent, hits
        ans.text = redact(ans.text)
        self.audit.write(question=question, intent=intent, refused=False, sources=ans.sources)
        return ans

    # ------------------------------------------------------------------ handlers
    def _target(self, hits: list[Hit], explicit: list[str]) -> str | None:
        return explicit[0] if explicit else self._asset_from_hits(hits)

    def _fmt(self, aid: str) -> str:
        a = self.catalog.assets[aid]
        return f"{aid} ({a['type']}, owner: {a['owner']})"

    def _lineage_up(self, q, hits, explicit) -> Answer:
        if len(explicit) >= 2:
            return self._path(q, explicit)
        target = self._target(hits, explicit)
        if not target:
            return self._search(q, hits, explicit)
        ups = lineage.upstream(self.catalog.graph, target)
        if not ups:
            return Answer(q, "", f"{target} is a source table: nothing flows into it inside the catalog.", [target])
        lines = [f"Data in {target} comes from {len(ups)} upstream assets:"]
        for hop in sorted(set(ups.values())):
            names = ", ".join(self._fmt(a) for a, d in ups.items() if d == hop)
            lines.append(f"- {hop} hop{'s' if hop > 1 else ''} away: {names}")
        roots = [a for a in ups if not self.catalog.graph.in_degree(a)]
        lines.append(f"Original sources: {', '.join(roots)}.")
        return Answer(q, "", "\n".join(lines), [target, *ups])

    def _lineage_down(self, q, hits, explicit) -> Answer:
        if len(explicit) >= 2:
            return self._path(q, explicit)
        target = self._target(hits, explicit)
        if not target:
            return self._search(q, hits, explicit)
        downs = lineage.downstream(self.catalog.graph, target)
        if not downs:
            return Answer(q, "", f"Nothing consumes {target}: it is a leaf of the lineage graph.", [target])
        lines = [f"{target} feeds {len(downs)} downstream assets:"]
        for hop in sorted(set(downs.values())):
            names = ", ".join(self._fmt(a) for a, d in downs.items() if d == hop)
            lines.append(f"- {hop} hop{'s' if hop > 1 else ''} away: {names}")
        return Answer(q, "", "\n".join(lines), [target, *downs])

    def _path(self, q, explicit) -> Answer:
        a, b = explicit[0], explicit[1]
        for src, dst in ((a, b), (b, a)):
            p = lineage.path_between(self.catalog.graph, src, dst)
            if p:
                return Answer(q, "", f"Data flows from {src} to {dst} through: " + " -> ".join(p), p)
        return Answer(q, "", f"No lineage path between {a} and {b}.", [a, b])

    def _impact(self, q, hits, explicit) -> Answer:
        target = self._target(hits, explicit)
        if not target:
            return self._search(q, hits, explicit)
        s = lineage.impact_summary(self.catalog, target)
        if not s["affected"]:
            return Answer(q, "", f"A change in {target} affects nothing else in the catalog.", [target])
        parts = [f"If {target} changes or arrives late, {len(s['affected'])} downstream assets are affected."]
        for kind in ("table", "dashboard", "model"):
            if s["by_type"][kind]:
                parts.append(f"- {kind}s: {', '.join(s['by_type'][kind])}")
        parts.append(f"- teams to warn: {', '.join(s['owners'])}")
        if s["critical"]:
            parts.append(f"- {len(s['critical'])} of them are rated high criticality.")
        return Answer(q, "", "\n".join(parts), [target, *s["affected"]])

    def _definition(self, q, hits, explicit) -> Answer:
        term = self.catalog.terms[hits[0].doc.meta["term_id"]]
        text = f"{term['name']}: {term['definition']}"
        related = term.get("related_assets", [])
        if related:
            text += f"\nWhere to look: {', '.join(related)}."
        return Answer(q, "", text, [f"term:{term['id']}", *related])

    def _owner(self, q, hits, explicit) -> Answer:
        target = self._target(hits, explicit)
        if not target:
            return self._search(q, hits, explicit)
        a = self.catalog.assets[target]
        text = (f"{target} is owned by {a['owner']}. Data steward: {a['steward']}. "
                f"Refresh: {a['refresh']}. Criticality: {a['criticality']}.")
        return Answer(q, "", text, [target])

    def _quality(self, q, hits, explicit) -> Answer:
        target = self._target(hits, explicit)
        if not target:
            return self._search(q, hits, explicit)
        a = self.catalog.assets[target]
        rules = "\n".join(f"- {r}" for r in a.get("quality_rules", [])) or "- no rule documented"
        text = f"{target} is refreshed {a['refresh']}. Documented quality rules:\n{rules}"
        return Answer(q, "", text, [target])

    def _pii(self, q, hits, explicit) -> Answer:
        cat = self.catalog
        if explicit:
            aid = explicit[0]
            cols = [c for c in cat.assets[aid].get("columns", []) if c["classification"] != "none"]
            if not cols:
                return Answer(q, "", f"{aid} has no column classified as personal or financial data.", [aid])
            lines = [f"Classified columns in {aid}:"] + [f"- {c['name']}: {c['classification']}" for c in cols]
            return Answer(q, "", "\n".join(lines), [aid])
        col_hits = [h for h in hits if h.doc.kind == "column" and h.doc.meta["classification"] != "none"]
        if col_hits:
            lines = ["Matching classified columns:"] + [
                f"- {h.doc.title}: {h.doc.meta['classification']}" for h in col_hits[:5]]
            if any(h.doc.meta["classification"] == "direct_identifier" for h in col_hits[:5]):
                lines.append(self._direct_identifier_note())
            return Answer(q, "", "\n".join(lines), [h.doc.title for h in col_hits[:5]])
        direct = {aid: [c["name"] for c in a.get("columns", []) if c["classification"] == "direct_identifier"]
                  for aid, a in cat.assets.items()}
        direct = {k: v for k, v in direct.items() if v}
        lines = ["Direct identifiers exist only in the raw zone:"] + [f"- {k}: {', '.join(v)}" for k, v in direct.items()]
        lines.append(self._direct_identifier_note())
        return Answer(q, "", "\n".join(lines), list(direct) + ["staging.stg_customers"])

    def _direct_identifier_note(self) -> str:
        layers = sorted({a["layer"] for a in self.catalog.assets.values()
                         if any(c["classification"] == "direct_identifier" for c in a.get("columns", []))})
        return (f"Direct identifiers exist only in the {', '.join(layers)} layer. From staging onwards customers are "
                "pseudonymised: tables join on a hashed customer_key.")

    def _search(self, q, hits, explicit) -> Answer:
        if not hits:
            return Answer(q, "", "I could not find anything relevant in the catalog. Try naming a table, a column or a business term.", [])
        lines = ["Closest catalog entries:"]
        for h in hits[:3]:
            if h.doc.kind == "asset":
                a = self.catalog.assets[h.doc.asset_id]
                lines.append(f"- {h.doc.title} ({a['type']}): {a['description']}")
            elif h.doc.kind == "column":
                lines.append(f"- {h.doc.title}: {h.doc.meta['description']}")
            else:
                t = self.catalog.terms[h.doc.meta["term_id"]]
                lines.append(f"- {t['name']}: {t['definition']}")
        return Answer(q, "", "\n".join(lines), [h.doc.id for h in hits[:3]])

    # ------------------------------------------------------------- LLM bridge
    def grounded_prompt(self, question: str, k: int = 5) -> str:
        """Prompt that restricts a language model to the retrieved catalog passages."""
        hits = self.retriever.search(question, k=k, intent=classify(question))
        context = "\n".join(f"[{h.doc.id}] {h.doc.text}" for h in hits)
        return (
            "You are a data-catalog assistant. Answer ONLY from the passages below and cite the ids in brackets.\n"
            "If the passages do not contain the answer, say you do not know. "
            "Never output personal data about an individual; you only describe metadata.\n\n"
            f"Passages:\n{context}\n\nQuestion: {redact(question)}\nAnswer:"
        )
