"""Shows the @dataflow: block before/after compilation transformation.

This demonstrates how the engine resolves data dependencies to determine
execution order within @dataflow: blocks.
"""

from kohakunode import parse
from kohakunode.compiler.dataflow import DataflowCompiler
from kohakunode.serializer.writer import Writer

source = """\
# Input value
x = 10

# Dataflow block: statements can be in ANY order.
# The compiler sorts them by data dependencies.
@dataflow:
    (x, y)multiply(product)
    (2)to_float(y)
    (product)to_string(product_str)
    ("Result: ", product_str)concat(message)

# After the dataflow block, continue with control flow
(message)print()
"""

if __name__ == "__main__":
    prog = parse(source)
    writer = Writer()

    print("=" * 60)
    print("BEFORE (as written — @dataflow: block, any order)")
    print("=" * 60)
    print(writer.write(prog))

    compiler = DataflowCompiler()
    compiled = compiler.transform(prog)

    print("=" * 60)
    print("AFTER (compiled — topologically sorted, no @dataflow:)")
    print("=" * 60)
    print(writer.write(compiled))

    print("=" * 60)
    print("Notice: (2)to_float(y) moved before (x,y)multiply(product)")
    print("because multiply depends on y, which to_float produces.")
