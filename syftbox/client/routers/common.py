from fastapi import Depends, Request
from typing_extensions import Annotated

from syftbox.client.base import SyftClientInterface

__all__ = ["APIContext"]


# Create a dependency for typed access to the client
async def get_context(request: Request) -> SyftClientInterface:
    return request.app.state.client


APIContext = Annotated[SyftClientInterface, Depends(get_context)]
