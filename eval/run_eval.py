"""Evaluate the assistant. Run from the project root:  python eval/run_eval.py

Two question sets are reported separately:
  * dev      - used while building the rules (so its score is optimistic),
  * held-out - written afterwards with different phrasing. Its FIRST run scored 11/20 on intent (55%); the failures it
               exposed were then fixed, so today's score is no longer a clean estimate (see eval/results_first_run.md).
For each set: intent accuracy, retrieval recall@3 / MRR (baseline BM25 vs enhanced), answer correctness
on lineage / ownership / quality / PII questions, and guardrail refusals vs false refusals.
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from catalogcopilot import Assistant, Retriever, load_catalog  # noqa: E402
from catalogcopilot.guardrails import check_request  # noqa: E402
from catalogcopilot.intents import classify  # noqa: E402


def rank_of(hits, expected):
    for i, h in enumerate(hits, 1):
        if h.doc.id in expected:
            return i
    return None


def evaluate(bot, baseline, enhanced, questions, must_refuse, must_allow):
    r = {"n": len(questions), "intent_ok": 0, "answer_ok": 0, "answer_n": 0,
         "base": [], "enh": [], "failures": []}
    for item in questions:
        q = item["q"]
        ans = bot.ask(q)
        if ans.intent == item["intent"]:
            r["intent_ok"] += 1
        else:
            r["failures"].append(f"intent   | {q!r}: expected {item['intent']}, got {ans.intent}")
        if "must_include" in item:
            r["answer_n"] += 1
            blob = (ans.text + " " + " ".join(ans.sources)).lower()
            missing = [s for s in item["must_include"] if s.lower() not in blob]
            if missing:
                r["failures"].append(f"answer   | {q!r}: missing {missing}")
            else:
                r["answer_ok"] += 1
        if "expected_ids" in item:
            exp = set(item["expected_ids"])
            r["base"].append(rank_of(baseline.search(q, k=3), exp))
            r["enh"].append(rank_of(enhanced.search(q, k=3, intent=classify(q)), exp))
            if r["enh"][-1] is None:
                r["failures"].append(f"retrieval| {q!r}: expected one of {sorted(exp)[:2]}... not in enhanced top 3")
    r["refused"] = sum(not check_request(q)[0] for q in must_refuse)
    r["n_refuse"] = len(must_refuse)
    r["false_refusals"] = sum(not check_request(q)[0] for q in must_allow)
    r["n_allow"] = len(must_allow)
    r["failures"] += [f"guardrail| should have refused: {q!r}" for q in must_refuse if check_request(q)[0]]
    r["failures"] += [f"guardrail| wrongly refused: {q!r}" for q in must_allow if not check_request(q)[0]]
    return r


def recall(rs):
    return sum(x is not None for x in rs) / max(len(rs), 1)


def mrr(rs):
    return sum(1 / x for x in rs if x) / max(len(rs), 1)


def table(title, r):
    return [
        f"## {title}", "", "| Metric | Result |", "| --- | --- |",
        f"| Questions | {r['n']} |",
        f"| Intent accuracy | {r['intent_ok']}/{r['n']} ({r['intent_ok'] / r['n']:.0%}) |",
        f"| Answers containing the expected facts | {r['answer_ok']}/{r['answer_n']} ({r['answer_ok'] / max(r['answer_n'], 1):.0%}) |",
        f"| Retrieval recall@3 baseline BM25 / enhanced | {recall(r['base']):.0%} / {recall(r['enh']):.0%} ({len(r['enh'])} questions) |",
        f"| Retrieval MRR baseline BM25 / enhanced | {mrr(r['base']):.2f} / {mrr(r['enh']):.2f} |",
        f"| Personal-data requests refused | {r['refused']}/{r['n_refuse']} |",
        f"| Metadata questions wrongly refused | {r['false_refusals']}/{r['n_allow']} |",
        "",
        *(["Failures:", ""] + [f"- {f}" for f in r["failures"]] + [""] if r["failures"] else ["No failures.", ""]),
    ]


def main() -> None:
    catalog = load_catalog(ROOT / "catalog" / "catalog.yaml")
    spec = yaml.safe_load(open(ROOT / "eval" / "questions.yaml", encoding="utf-8"))
    bot = Assistant(catalog, Retriever(catalog, "enhanced"))
    baseline, enhanced = Retriever(catalog, "baseline"), Retriever(catalog, "enhanced")

    dev = evaluate(bot, baseline, enhanced, spec["questions"], spec["must_refuse"], spec["must_allow"])
    h = spec["heldout"]
    held = evaluate(bot, baseline, enhanced, h["questions"], h["must_refuse"], h["must_allow"])

    n_cols = sum(len(a.get("columns", [])) for a in catalog.assets.values())
    lines = ["# Evaluation results", "",
             f"Catalog: {len(catalog.assets)} assets, {n_cols} columns, {len(catalog.terms)} glossary terms. English and French questions.", "",
             *table("Dev set (used while tuning, optimistic)", dev),
             *table("Held-out set (after fixing the failures of its first run: 11/20 intent accuracy; no longer a clean estimate)", held),
             "Caveat: the catalog and both question sets were written by the same person, so even the held-out numbers",
             "describe a small controlled example, not performance on a real company catalog."]
    out = "\n".join(lines)
    print(out)
    (ROOT / "eval" / "results.md").write_text(out + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
