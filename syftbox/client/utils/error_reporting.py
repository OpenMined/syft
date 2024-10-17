import datetime
import sys
from platform import platform

import requests
from pydantic import BaseModel, Field

from syftbox import Client
from syftbox.__version__ import __version__


class ErrorReport(BaseModel):
    client: dict
    server_syftbox_version: str | None = None
    client_syftbox_version: str = __version__
    python_version: str = sys.version
    platform: str = platform()
    timestamp: datetime.datetime = Field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc)
    )

    @classmethod
    def from_client(cls, client: Client):
        client.token = None
        return cls(
            client=client.to_dict(),
            server_version=try_get_server_version(client.server_url),
        )


def make_error_report(client: Client):
    return ErrorReport.from_client(client)


def try_get_server_version(server_url):
    try:
        # do not use the server_client here, as it may not be in bad state
        return requests.get(f"{server_url}/info").json()["version"]
    except Exception:
        return None
