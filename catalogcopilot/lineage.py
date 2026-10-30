"""Lineage queries on top of the catalog graph (NetworkX)."""
from __future__ import annotations

import networkx as nx

from .loader import Catalog


def upstream(g: nx.DiGraph, node: str) -> dict[str, int]:
    """All ancestors of `node` with their distance in hops."""
    return _without_self(nx.single_source_shortest_path_length(g.reverse(copy=False), node), node)


def downstream(g: nx.DiGraph, node: str) -> dict[str, int]:
    """All descendants of `node` with their distance in hops."""
    return _without_self(nx.single_source_shortest_path_length(g, node), node)


def _without_self(d: dict[str, int], node: str) -> dict[str, int]:
    d = {k: v for k, v in d.items() if k != node}
    return dict(sorted(d.items(), key=lambda kv: (kv[1], kv[0])))


def path_between(g: nx.DiGraph, source: str, target: str) -> list[str] | None:
    try:
        return nx.shortest_path(g, source, target)
    except nx.NetworkXNoPath:
        return None


def impact_summary(catalog: Catalog, node: str) -> dict:
    """What breaks if `node` changes: affected assets grouped by type, and who to notify."""
    affected = downstream(catalog.graph, node)
    by_type: dict[str, list[str]] = {"table": [], "dashboard": [], "model": []}
    owners: set[str] = set()
    for aid in affected:
        by_type[catalog.assets[aid]["type"]].append(aid)
        owners.add(catalog.assets[aid]["owner"])
    critical = [a for a in affected if catalog.assets[a].get("criticality") == "high"]
    return {"affected": affected, "by_type": by_type, "owners": sorted(owners), "critical": critical}
