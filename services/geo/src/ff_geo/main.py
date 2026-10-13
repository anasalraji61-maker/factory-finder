from fastapi import FastAPI

from . import __version__
from .api.errors import install_error_handlers
from .api.routes import router
from .domain.data import get_dataset


def create_app() -> FastAPI:
    get_dataset()  # validate bundled data at startup; raises on corruption
    app = FastAPI(title="Factory Finder - geo", version=__version__)
    install_error_handlers(app)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "geo", "version": __version__}

    app.include_router(router)
    return app


app = create_app()
