# kir-editor

An example node editor for KIR v2. It is a client of the toolchain, not part
of it: the Python package `kohakunode` (in `src/`) parses, checks, converts,
lowers and runs programs; machines consume KIR text. The editor shows one
program three ways (graph, text, blocks) and keeps them in step through a
thin HTTP backend over `kohakunode`.

```
apps/kir-editor/
  backend/                 FastAPI over kohakunode
    kir_editor/
      app.py               create_app(); `uvicorn kir_editor.app:app`
      config.py            settings from the environment
      api/                 routes and request bodies
      core/
        toolchain.py       every operation as one kohakunode call
        outline.py         block structure of a program (Blocks view)
        demo_nodes.py      `demo`, the runnable node library
    signatures/            .kirsig.json files listed in the palette (`vision`)
    tests/test_api.py      API smoke tests
  frontend/                Vue 3 + Vite + Pinia + UnoCSS + Vue Flow + elkjs + CodeMirror 6
    src/
      api/                 backend client
      graph/               pure graph logic: geometry, ELK layout, edits, Vue Flow mapping
      stores/              document (text + graph + layout), library, ui
      components/          chrome, graph canvas and nodes, text editor, blocks, panels
      samples/             programs shipped with the editor
```

## Run

From the repository root, with `kohakunode` installed in `.venv`:

```bash
uv pip install --python .venv/Scripts/python.exe fastapi uvicorn    # once
cd apps/kir-editor/backend
../../../.venv/Scripts/python.exe -m uvicorn kir_editor.app:app --port 48888
```

In another shell:

```bash
cd apps/kir-editor/frontend
npm install
npm run dev          # http://localhost:5173, proxies /api to 127.0.0.1:48888
```

`KIR_API_TARGET` points the dev proxy at another backend address.
`npm run build` writes a static build to `frontend/dist/`.

Backend settings:

| Variable | Default | Meaning |
|---|---|---|
| `KIR_EDITOR_SIG_DIR` | `backend/signatures` | directories of `.kirsig.json` files (os.pathsep separated); listed in the palette and searched by `@use` |
| `KIR_EDITOR_STEP_BUDGET` | `200000` | node calls one run may make |

URL parameters choose the start state: `?sample=tour|factorial|each|clamp`,
`&view=graph|split|text|blocks`, `&graph=<@def name>`, `&theme=light|dark`.

Tests:

- Backend API: `cd apps/kir-editor/backend && ../../../.venv/Scripts/python.exe -m pytest`.
- Browser smoke: `cd apps/kir-editor/frontend && npm run test:e2e`. It starts the
  backend and the dev server on their own ports (48931, 5931; `KIR_E2E_API_PORT`,
  `KIR_E2E_WEB_PORT`), drives the installed Microsoft Edge headless through
  playwright-core with a fresh profile, and on the `clamp` sample: drags a node
  in, wires a data and a control edge, edits a literal, deletes the node, undoes
  and redoes, undoes a typed text change, runs, and lowers with a pass switched
  off. Each step is checked against the DOM, the stores (the dev build exposes
  them as `window.__kir`) and the backend's own answers. `KIR_PYTHON` overrides
  the Python that runs the backend.

## API

Every POST body may carry `signatures` (parsed `.kirsig.json` files the user
loaded) and `use_demo` (default true). User errors are never HTTP errors: they
come back as `diagnostics: [{code, severity, message, line, column}]`.

| Route | Body | Returns |
|---|---|---|
| `POST /api/graph` | `text` | `graph` (.kirgraph), `outline`, `diagnostics` |
| `POST /api/text` | `graph`, `with_meta` | canonical `text`, `outline`, `diagnostics` |
| `POST /api/check` | `text` | `diagnostics` |
| `POST /api/lower` | `text`, `passes` | `lowered` text, `semantic_hash`, `full_hash`, `diagnostics` |
| `POST /api/run` | `text`, `passes` | `ok`, final `values`, `stdout`, `diagnostics` |
| `GET /api/passes` | | the optimization passes in order, with what each needs |
| `GET /api/signatures` | | `kir.std`, `demo`, then the signature directory |

`passes` is a list of pass names in order; omitted or null runs all of them,
`[]` runs the program as written.

## How it works

**Two copies, one direction at a time.** The document store holds the text
and the graph document. Typing in the text view re-derives the graph
(`/api/graph`) and lays it out again. Editing the graph (adding a node from
the palette, wiring ports, deleting, changing a property in the inspector)
re-derives the text (`/api/text`) and leaves the graph and its layout as the
user arranged them. Node ids and positions survive a text edit only when the
text carries them: the `@meta` toggle writes `@meta node_id=… pos=(…)` on
every statement, and positions from `@meta pos` are used when present.

**Undo / redo.** Ctrl+Z, Ctrl+Shift+Z / Ctrl+Y and the header buttons. Every
graph edit (add, delete, wire, unwire, inspector change) and every text
change applied to the graph first records a snapshot of the graph document,
node positions and the matching text, in a stack of 100; undo and redo swap
whole snapshots. Inside the text editor and input fields the keys keep their
own undo. Opening a file or sample starts a new history.

**Graph view.** Control ports sit on the top and bottom edges, data ports on
the left and right sides; control wires are iolite, data wires take the
colour of their type (legend in the corner). Every kind has its own shape:
call = rectangle (double border for a call to a `@def`), value = amber pill,
`get` = dashed pill, `set` = dashed rectangle, branch = diamond with `T`/`F`
ports labelled by their namespaces, switch = hexagon with one port per case,
merge = funnel (shows its label when it is a loop entry, plus a free slot for
one more incoming path), each = heavy-bordered node with `body`/`done` below
and `next` on the right, parallel = bar, try = red-edged node, `@dataflow` =
frame around its members, `inputs`/`outputs` = green nodes of a `@def` graph.
`graph/geometry.js` computes every size and port position; ELK (layered,
downwards) lays nodes out with exactly those ports, so its orthogonal routes
end at the handles. Back edges (jumps back into a loop merge, returns into an
`each` node's `next`) are given to ELK reversed, so layering follows control
flow, and drawn dashed around the loop. An edge draws its ELK route until one
of its ends is moved, then a curve. ELK runs in a web worker and falls back
to the main thread when the worker does not answer.

**Palette.** Builtins, the program's `@def`s, and every library from
`/api/signatures` plus loaded `.kirsig.json` files. Drag a node onto the
canvas or click it to drop it in the middle. A node from a library the
program does not reach yet adds its `@use`. `demo` is given to every program
unaliased while "in scope without @use" is on; turn it off when a loaded
library shares node names with it (they would be ambiguous, E011).

**Free nodes.** A call or value node with no control edge belongs to the
dataflow part of the canvas: graph → text puts all such nodes in one
`@dataflow:` block at the top (graph.md). Wire a node into the control chain
when it reads something the chain writes.

**Run.** `demo` (backend `core/demo_nodes.py`) has implementations; other
libraries are signatures only, so a program using them checks, converts and
lowers but fails at run time with "no implementation".
