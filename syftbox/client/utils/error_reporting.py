import datetime
import sys
from platform import platform

import httpx
from pydantic import BaseModel, Field
from typing_extensions import Optional

from syftbox.__version__ import __version__
from syftbox.client.env import syftbox_env
from syftbox.lib.client_config import SyftClientConfig


class ErrorReport(BaseModel):
    client_config: SyftClientConfig
    server_syftbox_version: Optional[str] = None
    client_syftbox_version: str = __version__
    python_version: str = sys.version
    platform: str = platform()
    timestamp: datetime.datetime = Field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc))
    env: dict = Field(default=syftbox_env.model_dump())

    @classmethod
    def from_client_config(cls, client_config: SyftClientConfig):
        return cls(
            client_config=client_config,
            server_version=try_get_server_version(client_config.server_url),
        )


def make_error_report(client_config: SyftClientConfig):
    return ErrorReport.from_client_config(client_config)


def try_get_server_version(server_url):
    try:
        # do not use the server_client here, as it may not be in bad state
        return httpx.get(f"{server_url}/info").json()["version"]
    except Exception:
        return None
