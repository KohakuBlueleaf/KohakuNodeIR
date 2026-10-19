"""Nodes for the v2 feature tour."""

from kohakunode import NodeLibrary

LIB = NodeLibrary("tour")


@LIB.node(outputs=["crop"])
def crop(image: str, box: int) -> str:
    return f"{image}[{box}]"


@LIB.node(outputs=["node"])
def entity(crop: str, max_tokens: int = 64) -> str:
    if crop.endswith("[13]"):
        raise ValueError("unreadable crop")
    return f"caption of {crop}"


@LIB.node(outputs=["flag"])
def is_new(box: int) -> bool:
    return box % 2 == 1


@LIB.node(outputs=["summary"])
def summarize(nodes: list) -> str:
    return "; ".join(str(n) for n in nodes)


@LIB.node(ordered=True)
def log_error(err: dict) -> None:
    print(f"[error] {err['node']}: {err['message']}")


@LIB.node(outputs=["graph"], mutates=["graph"])
def attach(graph: dict, node: str) -> dict:
    graph.setdefault("nodes", []).append(node)
    return graph
