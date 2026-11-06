"""FastAPI app. Run: uvicorn clipstar.api.main:app"""

import logging

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from ..config import get_settings
from . import routes_admin, routes_auth, routes_integrations, routes_connect, routes_engage, routes_jobs, routes_learn, routes_misc, routes_publishing, routes_videos
from .deps import require_token

log = logging.getLogger("clipstar.api")

app = FastAPI(
    title="clip_star API",
    version="1.0.0",
    description=(
        "Everything the clip_star app does, for your own scripts and tools.\n\n"
        "Authenticate with a personal API key (Settings → Integrations): `Authorization: Bearer cs_...`. "
        "A key acts as the person who made it, with the role chosen for the key (never more than theirs). "
        "Events: poll `GET /api/events?after=<last id>` or register a webhook. See docs/API.md."
    ),
    docs_url="/api/docs",
    redoc_url=None,
    openapi_url="/api/openapi.json",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_methods=["*"],
    allow_credentials=True,  # sign-in cookie; origins are listed explicitly
    allow_headers=["*"],
)

# Every route needs a signed-in user with the right role (or the API token), except sign-in, OAuth callbacks and signed media links.
for r in (routes_videos, routes_jobs, routes_publishing, routes_misc, routes_engage, routes_learn, routes_auth, routes_admin, routes_integrations):
    app.include_router(r.router, dependencies=[Depends(require_token)])
app.include_router(routes_connect.router)
app.include_router(routes_auth.public)
app.include_router(routes_connect.public)


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    # Never leak a stack trace to the client; log it for the operator.
    log.exception("unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Something went wrong on the server. Check the API logs."})
