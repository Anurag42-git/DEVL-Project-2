"""Serve the built React single-page app from the API process.

Calling :func:`mount_frontend` at the end of ``api.main`` registers the static
routes *after* every JSON endpoint, so API paths keep their normal behaviour.
If the frontend has not been built, the root endpoint returns a short JSON hint
instead of failing the whole service.
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from src.config import resolve_path


def mount_frontend(app: FastAPI, config: dict) -> bool:
    """Mount the SPA from ``deployment.static_dir`` when it exists.

    Returns:
        True when the built UI was mounted, False when it was not built yet.
    """
    static_dir = resolve_path(config, "deployment.static_dir")
    index = static_dir / "index.html"
    if not index.is_file():
        @app.get("/", include_in_schema=False)
        def not_built() -> JSONResponse:
            return JSONResponse(
                {
                    "service": "transaction-investigation-api",
                    "message": "Frontend not built. Run `npm --prefix frontend run build`.",
                }
            )

        return False

    assets = static_dir / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str) -> FileResponse:
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found")
        root = static_dir.resolve()
        candidate = (static_dir / full_path).resolve()
        if not str(candidate).startswith(str(root)):
            raise HTTPException(status_code=404, detail="Not found")
        if candidate.is_file():
            return FileResponse(candidate)
        # Client-side route (e.g. /review) -> let React Router handle it.
        return FileResponse(index)

    return True
