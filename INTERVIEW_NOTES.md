# Interview notes: Data Catalog Copilot (60 seconds, then details)

**Pitch.** "I built an assistant that answers questions about a data catalog: definitions, where a column lives, lineage, impact of a change, ownership, and personal-data classification. It uses BM25 retrieval I wrote myself, a lineage graph in NetworkX and guardrails that refuse requests for personal data. Every answer cites the catalog ids it used."

**Why not just an LLM?** Answers must be traceable and safe. Retrieval and graph queries give exact, checkable facts (lineage is a graph problem, not a text problem). An LLM can sit on top, restricted to the retrieved passages (`grounded_prompt`).

## Questions you should be able to answer

1. **How does BM25 work?** It scores a document by summing, over query words, IDF (rare words count more) times a saturating term frequency, normalised by document length (`bm25.py`, k1 = 1.5, b = 0.75).
2. **Why a graph for lineage?** Upstream = ancestors, downstream = descendants, impact = downstream grouped by type and owner. NetworkX gives these as one-line traversals; the catalog is checked to be a DAG when loaded.
3. **What did the evaluation show?** 100% on questions I tuned on, 55% on fresh ones, 80% after fixing the failures. The lesson: report held-out numbers, not tuned ones.
4. **Did the "enhanced" retrieval help?** No, not on this catalog. Say it plainly; explain that synonym expansion adds noise when vocabulary already overlaps.
5. **How do the guardrails work, and what do they miss?** Rules combine personal-data words, references to individuals and "schema" words. They miss indirect phrasings, so production needs access control plus a trained classifier.
6. **How would you add an LLM?** Send `grounded_prompt()` to the model, check that every cited id was in the retrieved set, keep the audit log, never put personal data in the prompt.
7. **What would you do with real data?** Load an OpenMetadata or DataHub export, add column-level lineage, replace rules by a classifier, evaluate on questions written by other people.

## Honest limits to mention before they ask
Synthetic catalog; rule-based intents; lexical retrieval; same author for data and questions.
