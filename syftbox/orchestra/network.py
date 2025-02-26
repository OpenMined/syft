import tempfile
from pathlib import Path
from typing import Optional

from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import BaseTransport

from syftbox.client.core import SyftBoxRunner
from syftbox.lib.client_config import SyftClientConfig
from syftbox.server.server import create_server
from syftbox.server.settings import ServerSettings


class Network:
    def __init__(self, base_dir: Optional[Path] = None):
        self.base_dir = base_dir or Path(tempfile.mkdtemp(prefix="syftbox-"))
        self.server = self._init_server()
        self._server_client: Optional[TestClient] = None

        self.syftboxes: dict[str, SyftBoxRunner] = {}

    def _init_server(self) -> FastAPI:
        settings = ServerSettings(
            data_folder=self.base_dir / "server",
        )
        return create_server(settings)

    @property
    def server_dir(self) -> Path:
        return self.base_dir / "server"

    @property
    def clients_dir(self) -> Path:
        return self.base_dir / "clients"

    @property
    def server_client(self) -> TestClient:
        if self._server_client is None:
            raise ValueError("Server client not initialized, please call network.start() first")
        return self._server_client

    @property
    def _server_transport(self) -> BaseTransport:
        return self.server_client._transport

    def start(self) -> None:
        if self._server_client is not None:
            raise ValueError("Server client already initialized")
        self._server_client = TestClient(self.server)
        self._server_client.__enter__()

    def launch_syftbox(self, name: str) -> SyftBoxRunner:
        if name in self.syftboxes:
            raise ValueError(f"SyftBox with name {name} already exists on this network")

        if self._server_client is None:
            raise ValueError("Server client not initialized, please call network.start() first")

        config = SyftClientConfig(
            data_dir=self.clients_dir / name,
            server_url="http://testserver",
            email=name,
            client_url="http://localhost:8080",
        )
        syftbox = SyftBoxRunner(
            config=config,
            server_transport=self._server_transport,
        )

        syftbox.start()
        self.syftboxes[name] = syftbox
        return syftbox

    def stop(self) -> None:
        for sb in self.syftboxes.values():
            sb.client.conn.__exit__()
        self.server_client.__exit__()
