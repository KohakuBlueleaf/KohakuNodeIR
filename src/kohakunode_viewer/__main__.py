"""KIR Viewer CLI — convert .kir or ComfyUI JSON to .kirgraph for viewing.

Usage:
    python -m kohakunode_viewer input.kir                    # outputs input.kirgraph
    python -m kohakunode_viewer input.kir -o output.kirgraph # specify output
    python -m kohakunode_viewer workflow.json                # ComfyUI -> kirgraph
    python -m kohakunode_viewer input.kir --serve            # start viewer server
    python -m kohakunode_viewer input.kir --html output.html # generate self-contained HTML
"""

from __future__ import annotations

import argparse
import http.server
import json
import os
import pathlib
import sys
import threading
import urllib.parse
import webbrowser

from kohakunode.kirgraph.decompiler import KirGraphDecompiler
from kohakunode.kirgraph.schema import KirGraph
from kohakunode.parser.parser import parse_file
from kohakunode_utils.comfyui import comfyui_to_kirgraph
from kohakunode_viewer.html_export import generate_html


# ---------------------------------------------------------------------------
# Format detection
# ---------------------------------------------------------------------------


def _load_kirgraph_from_kir(path: pathlib.Path) -> KirGraph:
    """Parse a .kir file and decompile it to a KirGraph."""
    program = parse_file(path)
    decompiler = KirGraphDecompiler()
    return decompiler.decompile(program)


def _load_kirgraph_from_json(path: pathlib.Path) -> KirGraph:
    """Load a .json file, trying ComfyUI format first, then raw kirgraph."""
    raw = path.read_text(encoding="utf-8")
    data = json.loads(raw)

    # Detect ComfyUI: has "nodes" list with ComfyUI-style dicts, or API format
    # with class_type keys.  Try ComfyUI first, fall back to kirgraph.
    is_comfy = False
    if isinstance(data, dict):
        # API format: values have "class_type"
        for v in data.values():
            if isinstance(v, dict) and "class_type" in v:
                is_comfy = True
                break
        # Workflow format: has "nodes" list and "links" list
        if not is_comfy and "nodes" in data and "links" in data:
            nodes = data["nodes"]
            if isinstance(nodes, list) and nodes and isinstance(nodes[0], dict):
                is_comfy = True

    if is_comfy:
        return comfyui_to_kirgraph(data)

    # Fall back: treat as a raw .kirgraph JSON
    return KirGraph.from_dict(data)


def _load_kirgraph_from_kirgraph(path: pathlib.Path) -> KirGraph:
    """Load a .kirgraph file directly."""
    raw = path.read_text(encoding="utf-8")
    return KirGraph.from_json(raw)


def _resolve_input(path: pathlib.Path) -> KirGraph:
    """Detect input format and return a KirGraph."""
    suffix = path.suffix.lower()

    if suffix == ".kir":
        return _load_kirgraph_from_kir(path)
    if suffix == ".kirgraph":
        return _load_kirgraph_from_kirgraph(path)
    if suffix == ".json":
        return _load_kirgraph_from_json(path)

    # Unknown extension — try to sniff content
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
        # If it parses as JSON, delegate to the JSON handler
        return _load_kirgraph_from_json(path)
    except (json.JSONDecodeError, UnicodeDecodeError):
        pass

    # Last resort: try KIR parser
    return _load_kirgraph_from_kir(path)


# ---------------------------------------------------------------------------
# Default output path
# ---------------------------------------------------------------------------


def _default_output(input_path: pathlib.Path) -> pathlib.Path:
    """Return the default .kirgraph output path for a given input."""
    return input_path.with_suffix(".kirgraph")


# ---------------------------------------------------------------------------
# --serve: simple HTTP server
# ---------------------------------------------------------------------------

# Viewer dist directory (built Vue app lives next to this package)
_VIEWER_DIST = pathlib.Path(__file__).parent / "dist"
# Fallback: the package directory itself (for dev, serves index.html if present)
_VIEWER_ROOT = pathlib.Path(__file__).parent


class _KirGraphRequestHandler(http.server.SimpleHTTPRequestHandler):
    """HTTP handler that serves the viewer dist + a virtual /graph.kirgraph."""

    kirgraph_json: str = ""  # populated before the server starts
    serve_root: pathlib.Path = _VIEWER_DIST

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path in ("/graph.kirgraph", "/graph.kirgraph/"):
            data = self.kirgraph_json.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(data)
            return
        super().do_GET()

    def translate_path(self, path: str) -> str:
        # Serve files from the viewer root (dist or package dir).
        parsed = urllib.parse.urlparse(path)
        rel = parsed.path.lstrip("/")
        full = self.serve_root / rel
        if full.is_dir():
            full = full / "index.html"
        return str(full)

    def log_message(self, fmt: str, *args: object) -> None:  # type: ignore[override]
        # Suppress access log noise; only errors go to stderr.
        pass

    def log_error(self, fmt: str, *args: object) -> None:  # type: ignore[override]
        print(f"[server error] {fmt % args}", file=sys.stderr)


def _serve(kirgraph_json: str, port: int = 5175) -> None:
    """Start an HTTP server and open the viewer in the default browser."""
    # Determine the directory to serve from.
    serve_root = _VIEWER_DIST if _VIEWER_DIST.is_dir() else _VIEWER_ROOT

    handler = type(
        "_Handler",
        (_KirGraphRequestHandler,),
        {
            "kirgraph_json": kirgraph_json,
            "serve_root": serve_root,
        },
    )

    with http.server.HTTPServer(("127.0.0.1", port), handler) as httpd:
        url = f"http://127.0.0.1:{port}"
        print(f"Serving KirGraph viewer at {url}")
        print("  Graph endpoint: " + url + "/graph.kirgraph")
        print("Press Ctrl-C to stop.")

        # Open browser in a background thread so the server can start first.
        def _open():
            webbrowser.open(url)

        threading.Thread(target=_open, daemon=True).start()

        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nServer stopped.")


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m kohakunode_viewer",
        description=(
            "Convert .kir or ComfyUI JSON to .kirgraph, "
            "or launch the graph viewer."
        ),
    )
    p.add_argument(
        "input",
        metavar="INPUT",
        help="Input file (.kir, .kirgraph, or .json ComfyUI workflow)",
    )
    p.add_argument(
        "-o",
        "--output",
        metavar="OUTPUT",
        default=None,
        help=(
            "Output .kirgraph file path. "
            "Defaults to INPUT with .kirgraph extension."
        ),
    )
    p.add_argument(
        "--serve",
        action="store_true",
        help="Start a local HTTP server and open the viewer in the browser.",
    )
    p.add_argument(
        "--port",
        type=int,
        default=5175,
        metavar="PORT",
        help="Port for --serve (default: 5175).",
    )
    p.add_argument(
        "--html",
        metavar="HTML_OUTPUT",
        default=None,
        help="Generate a self-contained HTML viewer file at the given path.",
    )
    return p


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    input_path = pathlib.Path(args.input).resolve()
    if not input_path.exists():
        print(f"error: input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    # Load and convert to KirGraph
    try:
        graph = _resolve_input(input_path)
    except Exception as exc:
        print(f"error: failed to load {input_path.name}: {exc}", file=sys.stderr)
        sys.exit(1)

    kirgraph_json = graph.to_json()

    # --html: generate self-contained HTML viewer
    if args.html is not None:
        html_path = pathlib.Path(args.html).resolve()
        try:
            html = generate_html(kirgraph_json)
            html_path.write_text(html, encoding="utf-8")
            print(f"HTML viewer written to: {html_path}")
        except Exception as exc:
            print(f"error: failed to write HTML: {exc}", file=sys.stderr)
            sys.exit(1)
        # If --serve is also set, fall through; otherwise done.
        if not args.serve:
            return

    # Determine output .kirgraph path
    if args.output is not None:
        output_path = pathlib.Path(args.output).resolve()
    else:
        output_path = _default_output(input_path)

    # Write the .kirgraph file (always, unless --serve was the only flag and
    # the user didn't ask for -o; still write it as a side-effect so the
    # server can reference a real file).
    try:
        output_path.write_text(kirgraph_json, encoding="utf-8")
        print(f"KirGraph written to: {output_path}")
    except Exception as exc:
        print(f"error: failed to write output: {exc}", file=sys.stderr)
        sys.exit(1)

    # --serve: launch viewer
    if args.serve:
        _serve(kirgraph_json, port=args.port)


if __name__ == "__main__":
    main()
