"""Hitung tata letak graf lineage dari ``lineage.json``.

Portal sengaja tidak memakai pustaka graf atau JavaScript. Posisi node dihitung
di server: kolom ditentukan layer, urutan vertikal dirapikan dengan barycenter
sederhana supaya garis sesedikit mungkin bersilangan, lalu edge digambar sebagai
kurva dengan panah. Hasilnya deterministik dan bisa langsung di-screenshot.
"""

from __future__ import annotations

from typing import Any

LAYER_ORDER = ("bronze", "silver", "gold")
LAYER_LABELS = {"bronze": "Bronze", "silver": "Silver", "gold": "Gold"}

NODE_W = 220
NODE_H = 40
ROW_GAP = 18
COL_GAP = 162
PAD = 12
TOP = 36
# Ruang di kanan untuk edge Gold ke Gold yang memutar di sisi kanan kolom.
RIGHT_PAD = 76


def _layer(node: dict[str, Any]) -> str:
    layer = str(node.get("layer") or "lain")
    return layer if layer else "lain"


def _label(layer: str) -> str:
    return LAYER_LABELS.get(layer, layer.capitalize())


def _neighbours(
    edges: list[dict[str, str]], node_id: str, *, downstream: bool
) -> list[str]:
    key_from, key_to = ("from", "to") if downstream else ("to", "from")
    return [edge[key_to] for edge in edges if edge[key_from] == node_id]


def _closure(edges: list[dict[str, str]], start: str, *, downstream: bool) -> set[str]:
    """Semua node yang bisa dicapai dari ``start``, termasuk ``start``."""
    seen = {start}
    queue = [start]
    while queue:
        current = queue.pop()
        for nxt in _neighbours(edges, current, downstream=downstream):
            if nxt not in seen:
                seen.add(nxt)
                queue.append(nxt)
    return seen


def _order_layers(
    layers: list[str],
    members: dict[str, list[str]],
    edges: list[dict[str, str]],
    original: dict[str, int],
) -> dict[str, list[str]]:
    """Urutkan node per layer dengan barycenter dari layer sebelumnya."""
    ordered: dict[str, list[str]] = {}
    rank: dict[str, int] = {}
    for index, layer in enumerate(layers):
        ids = list(members[layer])
        if index > 0:
            def barycenter(node_id: str) -> tuple[float, int]:
                positions = [
                    rank[edge["from"]]
                    for edge in edges
                    if edge["to"] == node_id and edge["from"] in rank
                ]
                if not positions:
                    return (float("inf"), original.get(node_id, 0))
                return (sum(positions) / len(positions), original.get(node_id, 0))

            ids.sort(key=barycenter)
        ordered[layer] = ids
        for position, node_id in enumerate(ids):
            rank[node_id] = position
    return ordered


def build_graph(
    lineage: dict[str, Any] | None,
    table_names: set[str],
    focus: str | None = None,
) -> dict[str, Any] | None:
    """Kembalikan geometri graf, atau None kalau lineage kosong."""
    if not lineage:
        return None

    raw_nodes = [
        node
        for node in (lineage.get("nodes") or [])
        if isinstance(node, dict) and node.get("id")
    ]
    if not raw_nodes:
        return None

    nodes_by_id = {str(node["id"]): node for node in raw_nodes}
    edges = [
        edge
        for edge in (lineage.get("edges") or [])
        if isinstance(edge, dict)
        and edge.get("from") in nodes_by_id
        and edge.get("to") in nodes_by_id
    ]

    members: dict[str, list[str]] = {}
    for node in raw_nodes:
        members.setdefault(_layer(node), []).append(str(node["id"]))
    known = [layer for layer in LAYER_ORDER if layer in members]
    extra = sorted(layer for layer in members if layer not in LAYER_ORDER)
    layers = known + extra

    original = {str(node["id"]): index for index, node in enumerate(raw_nodes)}
    ordered = _order_layers(layers, members, edges, original)

    rows = max(len(ids) for ids in ordered.values())
    plot_h = rows * NODE_H + max(0, rows - 1) * ROW_GAP
    width = (
        len(layers) * NODE_W
        + max(0, len(layers) - 1) * COL_GAP
        + PAD * 2
        + RIGHT_PAD
    )
    height = TOP + plot_h + PAD

    focus_id = focus if focus in nodes_by_id else None
    focus_missing = bool(focus) and focus_id is None
    if focus_id:
        upstream = _closure(edges, focus_id, downstream=False) - {focus_id}
        downstream = _closure(edges, focus_id, downstream=True) - {focus_id}
        active = upstream | downstream | {focus_id}
        visible_edges = [
            edge for edge in edges if edge["from"] in active and edge["to"] in active
        ]
    else:
        upstream, downstream, active = set(), set(), set(nodes_by_id)
        visible_edges = list(edges)

    geometry: dict[str, dict[str, Any]] = {}
    layer_meta = []
    for index, layer in enumerate(layers):
        ids = ordered[layer]
        column_h = len(ids) * NODE_H + max(0, len(ids) - 1) * ROW_GAP
        top = TOP + (plot_h - column_h) / 2
        x = PAD + index * (NODE_W + COL_GAP)
        layer_meta.append(
            {
                "id": layer,
                "label": _label(layer),
                "count": len(ids),
                "x": x,
            }
        )
        for position, node_id in enumerate(ids):
            y = top + position * (NODE_H + ROW_GAP)
            geometry[node_id] = {
                "id": node_id,
                "layer": layer,
                "type": str(nodes_by_id[node_id].get("type") or ""),
                "x": round(x, 1),
                "y": round(y, 1),
                "w": NODE_W,
                "h": NODE_H,
                "cx": round(x + NODE_W / 2, 1),
                "cy": round(y + NODE_H / 2, 1),
                "href": (
                    f"/catalog/{node_id}"
                    if node_id in table_names
                    else f"/lineage?focus={node_id}"
                ),
                "is_table": node_id in table_names,
                "dim": node_id not in active,
                "focus": node_id == focus_id,
            }

    outgoing: dict[str, list[str]] = {}
    incoming: dict[str, list[str]] = {}
    for edge in visible_edges:
        outgoing.setdefault(str(edge["from"]), []).append(str(edge["to"]))
        incoming.setdefault(str(edge["to"]), []).append(str(edge["from"]))

    def port(node: dict[str, Any], index: int, total: int) -> float:
        """Titik keluar/masuk yang disebar di sisi node supaya panah tidak menumpuk."""
        return node["y"] + node["h"] * (index + 1) / (total + 1)

    drawn_edges = []
    for edge in visible_edges:
        source = geometry[str(edge["from"])]
        target = geometry[str(edge["to"])]
        out_ids = outgoing[str(edge["from"])]
        in_ids = incoming[str(edge["to"])]
        x1 = source["x"] + NODE_W
        y1 = port(source, out_ids.index(str(edge["to"])), len(out_ids))
        x2 = target["x"]
        y2 = port(target, in_ids.index(str(edge["from"])), len(in_ids))
        if abs(source["x"] - target["x"]) < 1:
            # Edge di kolom yang sama memutar di sisi kanan supaya tidak
            # bertabrakan dengan panah masuk dari kolom sebelumnya.
            x1 = source["x"] + NODE_W
            x2 = target["x"] + NODE_W
            path = (
                f"M {x1} {y1} "
                f"C {x1 + 58} {y1}, {x2 + 58} {y2}, {x2} {y2}"
            )
            same_column = True
        else:
            bend = max(40.0, (x2 - x1) * 0.5)
            path = (
                f"M {x1} {y1} "
                f"C {x1 + bend} {y1}, {x2 - bend} {y2}, {x2} {y2}"
            )
            same_column = False
        drawn_edges.append(
            {
                "from": edge["from"],
                "to": edge["to"],
                "note": str(edge.get("note") or ""),
                "path": path,
                "into_gold": target["layer"] == "gold" and source["layer"] != "gold",
                "same_column": same_column,
                "dim": source["dim"] or target["dim"],
            }
        )

    return {
        "width": width,
        "height": height,
        "layers": layer_meta,
        "bands": [
            {"x": layer["x"], "width": NODE_W, "label": layer["label"]}
            for layer in layer_meta
        ],
        "nodes": list(geometry.values()),
        "edges": drawn_edges,
        "focus": focus_id,
        "focus_label": focus,
        "focus_detail": f"/catalog/{focus_id}" if focus_id in table_names else "",
        "focus_layer": (
            _label(geometry[focus_id]["layer"]) if focus_id else ""
        ),
        "focus_missing": focus_missing,
        "upstream": [node_id for node_id in nodes_by_id if node_id in upstream],
        "downstream": [node_id for node_id in nodes_by_id if node_id in downstream],
        "node_total": len(raw_nodes),
        "edge_total": len(edges),
        "visible_edge_total": len(drawn_edges),
    }
