from fastapi import APIRouter
from fastapi.responses import PlainTextResponse
from syftbox.client.routers.common import APIContext
from syftbox.__version__ import __version__

router = APIRouter()


@router.get("/")
async def index():
    return PlainTextResponse(f"SyftBox {__version__}")


@router.get("/version")
async def version():
    return {"version": __version__}


@router.get("/metadata")
async def metadata(ctx: APIContext):
    return {"datasite": ctx.email}
