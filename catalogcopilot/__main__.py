"""Command line: python -m catalogcopilot "Which tables feed the default rate dashboard?" """
from __future__ import annotations

import argparse
from pathlib import Path

from . import Assistant, AuditLog, Retriever, load_catalog

DEFAULT_CATALOG = Path(__file__).resolve().parent.parent / "catalog" / "catalog.yaml"


def main() -> None:
    p = argparse.ArgumentParser(description="Ask questions about a (synthetic) data catalog.")
    p.add_argument("question", nargs="*", help="question; leave empty for interactive mode")
    p.add_argument("--catalog", default=str(DEFAULT_CATALOG))
    p.add_argument("--mode", choices=["baseline", "enhanced"], default="enhanced")
    p.add_argument("--audit-log", default="audit_log.jsonl", help="JSONL audit file ('' to disable)")
    p.add_argument("--prompt", action="store_true", help="also print the grounded prompt an LLM would receive")
    args = p.parse_args()

    catalog = load_catalog(args.catalog)
    bot = Assistant(catalog, Retriever(catalog, args.mode), AuditLog(args.audit_log or None))

    def run(q: str) -> None:
        ans = bot.ask(q)
        print(f"[intent: {ans.intent}]\n{ans}\n")
        if args.prompt and not ans.refused:
            print("--- grounded prompt ---\n" + bot.grounded_prompt(q) + "\n")

    if args.question:
        run(" ".join(args.question))
        return
    print("Data Catalog Copilot (type 'exit' to quit)")
    while True:
        try:
            q = input("> ").strip()
        except EOFError:
            break
        if q.lower() in {"exit", "quit", ""}:
            break
        run(q)


if __name__ == "__main__":
    main()
