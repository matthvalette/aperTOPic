"""FastAPI application. Run with: uv run uvicorn parltopics.api.main:app --reload

The test console is served at /ui; the API stays at /search, /classify, ...
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from .dependencies import lifespan
from .routes import classify, health, parliaments, search, similar, taxonomies

WEB_DIR = Path(__file__).resolve().parents[1] / "web"


def create_app() -> FastAPI:
    app = FastAPI(
        title="Parliament topics",
        version="0.1.0",
        description=(
            "Multilingual search and topic classification for Swiss parliamentary affairs. "
            "Search: Apertus translates, OpenParlData finds. Classify: Jev returns a probability per topic."
        ),
        lifespan=lifespan,
    )
    for module in (health, search, classify, similar, taxonomies, parliaments):
        app.include_router(module.router)
    app.mount("/ui", StaticFiles(directory=WEB_DIR, html=True), name="ui")

    @app.get("/", include_in_schema=False)
    def home() -> RedirectResponse:
        return RedirectResponse("/ui/")

    return app


app = create_app()
