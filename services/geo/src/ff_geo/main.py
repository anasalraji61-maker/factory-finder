from fastapi import FastAPI

from . import __version__
from .api.errors import install_error_handlers
from .api.routes import router
from .domain.data import get_dataset
from .obs import install_observability, ready_response


def create_app() -> FastAPI:
    get_dataset()  # validate bundled data at startup; raises on corruption
    app = FastAPI(title="Factory Finder - geo", version=__version__)
    install_error_handlers(app)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "geo", "version": __version__}

    @app.get("/ready")
    def ready():
        try:
            get_dataset()
            ok = True
        except Exception:
            ok = False
        return ready_response("geo", {"dataset": ok})

    app.include_router(router)
    install_observability(app, "geo")
    return app


app = create_app()
