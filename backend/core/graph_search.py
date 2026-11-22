"""A graph search worked out by code, for teaching breadth-first and depth-first search.

A lesson describes the graph (its nodes, its edges, where the search starts and what it looks
for); `search` runs the search and records every step, so the picture and the narration can only
show what the algorithm really does: which node is taken next, what waits in the queue or on the
stack, how far each node is from the start, and the path found. The schema, the compiler and the
renderer all read the steps from here, the way the recursion tree is read from `call_tree`.
"""
from __future__ import annotations

from collections import deque

MAX_NODES = 10      # what stays readable in the frame
MAX_EDGES = 14


def neighbours(nodes: list[str], edges: list[list[str]]) -> dict[str, list[str]]:
    """Each node's neighbours, in the order the nodes are listed: the order a search tries them."""
    order = {node: index for index, node in enumerate(nodes)}
    near: dict[str, list[str]] = {node: [] for node in nodes}
    for a, b in edges:
        if b not in near[a]:
            near[a].append(b)
        if a not in near[b]:
            near[b].append(a)
    return {node: sorted(found, key=order.__getitem__) for node, found in near.items()}


def problems(nodes: list[str], edges: list[list[str]], start: str, goal: str | None) -> list[str]:
    """Why a graph cannot be searched and drawn, in words a lesson step can act on."""
    faults = []
    if len(nodes) != len(set(nodes)):
        faults.append("two nodes share a name; give every node its own short name")
    if not 3 <= len(nodes) <= MAX_NODES:
        faults.append(f"the graph has {len(nodes)} nodes; use 3 to {MAX_NODES}")
    if len(edges) > MAX_EDGES:
        faults.append(f"the graph has {len(edges)} edges; use at most {MAX_EDGES}")
    known = set(nodes)
    for edge in edges:
        if len(edge) != 2 or not set(edge) <= known or edge[0] == edge[1]:
            faults.append(f"the edge {edge} must join two different nodes of the graph")
    if start not in known:
        faults.append(f"the start {start!r} is not a node of the graph")
    if goal is not None and goal not in known:
        faults.append(f"the goal {goal!r} is not a node of the graph")
    if faults:
        return faults
    reached = {step["node"] for step in search(nodes, edges, start, None, "bfs")["steps"]}
    if goal is not None and goal not in reached:
        faults.append(f"the goal {goal!r} cannot be reached from {start!r}; join it to the graph")
    lonely = sorted(set(nodes) - reached)
    if lonely:
        faults.append(f"{lonely} cannot be reached from {start!r}; join them or leave them out")
    return faults


def search(nodes: list[str], edges: list[list[str]], start: str, goal: str | None,
           order: str = "bfs") -> dict:
    """Run breadth-first ("bfs", a queue) or depth-first ("dfs", a stack) search from `start`.

    Returns every step in order: the node taken, the neighbours newly added to the frontier, the
    frontier left waiting (front of the queue or top of the stack first) and the node's distance
    in edges from the start along the route the search took (for BFS, the shortest). The search
    stops when it takes the goal; `path` is the route it found there."""
    near = neighbours(nodes, edges)
    parent: dict[str, str | None] = {}
    distance: dict[str, int] = {}
    steps: list[dict] = []
    if order == "bfs":
        # a node is marked found when it joins the queue, so it is queued once
        parent[start], distance[start] = None, 0
        queue: deque[str] = deque([start])
        while queue:
            node = queue.popleft()
            added = [other for other in near[node] if other not in parent]
            for other in added:
                parent[other], distance[other] = node, distance[node] + 1
                queue.append(other)
            steps.append({"node": node, "added": added, "frontier": list(queue),
                          "distance": distance[node]})
            if node == goal:
                break
    else:
        # a node is taken from the top of the stack; one already taken is passed over
        stack: list[tuple[str, str | None]] = [(start, None)]
        while stack:
            node, came = stack.pop()
            if node in parent:
                continue
            parent[node] = came
            distance[node] = 0 if came is None else distance[came] + 1
            added = [other for other in near[node] if other not in parent]
            stack.extend((other, node) for other in reversed(added))   # first listed on top
            waiting = []
            for other, _ in reversed(stack):
                if other not in parent and other not in waiting:
                    waiting.append(other)
            steps.append({"node": node, "added": added, "frontier": waiting,
                          "distance": distance[node]})
            if node == goal:
                break
    path: list[str] = []
    if goal is not None and goal in parent and any(step["node"] == goal for step in steps):
        at: str | None = goal
        while at is not None:
            path.append(at)
            at = parent[at]
        path.reverse()
    return {"steps": steps, "path": path, "distance": distance, "found_from": parent}


def layout(nodes: list[str], edges: list[list[str]], start: str) -> dict[str, tuple[int, int]]:
    """A fixed place for every node: its column is its distance from the start, its row its turn
    within that column. Edges then run from left to right, the way a search spreads."""
    distance = search(nodes, edges, start, None, "bfs")["distance"]
    columns: dict[int, list[str]] = {}
    for node in nodes:
        columns.setdefault(distance.get(node, max(distance.values()) + 1), []).append(node)
    return {node: (column, row) for column, members in columns.items()
            for row, node in enumerate(members)}


def frontier_line(payload: dict) -> str:
    """What waits to be taken, as the line under a graph: 'Queue: B, G' or 'Stack: C'."""
    name = "Stack" if payload.get("order") == "dfs" else "Queue"
    waiting = payload.get("frontier") or []
    return f"{name}: {', '.join(waiting)}" if waiting else f"{name}: empty"
