"""The ``kir`` command."""

import argparse
import importlib
import json
import sys
from pathlib import Path

from kohakunode.compiler import compile_program
from kohakunode.errors import KirError
from kohakunode.graph import from_graph, to_graph
from kohakunode.lower import PASSES
from kohakunode.run import Interpreter
from kohakunode.sig.env import build_env
from kohakunode.sig.files import save_library
from kohakunode.sig.model import Library
from kohakunode.syntax import parse, write


def load_libraries(specs: list[str]) -> list[Library]:
    """``module`` (every Library it defines) or ``module:attr``, importable from the working directory."""
    if specs and str(Path.cwd()) not in sys.path:
        sys.path.insert(0, str(Path.cwd()))
    libs: list[Library] = []
    for spec in specs:
        module_name, _, attr = spec.partition(":")
        module = importlib.import_module(module_name)
        if attr:
            libs.append(getattr(module, attr))
        else:
            libs.extend(v for v in vars(module).values() if isinstance(v, Library))
    return libs


def _passes(text: str | None) -> list[str] | None:
    if text is None:
        return None
    names = [n for n in text.split(",") if n]
    unknown = [n for n in names if n not in PASSES]
    if unknown:
        raise KirError(f"unknown passes {unknown}; known: {list(PASSES)}")
    return names


def _compile(args):
    path = Path(args.file)
    program = parse(path.read_text(encoding="utf-8"))
    try:
        return compile_program(
            program,
            load_libraries(args.lib),
            path.parent,
            [Path(p) for p in args.sig_path],
            _passes(getattr(args, "passes", None)),
        )
    except ValueError as exc:
        raise KirError(str(exc)) from None


def cmd_check(args) -> int:
    path = Path(args.file)
    program = parse(path.read_text(encoding="utf-8"))
    try:
        compiled = compile_program(
            program, load_libraries(args.lib), path.parent, [Path(p) for p in args.sig_path]
        )
    except KirError as exc:
        diagnostics = getattr(exc, "diagnostics", None)
        for d in diagnostics or [exc]:
            print(f"{path}: {d}")
        return 1
    for d in compiled.diagnostics:
        print(f"{path}: {d}")
    return 0


def cmd_fmt(args) -> int:
    path = Path(args.file)
    text = write(parse(path.read_text(encoding="utf-8")))
    if args.write:
        path.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


def cmd_lower(args) -> int:
    compiled = _compile(args)
    if args.hash:
        print(f"semantic {compiled.semantic_hash}")
        print(f"full     {compiled.full_hash}")
        return 0
    _emit(write(compiled.lowered), args.output)
    return 0


def cmd_graph(args) -> int:
    path = Path(args.file)
    program = parse(path.read_text(encoding="utf-8"))
    env = build_env(
        program, load_libraries(args.lib), path.parent, [Path(p) for p in args.sig_path]
    )
    _emit(json.dumps(to_graph(program, env), indent=2, ensure_ascii=False) + "\n", args.output)
    return 0


def cmd_text(args) -> int:
    graph = json.loads(Path(args.file).read_text(encoding="utf-8"))
    _emit(write(from_graph(graph, with_meta=not args.no_meta)), args.output)
    return 0


def cmd_run(args) -> int:
    compiled = _compile(args)
    interp = Interpreter(compiled.lowered, compiled.env)
    interp.run()
    print(json.dumps(interp.source_values(), indent=2, ensure_ascii=False, default=repr))
    return 0


def cmd_sig(args) -> int:
    libs = load_libraries([args.module])
    if not libs:
        print(f"no node library found in {args.module}", file=sys.stderr)
        return 1
    for lib in libs:
        if len(libs) == 1 and args.output and args.output.endswith(".json"):
            out = Path(args.output)
        else:
            out = Path(args.output or ".") / f"{lib.name}.kirsig.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        save_library(lib, out)
        print(f"wrote {out}")
    return 0


def _emit(text: str, output: str | None) -> None:
    if output:
        Path(output).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="kir", description="KIR v2 toolchain")
    sub = p.add_subparsers(dest="command", required=True)

    def with_libs(sp):
        sp.add_argument(
            "--lib",
            action="append",
            default=[],
            help="Python module[:attr] defining node libraries",
        )
        sp.add_argument(
            "--sig-path", action="append", default=[], help="directory of .kirsig.json files"
        )

    sp = sub.add_parser("check", help="check a program")
    sp.add_argument("file")
    with_libs(sp)
    sp.set_defaults(fn=cmd_check)

    sp = sub.add_parser("fmt", help="print canonical text")
    sp.add_argument("file")
    sp.add_argument("-w", "--write", action="store_true", help="rewrite the file in place")
    sp.set_defaults(fn=cmd_fmt)

    passes_help = f"comma-separated passes to run, in order (default: all of {','.join(PASSES)})"
    sp = sub.add_parser("lower", help="print the program after the optimization passes")
    sp.add_argument("file")
    sp.add_argument("-o", "--output")
    sp.add_argument("--passes", help=passes_help)
    sp.add_argument("--hash", action="store_true", help="print the program hashes instead")
    with_libs(sp)
    sp.set_defaults(fn=cmd_lower)

    sp = sub.add_parser("graph", help="text to graph JSON (.kirgraph)")
    sp.add_argument("file")
    sp.add_argument("-o", "--output")
    with_libs(sp)
    sp.set_defaults(fn=cmd_graph)

    sp = sub.add_parser("text", help="graph JSON (.kirgraph) to text")
    sp.add_argument("file")
    sp.add_argument("-o", "--output")
    sp.add_argument("--no-meta", action="store_true", help="leave out @meta node ids and positions")
    sp.set_defaults(fn=cmd_text)

    sp = sub.add_parser("run", help="run with the reference interpreter; print final values")
    sp.add_argument("file")
    sp.add_argument("--passes", help=passes_help + "; '' runs the program as written")
    with_libs(sp)
    sp.set_defaults(fn=cmd_run)

    sp = sub.add_parser("sig", help="export a signature file")
    sp.add_argument("action", choices=["export"])
    sp.add_argument("module", help="Python module[:attr] defining node libraries")
    sp.add_argument(
        "-o", "--output", help="output file, or directory when the module has several libraries"
    )
    sp.set_defaults(fn=cmd_sig)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.fn(args)
    except KirError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
