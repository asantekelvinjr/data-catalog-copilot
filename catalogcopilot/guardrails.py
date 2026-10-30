"""Data-protection guardrails.

The assistant only knows METADATA (descriptions, owners, lineage). It must never be turned into a
way to look up personal data, so it:
  1. refuses questions that ask for personal values about individuals,
  2. redacts anything that looks like an email / phone / IBAN before it is shown or logged,
  3. writes an audit log (with redacted questions) so every interaction can be reviewed.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from .text import normalize

PII_FIELD = (r"(e ?mail|mail|phone|telephone|mobile|portable|address|adresse|iban|birth ?date|date of birth|"
             r"date de naissance|full name|first name|last name|surname|customer name|client name|"
             r"nom du client|nom complet|prenom|passport|passeport|ssn)")
METADATA_HINT = (r"(column|columns|field|fields|table|tables|schema|contain|contains|stored|store|"
                 r"classif\w*|which|where|colonne|colonnes|champ|champs|contient|contiennent|"
                 r"hashed|pseudonym\w*|masked|protected|layer|layers|downstream|upstream|anonymi[sz]ed)")
INDIVIDUAL = r"(customer|customers|client|clients|user|users|person|borrower|emprunteur|him|her|them|\d{3,})"
NAME_PAIR = re.compile(r"\b[A-Z][a-z]+ [A-Z][a-z]+\b")  # e.g. "John Smith" (checked on the original text)

REFUSAL = ("I can't return personal data about individuals. I only describe the data catalog (metadata): "
           "which table or column holds a type of data, how it is classified, who owns it and where it flows. "
           "If you need access to personal data, ask the data steward of the source table through the usual "
           "access-request process.")


def check_request(question: str) -> tuple[bool, str]:
    """Return (allowed, reason)."""
    if redact(question) != question:
        return False, "question contains personal data (email, phone or IBAN)"
    q = normalize(question)
    mentions_pii = re.search(rf"\b{PII_FIELD}s?\b", q) is not None
    asks_metadata = re.search(rf"\b{METADATA_HINT}\b", q) is not None
    about_individual = re.search(rf"\b{INDIVIDUAL}\b", q) is not None or NAME_PAIR.search(question) is not None
    # Any question that pairs a personal-data field with an individual is refused unless it is clearly
    # about the schema ("which column ...", "is it hashed ..."): safer to over-refuse than to leak.
    if mentions_pii and about_individual and not asks_metadata:
        return False, "request for personal values about an individual"
    if re.search(r"\b(lives|live|resides|habite|habitent)\b", q) and about_individual and not asks_metadata:
        return False, "request about where an individual lives"
    if mentions_pii and re.search(r"\b(customer|client)\s*(id\s*)?#?\d+\b", q):
        return False, "request about a specific customer"
    return True, "ok"


_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){3,7}(?: ?[A-Z0-9]{1,4})?\b")
_PHONE = re.compile(r"(?<!\w)\+?\d[\d ().-]{7,}\d(?!\w)")


def _mask_phone(match: re.Match) -> str:
    digits = re.sub(r"\D", "", match.group(0))
    # 9+ digits looks like a phone number; shorter runs (years, ids, "90 days") are left alone.
    # Dates such as 2026-10-30 only have 8 digits, so they survive too.
    return "[PHONE]" if len(digits) >= 9 else match.group(0)


def redact(text: str) -> str:
    text = _EMAIL.sub("[EMAIL]", text)
    text = _IBAN.sub("[IBAN]", text)
    return _PHONE.sub(_mask_phone, text)


class AuditLog:
    """Append-only JSON-lines log. Questions are redacted before being written."""

    def __init__(self, path: str | Path | None):
        self.path = Path(path) if path else None

    def write(self, **fields) -> None:
        if not self.path:
            return
        record = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), **fields}
        if "question" in record:
            record["question"] = redact(record["question"])
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
