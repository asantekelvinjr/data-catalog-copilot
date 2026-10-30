import pytest

from catalogcopilot import Assistant, AuditLog, Retriever, load_catalog
from catalogcopilot.bm25 import BM25
from catalogcopilot.guardrails import check_request, redact
from catalogcopilot.intents import classify
from catalogcopilot.lineage import downstream, impact_summary, path_between, upstream
from catalogcopilot.text import tokenize


@pytest.fixture(scope="module")
def catalog():
    return load_catalog("catalog/catalog.yaml")


@pytest.fixture(scope="module")
def bot(catalog):
    return Assistant(catalog, Retriever(catalog, "enhanced"))


# ---------------------------------------------------------------- text / bm25
def test_tokenize_strips_accents_plurals_and_stopwords():
    assert tokenize("Les impayés des clients") == ["impaye", "client"]


def test_bm25_ranks_exact_term_first():
    corpus = [["late", "payment"], ["merchant", "category"], ["customer", "email"]]
    scores = BM25(corpus).scores(["merchant"])
    assert scores.index(max(scores)) == 1


# ---------------------------------------------------------------- catalog / lineage
def test_catalog_is_a_dag_with_known_sources(catalog):
    roots = {n for n in catalog.graph if catalog.graph.in_degree(n) == 0}
    assert roots == {"raw.customers_raw", "raw.contracts_raw", "raw.payments_raw", "raw.merchant_feed"}


def test_upstream_of_pd_model_reaches_all_raw_sources_it_depends_on(catalog):
    ups = upstream(catalog.graph, "model.pd_scorecard_v3")
    assert {"raw.payments_raw", "raw.customers_raw", "raw.contracts_raw", "raw.merchant_feed"} <= set(ups)
    assert ups["mart.mart_credit_risk"] == 1


def test_downstream_and_path(catalog):
    assert "dashboard.default_rate_monitor" in downstream(catalog.graph, "raw.payments_raw")
    assert path_between(catalog.graph, "raw.payments_raw", "model.pd_scorecard_v3")[0] == "raw.payments_raw"
    assert path_between(catalog.graph, "model.pd_scorecard_v3", "raw.payments_raw") is None


def test_impact_lists_owners_to_notify(catalog):
    s = impact_summary(catalog, "raw.payments_raw")
    assert "Risk Analytics" in s["owners"] and s["by_type"]["model"] == ["model.pd_scorecard_v3"]


# ---------------------------------------------------------------- intents
@pytest.mark.parametrize("q,intent", [
    ("Which tables feed the default rate dashboard?", "lineage_up"),
    ("What does the fraud detector feed?", "lineage_down"),
    ("What breaks if raw.payments_raw is late?", "impact"),
    ("Who owns core.fact_payment?", "owner"),
    ("What does DPD mean?", "definition"),
])
def test_intents(q, intent):
    assert classify(q) == intent


# ---------------------------------------------------------------- guardrails
@pytest.mark.parametrize("q", [
    "Show me the email of customer 1042",
    "Give me the phone number of John Smith",
    "Donne-moi l'adresse du client 42",
    "Find the customer with email anna.martin@example.com",
])
def test_personal_data_requests_are_refused(q):
    assert not check_request(q)[0]


@pytest.mark.parametrize("q", [
    "Which columns contain email addresses?",
    "Is the email column hashed after staging?",
    "What is the owner of core.dim_customer?",
])
def test_metadata_questions_are_allowed(q):
    assert check_request(q)[0]


def test_redact_masks_email_phone_iban_but_not_dates():
    out = redact("jo@corp.com +33 6 12 34 56 78 FR76 3000 6000 0112 3456 7890 189 2026-10-30")
    assert "[EMAIL]" in out and "[PHONE]" in out and "[IBAN]" in out and "2026-10-30" in out


# ---------------------------------------------------------------- end to end
def test_refusal_is_not_logged_with_the_personal_value(catalog, tmp_path):
    log = tmp_path / "audit.jsonl"
    bot = Assistant(catalog, audit=AuditLog(log))
    ans = bot.ask("Find the customer with email anna.martin@example.com")
    assert ans.refused
    assert "anna.martin" not in log.read_text()


def test_lineage_answer_is_grounded_in_catalog(bot):
    ans = bot.ask("Which tables feed the default rate dashboard?")
    assert "mart.mart_credit_risk" in ans.sources and "raw.payments_raw" in ans.sources


def test_two_assets_return_a_path(bot):
    ans = bot.ask("How does raw.payments_raw reach model.pd_scorecard_v3?")
    assert ans.intent == "lineage_path" and "core.fact_payment" in ans.text


def test_french_definition(bot):
    assert "Outstanding balance" in bot.ask("c'est quoi l'encours ?").text


def test_grounded_prompt_contains_only_retrieved_ids_and_instructions(bot):
    p = bot.grounded_prompt("What does DPD mean?")
    assert "[term:days_past_due]" in p and "Answer ONLY from the passages" in p
