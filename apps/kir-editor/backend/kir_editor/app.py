"""The FastAPI application: ``uvicorn kir_editor.app:app``."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from kir_editor.api.routes import router
from kir_editor.config import Settings, load_settings
from kir_editor.core.toolchain import Toolchain


def create_app(settings: Settings | None = None) -> FastAPI:
    app = FastAPI(title="KIR editor backend")
    app.state.toolchain = Toolchain(settings or load_settings())
    # The Vite dev server proxies /api; CORS covers a frontend served from elsewhere.
    app.add_middleware(
        CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
    )
    app.include_router(router)
    return app


app = create_app()
