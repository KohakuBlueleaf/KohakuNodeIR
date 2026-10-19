"""Stand-in GBC nodes: deterministic, model-free, enough to run gbc.kir end to end."""

from kohakunode import NodeLibrary

LIB = NodeLibrary("gbc")

# What each detected object contains, for the next round of expansion.
PARTS = {"cat": ["ear", "tail"], "table": ["leg"], "phone": ["screen"]}


@LIB.node(outputs=["elements"])
def seed_elements(description: str, brief: str) -> list:
    return [w.strip() for w in brief.split(",") if w.strip()]


@LIB.node(outputs=["boxes"])
def detect(image: str, elements: list) -> list:
    return [
        {"label": e, "box": [10 * i, 10 * i, 50, 50], "parent": None}
        for i, e in enumerate(elements)
    ]


@LIB.node(outputs=["graph", "seen"])
def empty_state() -> tuple:
    return {"nodes": [], "relations": [], "round": 0}, []


@LIB.node(outputs=["seen", "is_new"])
def register(seen: list, box: dict) -> tuple:
    key = (box["label"], box["parent"])
    if list(key) in seen:
        return seen, False
    return [*seen, list(key)], True


@LIB.node(outputs=["crop"])
def crop(image: str, box: dict) -> str:
    return f"{image}@{box['box']}"


@LIB.node(outputs=["node"])
def entity(crop: str, box: dict) -> dict:
    label = box["label"]
    return {
        "label": label,
        "parent": box["parent"],
        "caption": f"a {label} ({crop})",
        "parts": PARTS.get(label, []),
    }


@LIB.node(outputs=["graph", "children"])
def assemble(graph: dict, expanded: list) -> tuple:
    nodes = [n for n in expanded if n is not None]
    children = [
        {"label": part, "box": [0, 0, 10, 10], "parent": n["label"]}
        for n in nodes
        for part in n["parts"]
    ]
    graph = {**graph, "nodes": graph["nodes"] + nodes, "round": graph["round"] + 1}
    return graph, children


@LIB.node(outputs=["frontier", "more"])
def next_frontier(children: list, graph: dict, budget: int) -> tuple:
    return children, bool(children) and graph["round"] < budget


@LIB.node(outputs=["queries"])
def relational_queries(graph: dict) -> list:
    labels = [n["label"] for n in graph["nodes"] if n["parent"] is None]
    return (
        [[a, b] for i, a in enumerate(labels) for b in labels[i + 1 :]]
        if graph["round"] == 1
        else []
    )


@LIB.node(outputs=["rel"])
def relational(image: str, q: list) -> dict:
    return {"from": q[0], "to": q[1], "text": f"the {q[0]} is near the {q[1]}"}


@LIB.node(outputs=["graph"])
def attach_relation(graph: dict, rel: dict) -> dict:
    return {**graph, "relations": graph["relations"] + [rel]}


@LIB.node(outputs=["result"])
def to_gbc(graph: dict) -> dict:
    return {
        "nodes": [f"{n['parent'] or 'image'} -> {n['label']}" for n in graph["nodes"]],
        "relations": [r["text"] for r in graph["relations"]],
        "rounds": graph["round"],
    }
