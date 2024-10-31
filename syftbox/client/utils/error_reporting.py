import datetime
import sys
from platform import platform

import requests
from pydantic import BaseModel, Field
from typing_extensions import Optional

from syftbox.__version__ import __version__
from syftbox.lib.lib import ClientConfig


class ErrorReport(BaseModel):
    client_config: dict
    server_syftbox_version: Optional[str] = None
    client_syftbox_version: str = __version__
    python_version: str = sys.version
    platform: str = platform()
    timestamp: datetime.datetime = Field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc))

    @classmethod
    def from_client_config(cls, client_config: ClientConfig):
        client_config.token = None
        return cls(
            client_config=client_config.to_dict(),
            server_version=try_get_server_version(client_config.server_url),
        )


def make_error_report(client_config: ClientConfig):
    return ErrorReport.from_client_config(client_config)


def try_get_server_version(server_url):
    try:
        # do not use the server_client here, as it may not be in bad state
        return requests.get(f"{server_url}/info").json()["version"]
    except Exception:
        return None
