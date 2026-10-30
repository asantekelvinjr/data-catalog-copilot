"""Load the YAML catalog into searchable documents and a lineage graph."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import networkx as nx
import yaml


@dataclass
class Doc:
    id: str            # e.g. "asset:core.fact_payment", "column:core.fact_payment.days_past_due", "term:pii"
    kind: str          # "asset" | "column" | "term"
    title: str
    text: str          # text that is indexed
    asset_id: str | None = None
    meta: dict = field(default_factory=dict)


class Catalog:
    def __init__(self, raw: dict):
        self.company: str = raw.get("company", "")
        self.assets: dict[str, dict] = {a["id"]: a for a in raw["assets"]}
        self.terms: dict[str, dict] = {t["id"]: t for t in raw["terms"]}
        self.graph = self._build_graph()
        self.docs = self._build_docs()

    # ----------------------------------------------------------------- graph
    def _build_graph(self) -> nx.DiGraph:
        g = nx.DiGraph()
        for aid, a in self.assets.items():
            g.add_node(aid, type=a["type"], layer=a["layer"], owner=a["owner"],
                       criticality=a.get("criticality", "medium"))
        for aid, a in self.assets.items():
            for parent in a.get("upstream", []):
                if parent not in self.assets:
                    raise ValueError(f"{aid} lists unknown upstream asset {parent}")
                g.add_edge(parent, aid)  # edge direction = data flow
        if not nx.is_directed_acyclic_graph(g):
            raise ValueError("lineage graph contains a cycle")
        return g

    # ------------------------------------------------------------------ docs
    def _build_docs(self) -> list[Doc]:
        docs: list[Doc] = []
        for aid, a in self.assets.items():
            col_names = " ".join(c["name"] for c in a.get("columns", []))
            rules = " ".join(a.get("quality_rules", []))
            text = (f"{aid} {a['type']} {a['layer']} {a['description']} owner {a['owner']} "
                    f"steward {a['steward']} refresh {a['refresh']} {rules} columns {col_names}")
            docs.append(Doc(f"asset:{aid}", "asset", aid, text, aid))
            for c in a.get("columns", []):
                ctext = (f"{c['name']} column of {aid}. {c['description']}. type {c['type']} "
                         f"classification {c['classification'].replace('_', ' ')}")
                docs.append(Doc(f"column:{aid}.{c['name']}", "column", f"{aid}.{c['name']}", ctext, aid,
                                {"classification": c["classification"], "column": c["name"],
                                 "description": c["description"]}))
        for tid, t in self.terms.items():
            text = f"{t['name']} {' '.join(t['synonyms'])} {t['definition']}"
            docs.append(Doc(f"term:{tid}", "term", t["name"], text, None, {"term_id": tid}))
        return docs


def load_catalog(path: str | Path) -> Catalog:
    with open(path, encoding="utf-8") as fh:
        return Catalog(yaml.safe_load(fh))
