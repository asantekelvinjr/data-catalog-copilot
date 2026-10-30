# Data Catalog Copilot

A small, **explainable** assistant that answers questions about a company's data catalog: *what does this term mean, where is this column, where does this table come from, what breaks if it changes, who owns it, is it personal data?*

It combines three simple ideas instead of a black box:

1. **Retrieval**: BM25 (implemented from scratch) over table, column and glossary documents, with EN/FR synonym expansion.
2. **A lineage graph** (NetworkX): upstream sources, downstream consumers, impact analysis and paths between two assets.
3. **Data-protection guardrails**: the assistant only ever describes metadata. It refuses requests for personal values, redacts emails / phones / IBANs, and writes an audit log.

Every answer ends with the catalog ids it used, so each statement can be checked. `grounded_prompt()` shows how the same retrieved passages would be given to an LLM that must answer *only* from them, so a language model can be plugged in later without touching the rest.

> The catalog (`catalog/catalog.yaml`) is **entirely synthetic**: a fictional consumer-credit company with 18 assets, 89 columns and 14 glossary terms. No real company, customer or system is described.

## Run it

```bash
pip install -r requirements.txt
python -m catalogcopilot "Which tables feed the default rate dashboard?"
python -m catalogcopilot            # interactive mode
python -m catalogcopilot --prompt "What does DPD mean?"   # also prints the grounded LLM prompt
python eval/run_eval.py             # reproduce the evaluation
python -m pytest -q                 # 24 tests
```

## Examples

```
> What breaks if raw.payments_raw is late?
If raw.payments_raw changes or arrives late, 7 downstream assets are affected.
- tables: staging.stg_payments, core.fact_payment, mart.mart_collections, mart.mart_credit_risk
- dashboards: dashboard.collections_performance, dashboard.default_rate_monitor
- models: model.pd_scorecard_v3
- teams to warn: Collections Analytics, Data Engineering, Data Science, Risk Analytics

> c'est quoi l'encours ?
Outstanding balance: Total amount a customer still owes on a contract ... at the snapshot date.

> Show me the email of customer 1042
I can't return personal data about individuals. I only describe the data catalog (metadata) ...
```

## Architecture

```
question -> guardrails -> intent (regex rules) -> retriever (BM25 +/- synonyms) -> handler -> cited answer
                |                                         \-> lineage graph (NetworkX)          |
                \----------------------- audit log (redacted) <-----------------------------------/
```

| File | Role |
| --- | --- |
| `catalogcopilot/bm25.py` | Okapi BM25 from scratch |
| `catalogcopilot/retriever.py` | baseline vs enhanced retrieval (synonyms, intent-based boosts) |
| `catalogcopilot/lineage.py` | upstream / downstream / path / impact queries |
| `catalogcopilot/intents.py` | transparent, rule-based intent detection |
| `catalogcopilot/guardrails.py` | refusal rules, redaction, audit log |
| `catalogcopilot/assistant.py` | routing, answer formatting, grounded prompt |
| `eval/` | question sets and the evaluation runner |

## Evaluation (read the caveats)

`python eval/run_eval.py` reports two sets. The **dev set** (38 questions) was used while I wrote the rules, so its score is optimistic. The **held-out set** (20 questions, 5 + 3 guardrail probes) was written afterwards with different phrasing and was not used for tuning on its first run.

| | Dev set | Held-out, first run | Held-out, after fixes* |
| --- | --- | --- | --- |
| Intent accuracy | 38/38 | 11/20 (55%) | 16/20 (80%) |
| Answers with the expected facts | 18/18 | 5/9 | 8/9 |
| Personal-data requests refused | 7/7 | 2/5 | 4/5 |
| Metadata questions wrongly refused | 0/6 | 0/3 | 0/3 |
| Retrieval recall@3 (baseline BM25 / enhanced) | 100% / 100% | 91% / 91% | 91% / 91% |

\* After the first run I fixed the failures it exposed (new intent keywords, a stricter personal-data rule). The "after fixes" column is therefore no longer a clean estimate; the first-run column (also saved in `eval/results_first_run.md`) is the honest one.

What I learned:

- **Rules overfit.** Going from 100% on the dev set to 55% on fresh phrasing is the main finding. A trained intent classifier, or an LLM with the grounded prompt, is the natural next step.
- **The "enhanced" retriever did not beat plain BM25** on this small catalog (MRR 0.79 vs 0.82 on the held-out set): synonym expansion adds noise when documents already share vocabulary with the question. I kept both modes so the comparison stays reproducible.
- **Guardrails are heuristics.** The remaining miss ("Tell me where customer 9001 lives") shows why real deployments need access control and a trained classifier, not keyword rules alone.
- The catalog and the questions share one author, so none of these numbers estimate performance on a real catalog.

## Limits and next steps

- Retrieval is lexical; embeddings would help with paraphrases (and French) but need a model download.
- Intent rules are English/French keywords only.
- Next steps: swap the rules for an LLM call using `grounded_prompt()`, add a small Streamlit or React front end, load a real catalog export (e.g. OpenMetadata JSON), and add column-level lineage.
