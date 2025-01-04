from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

from syftbox import __version__
from syftbox.client.routers.common import APIContext

router = APIRouter()


@router.get("/")
async def index() -> PlainTextResponse:
    return PlainTextResponse(f"SyftBox {__version__}")


@router.get("/version")
async def version() -> dict:
    return {"version": __version__}


@router.get("/metadata")
async def metadata(ctx: APIContext) -> dict:
    return {"datasite": ctx.email}
