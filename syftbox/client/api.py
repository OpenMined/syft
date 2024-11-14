import contextlib

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from syftbox.client.base import SyftClientInterface
from syftbox.client.routers import app_router, datasite_router, index_router


class NoCacheMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    yield


def create_api(client: SyftClientInterface) -> FastAPI:
    app = FastAPI(lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost",
            "http://localhost:5001",
            "http://localhost:8080",
            "http://localhost:8081",
            "http://localhost:8083",
            "https://syftbox.openmined.org",
        ],  # Allow localhost on any port and specific domain
        allow_credentials=True,
        allow_methods=["*"],  # Allow all HTTP methods
        allow_headers=["*"],  # Allow all headers
    )

    app.state.client = client

    # Include routers
    app.include_router(index_router.router, tags=["index"])
    app.include_router(datasite_router.router, prefix="/datasites", tags=["datasites"])
    app.include_router(app_router.router, prefix="/apps", tags=["apps"])

    app.add_middleware(NoCacheMiddleware)

    return app
