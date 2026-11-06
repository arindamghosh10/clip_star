"""FastAPI app. Run: uvicorn clipstar.api.main:app"""

import logging

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from ..config import get_settings
from . import routes_connect, routes_engage, routes_jobs, routes_learn, routes_misc, routes_publishing, routes_videos
from .deps import require_token

log = logging.getLogger("clipstar.api")

app = FastAPI(title="clip_star API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Every route needs the API token (when one is set) except OAuth callbacks and signed media links.
for r in (routes_videos, routes_jobs, routes_publishing, routes_misc, routes_engage, routes_learn):
    app.include_router(r.router, dependencies=[Depends(require_token)])
app.include_router(routes_connect.router)
app.include_router(routes_connect.public)


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    # Never leak a stack trace to the client; log it for the operator.
    log.exception("unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Something went wrong on the server. Check the API logs."})
