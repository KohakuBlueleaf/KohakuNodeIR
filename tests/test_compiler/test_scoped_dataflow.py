"""Tests for scoped @dataflow: blocks in KohakuNodeIR."""

from __future__ import annotations

from kohakunode.ast.nodes import Assignment, DataflowBlock, FuncCall, Jump
from kohakunode.compiler.dataflow import DataflowCompiler
from kohakunode.parser.parser import parse
from kohakunode.serializer.writer import Writer


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def test_scoped_dataflow_parse():
    """@dataflow: block parses correctly."""
    prog = parse(
        """
@dataflow:
    ()load(model)
    (model)process(result)
"""
    )
    assert isinstance(prog.body[0], DataflowBlock)
    assert len(prog.body[0].body) == 2


def test_scoped_dataflow_with_controlflow():
    """Mixed control flow + dataflow in same file."""
    prog = parse(
        """
counter = 0
()jump(`loop`)
loop:
    (counter, 1)add(counter)
    (counter, 5)less_than(cond)
    (cond)branch(`cont`, `done`)
    cont:
        ()jump(`loop`)
    done:

@dataflow:
    ()load(model)
    (model)process(out)
"""
    )
    assert isinstance(prog.body[0], Assignment)  # counter = 0
    assert isinstance(prog.body[1], Jump)  # jump
    # Find the DataflowBlock
    df_blocks = [s for s in prog.body if isinstance(s, DataflowBlock)]
    assert len(df_blocks) == 1


# ---------------------------------------------------------------------------
# Compilation
# ---------------------------------------------------------------------------


def test_scoped_dataflow_compile():
    """@dataflow: block gets expanded to sequential statements."""
    prog = parse(
        """
x = 1
@dataflow:
    (x)process_b(z)
    ()generate(y)
    (y, z)combine(result)
"""
    )
    compiler = DataflowCompiler()
    result = compiler.transform(prog)
    # DataflowBlock should be gone
    assert not any(isinstance(s, DataflowBlock) for s in result.body)
    # generate should come before combine (dependency order)
    names = []
    for stmt in result.body:
        if isinstance(stmt, FuncCall):
            names.append(stmt.func_name)
    assert "generate" in names
    assert "combine" in names
    assert names.index("generate") < names.index("combine")


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def test_dataflow_block_serialization():
    """Writer outputs @dataflow: block correctly."""
    prog = parse(
        """
@dataflow:
    ()load(a)
    (a)process(b)
"""
    )
    writer = Writer()
    text = writer.write(prog)
    assert "@dataflow:" in text


# ---------------------------------------------------------------------------
# Round-trip / transformation visibility
# ---------------------------------------------------------------------------


def test_show_transformation():
    """Print the before/after of dataflow compilation for visibility."""
    source = """
x = 10
@dataflow:
    (x, y)combine(result)
    ()generate(y)
    (result)finalize(output)
"""
    prog = parse(source)
    writer = Writer()
    before = writer.write(prog)

    compiler = DataflowCompiler()
    compiled = compiler.transform(prog)
    after = writer.write(compiled)

    print("=== BEFORE (with @dataflow:) ===")
    print(before)
    print("=== AFTER (compiled to sequential) ===")
    print(after)

    # Verify the dataflow block was expanded
    assert "@dataflow:" in before
    assert "@dataflow:" not in after
