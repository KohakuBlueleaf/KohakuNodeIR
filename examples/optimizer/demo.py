"""Optimizer demo — shows before/after for each L4 optimization pass.

Usage: python examples/optimizer/demo.py
"""

from pathlib import Path

from kohakunode import parse
from kohakunode.compiler.dead_code import DeadCodePass
from kohakunode.compiler.optimizer import (
    BranchSimplifier,
    CommonSubexprEliminator,
    DeadNamespaceEliminator,
    Optimizer,
)
from kohakunode.serializer.writer import Writer

SEP = "=" * 60
w = Writer()


def show(title: str, source: str) -> None:
    print(f"\n{SEP}")
    print(f"  {title}")
    print(SEP)
    print(source)


# ---------------------------------------------------------------------------
# 1. Branch Simplification
# ---------------------------------------------------------------------------

src_branch = """\
debug_mode = True
(debug_mode)branch(`debug_path`, `prod_path`)
debug_path:
    ("Debug: starting pipeline")log()
prod_path:
    ("Starting pipeline")log()
"""

prog = parse(src_branch)
show("1. BRANCH SIMPLIFICATION — before", w.write(prog))

result = BranchSimplifier().transform(prog)
result = DeadNamespaceEliminator().transform(result)
show("1. BRANCH SIMPLIFICATION — after", w.write(result))
print("  → Constant True condition folded, only debug_path survives.")

# ---------------------------------------------------------------------------
# 2. Dead Code Elimination
# ---------------------------------------------------------------------------

src_dead = """\
temp_a = 100
temp_b = 200
temp_c = 300
x = 10
y = 20
(x, y)add(result)
(result)print()
"""

prog = parse(src_dead)
show("2. DEAD CODE ELIMINATION — before", w.write(prog))

result = DeadCodePass().transform(prog)
show("2. DEAD CODE ELIMINATION — after", w.write(result))
print("  → temp_a, temp_b, temp_c removed (never referenced).")

# ---------------------------------------------------------------------------
# 3. Common Subexpression Elimination
# ---------------------------------------------------------------------------

src_cse = """\
(data)normalize(norm1)
(data)normalize(norm2)
(norm1)process_a(out_a)
(norm2)process_b(out_b)
(out_a, out_b)combine(final)
"""

prog = parse(src_cse)
show("3. CSE — before", w.write(prog))

result = CommonSubexprEliminator().transform(prog)
show("3. CSE — after", w.write(result))
print("  → Second normalize(data) replaced with norm2 = norm1.")

# ---------------------------------------------------------------------------
# 4. All passes combined
# ---------------------------------------------------------------------------

src_combined = """\
debug = False
unused_setup = 42
(debug)branch(`verbose`, `quiet`)
verbose:
    ("VERBOSE MODE")print()
quiet:
    x = 10
    y = 20
    (x, y)add(sum)
    (x, y)add(sum_copy)
    (sum)to_string(text)
    (text)print()
"""

prog = parse(src_combined)
show("4. ALL PASSES COMBINED — before", w.write(prog))

opt = Optimizer(passes=["branch_simplify", "dead_code", "cse"])
result = opt.transform(prog)
show("4. ALL PASSES COMBINED — after", w.write(result))
print("  → Branch folded (False → quiet), verbose removed,")
print("    unused_setup removed, sum_copy replaced with sum_copy = sum.")

# ---------------------------------------------------------------------------
# 5. Full pipeline example
# ---------------------------------------------------------------------------

kir_file = Path(__file__).parent / "no_opt.kir"
if kir_file.exists():
    prog = parse(kir_file.read_text(encoding="utf-8"))
    show("5. FILE: no_opt.kir — before", w.write(prog))

    opt = Optimizer()
    result = opt.transform(prog)
    show("5. FILE: no_opt.kir — after", w.write(result))


if __name__ == "__main__":
    print("\n" + SEP)
    print("  Done! All optimizations demonstrated.")
    print(SEP)
