"""The tree of calls a recursion makes, for showing why it repeats its own work.

A lesson describes the recursion in three numbers: where it starts, how much each call steps
down by, and where it stops. `call_tree` works out every call from that, so the picture cannot
show a call the recursion would not make. The schema, the compiler, the validator and the
renderer all read the tree from here.
"""
from __future__ import annotations

MAX_CALLS = 31      # what stays readable in the frame


def call_tree(start: int, steps: list[int], stop: int) -> list[dict]:
    """Every call, in the order the tree is revealed (level by level, left to right). A call for
    value `n` makes one call for `n - step` per step, unless `n` has reached `stop`."""
    nodes = [{"id": 0, "value": start, "parent": None, "depth": 0}]
    level = [nodes[0]]
    while level and len(nodes) <= MAX_CALLS:
        following = []
        for node in level:
            if node["value"] <= stop:
                continue
            for step in steps:
                if node["value"] - step < 0:
                    continue
                child = {"id": len(nodes), "value": node["value"] - step, "parent": node["id"],
                         "depth": node["depth"] + 1}
                nodes.append(child)
                following.append(child)
        level = following
    return nodes


def shown_to_depth(nodes: list[dict], depth: int | None) -> int:
    """How many calls are on screen when the tree is revealed down to `depth` (all, if None)."""
    return len(nodes) if depth is None else sum(node["depth"] <= depth for node in nodes)


def repeats(payload: dict) -> list[str]:
    """What the tree says under itself about each value picked out: '3 is worked out 2 times'."""
    seen = [node["value"] for node in payload["nodes"][:payload.get("shown", 1)]]
    return [f"{value} is worked out {seen.count(value)} times" for value in payload.get("marked") or []]


def positions(nodes: list[dict], spacing: float = 62, level: float = 74) -> tuple[dict[int, tuple[float, float]], float, float]:
    """Where each call is drawn: leaves spread evenly left to right, a parent centred over its
    children. Returns the positions and the width and height of the drawing."""
    children: dict[int, list[int]] = {node["id"]: [] for node in nodes}
    for node in nodes:
        if node["parent"] is not None:
            children[node["parent"]].append(node["id"])
    across: dict[int, float] = {}
    leaves = 0

    def place(node_id: int) -> float:
        nonlocal leaves
        if not children[node_id]:
            across[node_id] = leaves * spacing + spacing / 2
            leaves += 1
        else:
            spots = [place(child) for child in children[node_id]]
            across[node_id] = (spots[0] + spots[-1]) / 2
        return across[node_id]

    place(0)
    depth = max(node["depth"] for node in nodes)
    where = {node["id"]: (across[node["id"]], node["depth"] * level + level / 2) for node in nodes}
    return where, leaves * spacing, (depth + 1) * level
