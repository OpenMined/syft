import contextlib

from fastapi import FastAPI, Request
from starlette.middleware.base import BaseHTTPMiddleware

from syftbox.client.base import SyftClientInterface
from syftbox.client.routers import datasite_router, index_router


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
    app.state.client = client

    # Include routers
    app.include_router(index_router.router, tags=["index"])
    app.include_router(datasite_router.router, prefix="/datasites", tags=["datasites"])

    app.add_middleware(NoCacheMiddleware)

    return app
