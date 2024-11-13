from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

from syftbox import __version__

router = APIRouter()


@router.get("/")
async def index():
    return PlainTextResponse(f"SyftBox {__version__}")


@router.get("/version")
async def version():
    return {"version": __version__}
