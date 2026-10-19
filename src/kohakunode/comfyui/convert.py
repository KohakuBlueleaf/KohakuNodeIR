"""ComfyUI workflows to KIR and back.

Both ComfyUI formats are read: the API prompt (``{id: {class_type, inputs}}``)
and the UI workflow (``{nodes, links}``). A workflow is pure dataflow, so it
becomes one `@dataflow:` block of calls; node ids and UI positions travel in
`@meta`. Links become names ``n<id>_<output index>``. Export writes the API
prompt format.
"""

from kohakunode.errors import KirError
from kohakunode.syntax.ast import Arg, Call, Dataflow, Literal, Name, Program, walk


def _out_name(node_id, index: int) -> str:
    return f"n{node_id}_{index}"


def _node_name(class_type: str) -> str:
    """ComfyUI class names may hold characters KIR names cannot."""
    out = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in class_type)
    return out if out and not out[0].isdigit() else f"n_{out}"


def from_api(prompt: dict) -> Program:
    uses: dict[str, int] = {}
    for node in prompt.values():
        for v in node.get("inputs", {}).values():
            if isinstance(v, list) and len(v) == 2 and isinstance(v[1], int):
                src = str(v[0])
                uses[src] = max(uses.get(src, 0), v[1] + 1)
    calls = []
    for nid in sorted(prompt, key=lambda k: (len(str(k)), str(k))):
        node = prompt[nid]
        args = []
        for key, v in node.get("inputs", {}).items():
            if isinstance(v, list) and len(v) == 2 and isinstance(v[1], int):
                args.append(Arg(Name(_out_name(v[0], v[1])), key))
            else:
                args.append(Arg(Literal(v), key))
        outs = [_out_name(nid, i) for i in range(uses.get(str(nid), 0))]
        meta = {"node_id": f"n{nid}", "comfy_class": node["class_type"]}
        if "_meta" in node:
            meta["comfy_meta"] = node["_meta"]
        calls.append(Call(_node_name(node["class_type"]), args, outs, meta=meta))
    return Program(body=[Dataflow(calls)])


def from_ui(workflow: dict) -> Program:
    link_src = {link[0]: (link[1], link[2]) for link in workflow.get("links", [])}
    calls = []
    for node in sorted(workflow["nodes"], key=lambda n: n["id"]):
        args = []
        for inp in node.get("inputs", []):
            if inp.get("link") is not None and inp["link"] in link_src:
                src, idx = link_src[inp["link"]]
                args.append(Arg(Name(_out_name(src, idx)), inp["name"]))
        widgets = node.get("widgets_values") or []
        if isinstance(widgets, dict):  # some custom nodes store named widgets
            widgets = list(widgets.values())
        for i, v in enumerate(widgets):
            args.append(Arg(Literal(v), f"widget_{i}"))
        outs = [_out_name(node["id"], i) for i, _ in enumerate(node.get("outputs") or [])]
        meta = {"node_id": f"n{node['id']}", "comfy_class": node["type"]}
        if "pos" in node:
            pos = node["pos"]
            meta["pos"] = tuple(pos.values()) if isinstance(pos, dict) else tuple(pos)
        calls.append(Call(_node_name(node["type"]), args, outs, meta=meta))
    return Program(body=[Dataflow(calls)])


def from_comfyui(data: dict) -> Program:
    """Read either ComfyUI format."""
    if "nodes" in data and "links" in data:
        return from_ui(data)
    if all(isinstance(v, dict) and "class_type" in v for v in data.values()):
        return from_api(data)
    raise KirError("not a ComfyUI workflow or API prompt")


def to_api(program: Program) -> dict:
    """The API prompt of a program made only of calls."""
    producer: dict[str, tuple[str, int]] = {}
    calls = [s for s in walk(program.body) if isinstance(s, Call)]
    ids = {}
    for k, c in enumerate(calls, start=1):
        nid = str(c.meta.get("node_id", k)).removeprefix("n")
        ids[id(c)] = nid
        for i, o in enumerate(c.outs):
            if o is not None:
                producer[o] = (nid, i)
    prompt = {}
    for c in calls:
        inputs = {}
        for i, a in enumerate(c.args):
            key = a.key or f"in{i}"
            if isinstance(a.value, Name):
                if a.value.id not in producer:
                    raise KirError(f"{a.value.id!r} has no producing node")
                src, idx = producer[a.value.id]
                inputs[key] = [src, idx]
            else:
                inputs[key] = a.value.value
        entry = {"inputs": inputs, "class_type": c.meta.get("comfy_class", c.name)}
        if "comfy_meta" in c.meta:
            entry["_meta"] = c.meta["comfy_meta"]
        prompt[ids[id(c)]] = entry
    return prompt
