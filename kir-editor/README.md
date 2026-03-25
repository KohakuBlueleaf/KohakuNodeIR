# kir-editor

A visual editor for KIR programs. This is a **development tool**, not the core
KohakuNodeIR project -- the language and its implementations live in
`src/kohakunode/` and `src/kohakunode-rs/`.

## Architecture

- **Frontend** (`frontend/`) -- Vue 3 + Vite single-page application
- **Backend** (`backend/`) -- FastAPI server for execution and node management

The frontend handles editing and visualization entirely in the browser (parsing
and layout use the WASM build of `kohakunode-rs`). The backend is only needed
for executing KIR programs and managing custom node types.

## View modes

The editor provides three synchronized views of the same program:

1. **Node Graph** -- drag-and-drop visual node editor
2. **Blocks** -- structured block view of the AST
3. **Code** -- Monaco-based `.kir` text editor

Changes in any view are reflected in the others via the shared KirGraph store.

## Running

### Backend

```bash
cd kir-editor/backend
pip install -r requirements.txt
python main.py
# or: uvicorn main:app --host 0.0.0.0 --port 48888
```

Requires the `kohakunode` Python package to be installed.

### Frontend

```bash
cd kir-editor/frontend
npm install
npm run dev
```

The frontend dev server runs on `http://localhost:5173` by default.

### WASM (optional rebuild)

If you modify `kohakunode-rs`, rebuild the WASM module:

```bash
npm run build:wasm    # from kir-editor/frontend/
# or: bash scripts/build-wasm.sh   # from repo root
```

## Documentation

See [docs/](../docs/) for the full language specification and architecture guide.
