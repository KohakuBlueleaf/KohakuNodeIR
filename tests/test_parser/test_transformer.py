"""Transformer tests: verify that parse() produces correct AST nodes."""


from kohakunode import parse
from kohakunode.ast.nodes import (
    Assignment,
    Branch,
    FuncCall,
    Identifier,
    Jump,
    KeywordArg,
    Literal,
    MetaAnnotation,
    ModeDecl,
    Namespace,
    Parallel,
    Parameter,
    Program,
    SubgraphDef,
    Switch,
    Wildcard,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_fixture(load_fixture, name: str) -> Program:
    return parse(load_fixture(name))


# ---------------------------------------------------------------------------
# test_basic_assignment
# ---------------------------------------------------------------------------

# basic_assignment.kir:
#   x = 42
#   name = "hello"
#   pi = 3.14
#   flag = True
#   empty = None
#   y = x


def test_basic_assignment(load_fixture) -> None:
    prog = _parse_fixture(load_fixture, "basic_assignment.kir")

    assert isinstance(prog, Program)
    assert len(prog.body) == 6

    # x = 42
    stmt = prog.body[0]
    assert isinstance(stmt, Assignment)
    assert stmt.target == "x"
    assert isinstance(stmt.value, Literal)
    assert stmt.value.literal_type == "int"
    assert stmt.value.value == 42

    # name = "hello"
    stmt = prog.body[1]
    assert isinstance(stmt, Assignment)
    assert stmt.target == "name"
    assert isinstance(stmt.value, Literal)
    assert stmt.value.literal_type == "str"
    assert stmt.value.value == "hello"

    # pi = 3.14
    stmt = prog.body[2]
    assert isinstance(stmt, Assignment)
    assert stmt.target == "pi"
    assert isinstance(stmt.value, Literal)
    assert stmt.value.literal_type == "float"
    assert abs(stmt.value.value - 3.14) < 1e-9

    # flag = True
    stmt = prog.body[3]
    assert isinstance(stmt, Assignment)
    assert stmt.target == "flag"
    assert isinstance(stmt.value, Literal)
    assert stmt.value.literal_type == "bool"
    assert stmt.value.value is True

    # empty = None
    stmt = prog.body[4]
    assert isinstance(stmt, Assignment)
    assert stmt.target == "empty"
    assert isinstance(stmt.value, Literal)
    assert stmt.value.literal_type == "none"
    assert stmt.value.value is None

    # y = x  (identifier RHS)
    stmt = prog.body[5]
    assert isinstance(stmt, Assignment)
    assert stmt.target == "y"
    assert isinstance(stmt.value, Identifier)
    assert stmt.value.name == "x"


# ---------------------------------------------------------------------------
# test_func_call
# ---------------------------------------------------------------------------

# func_call.kir:
#   ("./data/test.bin")load_data(x1, x2)
#   (x1, x2)process(result)
#   ()generate(value)
#   (value)consume()


def test_func_call(load_fixture) -> None:
    prog = _parse_fixture(load_fixture, "func_call.kir")

    assert isinstance(prog, Program)
    assert len(prog.body) == 4

    # ("./data/test.bin")load_data(x1, x2)
    call = prog.body[0]
    assert isinstance(call, FuncCall)
    assert call.func_name == "load_data"
    assert len(call.inputs) == 1
    assert isinstance(call.inputs[0], Literal)
    assert call.inputs[0].value == "./data/test.bin"
    assert call.outputs == ["x1", "x2"]

    # (x1, x2)process(result)
    call = prog.body[1]
    assert isinstance(call, FuncCall)
    assert call.func_name == "process"
    assert len(call.inputs) == 2
    assert isinstance(call.inputs[0], Identifier)
    assert call.inputs[0].name == "x1"
    assert isinstance(call.inputs[1], Identifier)
    assert call.inputs[1].name == "x2"
    assert call.outputs == ["result"]

    # ()generate(value)
    call = prog.body[2]
    assert isinstance(call, FuncCall)
    assert call.func_name == "generate"
    assert call.inputs == []
    assert call.outputs == ["value"]

    # (value)consume()
    call = prog.body[3]
    assert isinstance(call, FuncCall)
    assert call.func_name == "consume"
    assert len(call.inputs) == 1
    assert isinstance(call.inputs[0], Identifier)
    assert call.inputs[0].name == "value"
    assert call.outputs == []


# ---------------------------------------------------------------------------
# test_keyword_args
# ---------------------------------------------------------------------------

# keyword_args.kir:
#   (x1, x2, mode="fast", threshold=0.5)process(result)
#   (img, verbose=False, quality=95)export(path)


def test_keyword_args(load_fixture) -> None:
    prog = _parse_fixture(load_fixture, "keyword_args.kir")

    assert len(prog.body) == 2

    # First call: two positional args + two keyword args.
    call = prog.body[0]
    assert isinstance(call, FuncCall)
    assert call.func_name == "process"

    assert isinstance(call.inputs[0], Identifier)
    assert call.inputs[0].name == "x1"
    assert isinstance(call.inputs[1], Identifier)
    assert call.inputs[1].name == "x2"

    kwarg_mode = call.inputs[2]
    assert isinstance(kwarg_mode, KeywordArg)
    assert kwarg_mode.name == "mode"
    assert isinstance(kwarg_mode.value, Literal)
    assert kwarg_mode.value.value == "fast"

    kwarg_thresh = call.inputs[3]
    assert isinstance(kwarg_thresh, KeywordArg)
    assert kwarg_thresh.name == "threshold"
    assert isinstance(kwarg_thresh.value, Literal)
    assert abs(kwarg_thresh.value.value - 0.5) < 1e-9

    # Second call: one positional + two keyword args.
    call = prog.body[1]
    assert isinstance(call, FuncCall)
    assert call.func_name == "export"

    assert isinstance(call.inputs[0], Identifier)
    assert call.inputs[0].name == "img"

    kwarg_verbose = call.inputs[1]
    assert isinstance(kwarg_verbose, KeywordArg)
    assert kwarg_verbose.name == "verbose"
    assert isinstance(kwarg_verbose.value, Literal)
    assert kwarg_verbose.value.value is False

    kwarg_quality = call.inputs[2]
    assert isinstance(kwarg_quality, KeywordArg)
    assert kwarg_quality.name == "quality"
    assert isinstance(kwarg_quality.value, Literal)
    assert kwarg_quality.value.value == 95


# ---------------------------------------------------------------------------
# test_wildcard
# ---------------------------------------------------------------------------

# wildcard.kir:
#   (x1, x2)process(_, result, _)
#   ("test")load(data, _)


def test_wildcard(load_fixture) -> None:
    prog = _parse_fixture(load_fixture, "wildcard.kir")

    assert len(prog.body) == 2

    call = prog.body[0]
    assert isinstance(call, FuncCall)
    assert call.func_name == "process"
    assert isinstance(call.outputs[0], Wildcard)
    assert call.outputs[1] == "result"
    assert isinstance(call.outputs[2], Wildcard)

    call = prog.body[1]
    assert isinstance(call, FuncCall)
    assert call.func_name == "load"
    assert call.outputs[0] == "data"
    assert isinstance(call.outputs[1], Wildcard)


# ---------------------------------------------------------------------------
# test_multiline
# ---------------------------------------------------------------------------

# multiline.kir:
#   (
#       x1, x2,
#       mode="bicubic",
#       threshold=0.5
#   )complex_filter(
#       filtered,
#       confidence
#   )


def test_multiline(load_fixture) -> None:
    prog = _parse_fixture(load_fixture, "multiline.kir")

    assert len(prog.body) == 1
    call = prog.body[0]
    assert isinstance(call, FuncCall)
    assert call.func_name == "complex_filter"

    # Two positional inputs.
    assert isinstance(call.inputs[0], Identifier)
    assert call.inputs[0].name == "x1"
    assert isinstance(call.inputs[1], Identifier)
    assert call.inputs[1].name == "x2"

    # Two keyword inputs.
    assert isinstance(call.inputs[2], KeywordArg)
    assert call.inputs[2].name == "mode"
    assert call.inputs[2].value.value == "bicubic"

    assert isinstance(call.inputs[3], KeywordArg)
    assert call.inputs[3].name == "threshold"
    assert abs(call.inputs[3].value.value - 0.5) < 1e-9

    # Two outputs.
    assert call.outputs == ["filtered", "confidence"]

    # Verify this is the same AST shape as the equivalent single-line form.
    single_line = "(x1, x2, mode=\"bicubic\", threshold=0.5)complex_filter(filtered, confidence)\n"
    prog2 = parse(single_line)
    call2 = prog2.body[0]

    assert call.func_name == call2.func_name
    assert call.outputs == call2.outputs
    assert len(call.inputs) == len(call2.inputs)
    for a, b in zip(call.inputs, call2.inputs):
        assert type(a) is type(b)


# ---------------------------------------------------------------------------
# test_metadata
# ---------------------------------------------------------------------------

# metadata.kir:
#   @meta node_id="n01" pos=(120, 300)
#   @meta color="blue" label="My Node"
#   (x1)process(x2)
#
#   @meta node_id="n02" pos=(400, 300)
#   (x2)another(x3)


def test_metadata(load_fixture) -> None:
    prog = _parse_fixture(load_fixture, "metadata.kir")

    # Two FuncCall statements after metadata collapsing.
    assert len(prog.body) == 2

    first = prog.body[0]
    assert isinstance(first, FuncCall)
    assert first.func_name == "process"
    assert first.metadata is not None
    assert len(first.metadata) == 2

    anno1, anno2 = first.metadata
    assert isinstance(anno1, MetaAnnotation)
    assert anno1.data["node_id"] == "n01"
    assert anno1.data["pos"] == (120, 300)

    assert isinstance(anno2, MetaAnnotation)
    assert anno2.data["color"] == "blue"
    assert anno2.data["label"] == "My Node"

    second = prog.body[1]
    assert isinstance(second, FuncCall)
    assert second.func_name == "another"
    assert second.metadata is not None
    assert len(second.metadata) == 1
    assert second.metadata[0].data["node_id"] == "n02"
    assert second.metadata[0].data["pos"] == (400, 300)


# ---------------------------------------------------------------------------
# test_namespace
# ---------------------------------------------------------------------------

# namespace_skip.kir:
#   x = 1
#   unused:
#       ("never runs")print()
#   (x)process(result)


def test_namespace(load_fixture) -> None:
    prog = _parse_fixture(load_fixture, "namespace_skip.kir")

    assert len(prog.body) == 3

    assert isinstance(prog.body[0], Assignment)
    assert prog.body[0].target == "x"

    ns = prog.body[1]
    assert isinstance(ns, Namespace)
    assert ns.name == "unused"
    assert len(ns.body) == 1
    assert isinstance(ns.body[0], FuncCall)
    assert ns.body[0].func_name == "print"

    assert isinstance(prog.body[2], FuncCall)
    assert prog.body[2].func_name == "process"


# ---------------------------------------------------------------------------
# test_branch
# ---------------------------------------------------------------------------

# branch.kir:
#   (x1, x2)compare(cond)
#   (cond)branch(`on_true`, `on_false`)
#   on_true:
#       (x1)process_a(out)
#   on_false:
#       (x2)process_b(out)
#   (out)final(result)


def test_branch(load_fixture) -> None:
    prog = _parse_fixture(load_fixture, "branch.kir")

    # compare, branch, on_true ns, on_false ns, final
    assert len(prog.body) == 5

    br = prog.body[1]
    assert isinstance(br, Branch)
    assert isinstance(br.condition, Identifier)
    assert br.condition.name == "cond"
    assert br.true_label == "on_true"
    assert br.false_label == "on_false"

    ns_true = prog.body[2]
    assert isinstance(ns_true, Namespace)
    assert ns_true.name == "on_true"

    ns_false = prog.body[3]
    assert isinstance(ns_false, Namespace)
    assert ns_false.name == "on_false"


# ---------------------------------------------------------------------------
# test_switch
# ---------------------------------------------------------------------------

# switch.kir:
#   (x)classify(category)
#   (category)switch(0=>`case_a`, 1=>`case_b`, _=>`case_default`)
#   case_a: ...
#   case_b: ...
#   case_default: ...


def test_switch(load_fixture) -> None:
    prog = _parse_fixture(load_fixture, "switch.kir")

    # classify, switch, case_a ns, case_b ns, case_default ns
    assert len(prog.body) == 5

    sw = prog.body[1]
    assert isinstance(sw, Switch)
    assert isinstance(sw.value, Identifier)
    assert sw.value.name == "category"

    assert len(sw.cases) == 2
    case0_expr, case0_label = sw.cases[0]
    assert isinstance(case0_expr, Literal)
    assert case0_expr.value == 0
    assert case0_label == "case_a"

    case1_expr, case1_label = sw.cases[1]
    assert isinstance(case1_expr, Literal)
    assert case1_expr.value == 1
    assert case1_label == "case_b"

    assert sw.default_label == "case_default"


# ---------------------------------------------------------------------------
# test_jump
# ---------------------------------------------------------------------------

# jump.kir:
#   x = 1
#   ()jump(`target`)
#   skipped:
#       ("never")print()
#   target:
#       (x)process(result)


def test_jump(load_fixture) -> None:
    prog = _parse_fixture(load_fixture, "jump.kir")

    assert len(prog.body) == 4

    jmp = prog.body[1]
    assert isinstance(jmp, Jump)
    assert jmp.target == "target"


# ---------------------------------------------------------------------------
# test_parallel
# ---------------------------------------------------------------------------

# parallel.kir:
#   (data)split(a, b)
#   ()parallel(`task_a`, `task_b`)
#   task_a:
#       (a)process_a(result_a)
#   task_b:
#       (b)process_b(result_b)
#   (result_a, result_b)merge(final)


def test_parallel(load_fixture) -> None:
    prog = _parse_fixture(load_fixture, "parallel.kir")

    # split, parallel, task_a ns, task_b ns, merge
    assert len(prog.body) == 5

    par = prog.body[1]
    assert isinstance(par, Parallel)
    assert par.labels == ["task_a", "task_b"]


# ---------------------------------------------------------------------------
# test_subgraph
# ---------------------------------------------------------------------------

# subgraph.kir:
#   @def (input, strength=1.0)preprocess(output):
#       (input)denoise(clean)
#       (clean, amount=strength)normalize(output)
#
#   (raw_data)preprocess(result)
#   (raw_data, strength=2.0)preprocess(result2)


def test_subgraph(load_fixture) -> None:
    prog = _parse_fixture(load_fixture, "subgraph.kir")

    # subgraph_def + 2 call statements
    assert len(prog.body) == 3

    defn = prog.body[0]
    assert isinstance(defn, SubgraphDef)
    assert defn.name == "preprocess"

    # Params: input (plain) and strength (with default 1.0).
    assert len(defn.params) == 2

    p_input = defn.params[0]
    assert isinstance(p_input, Parameter)
    assert p_input.name == "input"
    assert p_input.default is None

    p_strength = defn.params[1]
    assert isinstance(p_strength, Parameter)
    assert p_strength.name == "strength"
    assert isinstance(p_strength.default, Literal)
    assert abs(p_strength.default.value - 1.0) < 1e-9

    # Output names.
    assert defn.outputs == ["output"]

    # Body: two calls.
    assert len(defn.body) == 2
    assert isinstance(defn.body[0], FuncCall)
    assert defn.body[0].func_name == "denoise"
    assert isinstance(defn.body[1], FuncCall)
    assert defn.body[1].func_name == "normalize"

    # Remaining top-level calls.
    assert isinstance(prog.body[1], FuncCall)
    assert prog.body[1].func_name == "preprocess"
    assert isinstance(prog.body[2], FuncCall)
    assert prog.body[2].func_name == "preprocess"


# ---------------------------------------------------------------------------
# test_dataflow_mode
# ---------------------------------------------------------------------------

# dataflow.kir:
#   @mode dataflow
#   @meta node_id="1" pos=(0, 0)
#   ()load_model(model, clip)
#   ...


def test_dataflow_mode(load_fixture) -> None:
    prog = _parse_fixture(load_fixture, "dataflow.kir")

    assert prog.mode == "dataflow"
    # ModeDecl is consumed; body holds only the call statements.
    assert len(prog.body) == 4
    for stmt in prog.body:
        assert isinstance(stmt, FuncCall)


# ---------------------------------------------------------------------------
# test_collections
# ---------------------------------------------------------------------------

# collections.kir:
#   sizes = [512, 768, 1024]
#   config = {"mode": "fast", "quality": "high"}
#   nested = [1, [2, 3], "four"]
#   (sizes, config)process(result)


def test_collections(load_fixture) -> None:
    prog = _parse_fixture(load_fixture, "collections.kir")

    assert len(prog.body) == 4

    # sizes = [512, 768, 1024]
    sizes_stmt = prog.body[0]
    assert isinstance(sizes_stmt, Assignment)
    assert sizes_stmt.target == "sizes"
    sizes_lit = sizes_stmt.value
    assert isinstance(sizes_lit, Literal)
    assert sizes_lit.literal_type == "list"
    assert len(sizes_lit.value) == 3
    assert sizes_lit.value[0] == 512
    assert sizes_lit.value[1] == 768
    assert sizes_lit.value[2] == 1024

    # config = {"mode": "fast", "quality": "high"}
    config_stmt = prog.body[1]
    assert isinstance(config_stmt, Assignment)
    assert config_stmt.target == "config"
    config_lit = config_stmt.value
    assert isinstance(config_lit, Literal)
    assert config_lit.literal_type == "dict"
    # Dict values are raw Python values.
    assert config_lit.value == {"mode": "fast", "quality": "high"}

    # nested = [1, [2, 3], "four"]
    nested_stmt = prog.body[2]
    assert isinstance(nested_stmt, Assignment)
    nested_lit = nested_stmt.value
    assert isinstance(nested_lit, Literal)
    assert nested_lit.literal_type == "list"
    assert nested_lit.value[0] == 1
    assert nested_lit.value[1] == [2, 3]
    assert nested_lit.value[2] == "four"


# ---------------------------------------------------------------------------
# test_nested_namespace
# ---------------------------------------------------------------------------

# nested_namespace.kir (loop.kir has nested namespaces via branch inside switch):
# Use the loop fixture which has:
#   counter = 0
#   limit = 5
#   ()jump(`loop_body`)
#   loop_body:
#       (counter, 1)add(counter)
#       (counter, limit)less_than(keep_going)
#       (keep_going)branch(`continue_loop`, `exit_loop`)
#       continue_loop:
#           ()jump(`loop_body`)
#       exit_loop:
#   (counter)print()


def test_nested_namespace(load_fixture) -> None:
    prog = _parse_fixture(load_fixture, "loop.kir")

    # counter=0, limit=5, jump, loop_body ns, print
    assert len(prog.body) == 5

    loop_body = prog.body[3]
    assert isinstance(loop_body, Namespace)
    assert loop_body.name == "loop_body"

    # Body: add, less_than, branch, continue_loop ns, exit_loop ns
    assert len(loop_body.body) == 5

    branch_stmt = loop_body.body[2]
    assert isinstance(branch_stmt, Branch)
    assert branch_stmt.true_label == "continue_loop"
    assert branch_stmt.false_label == "exit_loop"

    continue_ns = loop_body.body[3]
    assert isinstance(continue_ns, Namespace)
    assert continue_ns.name == "continue_loop"
    assert len(continue_ns.body) == 1
    assert isinstance(continue_ns.body[0], Jump)
    assert continue_ns.body[0].target == "loop_body"

    exit_ns = loop_body.body[4]
    assert isinstance(exit_ns, Namespace)
    assert exit_ns.name == "exit_loop"
    assert exit_ns.body == []
