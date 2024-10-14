# Handle configuratoin loading and management
import argparse
import logging
import os
import platform
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import httpx
from const import (
    DEFAULT_CONFIG_PATH,
    DEFAULT_PORT,
    DEFAULT_SERVER_URL,
    DEFAULT_SYNC_FOLDER,
    ICON_FOLDER,
)

from syftbox.lib import Jsonable, SyftPermission, validate_email

logger = logging.getLogger(__name__)


@dataclass
class ClientConfig(Jsonable):
    config_path: Path
    sync_folder: Path | None = None
    port: int | None = None
    email: str | None = None
    token: int | None = None
    server_url: str = "http://localhost:5001"
    email_token: str | None = None
    autorun_plugins: list[str] | None = field(
        default_factory=lambda: ["init", "create_datasite", "sync", "apps"]
    )
    _server_client: httpx.Client | None = None

    @property
    def is_registered(self) -> bool:
        return self.token is not None

    @property
    def server_client(self) -> httpx.Client:
        if self._server_client is None:
            self._server_client = httpx.Client(
                base_url=self.server_url,
                follow_redirects=True,
            )
        return self._server_client

    def close(self):
        if self._server_client:
            self._server_client.close()

    def save(self, path: str | None = None) -> None:
        if path is None:
            path = self.config_path
        super().save(path)

    @property
    def datasite_path(self) -> Path:
        return Path(self.sync_folder) / self.email

    @property
    def manifest_path(self) -> Path:
        return self.datasite_path / "public" / "manifest" / "manifest.json"

    def get_datasites(self: str) -> list[str]:
        datasites = []
        folders = Path(self.sync_folder).iterdir()
        for folder in folders:
            if "@" in folder:
                datasites.append(folder)
        return datasites

    def use(self):
        os.environ["SYFTBOX_CURRENT_CLIENT"] = self.config_path
        os.environ["SYFTBOX_SYNC_DIR"] = self.sync_folder
        logger.info(f"> Setting Sync Dir to: {self.sync_folder}")

    def create_folder(self, path: str, permission: SyftPermission):
        os.makedirs(path, exist_ok=True)
        permission.save(path)

    @property
    def root_dir(self) -> Path:
        root_dir = Path(os.path.abspath(os.path.dirname(self.file_path) + "/../"))
        return root_dir

    def create_public_folder(self, path: str):
        full_path = self.root_dir / path
        os.makedirs(str(full_path), exist_ok=True)
        public_read = SyftPermission.mine_with_public_read(email=self.datasite)
        public_read.save(full_path)
        return Path(full_path)


def get_user_input(prompt: str, default: str | None = None) -> str:
    if default:
        prompt = f"{prompt} (default: {default}): "
    user_input = input(prompt).strip()
    return user_input if user_input else default


# Parsing arguments and initializing shared state
def parse_args():
    parser = argparse.ArgumentParser(
        description="Run the web application with plugins.",
    )
    parser.add_argument(
        "--config_path", type=str, default=DEFAULT_CONFIG_PATH, help="config path"
    )
    parser.add_argument(
        "--sync_folder", type=str, default=DEFAULT_SYNC_FOLDER, help="sync folder path"
    )
    parser.add_argument("--email", type=str, help="email")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Port number")
    parser.add_argument(
        "--server",
        type=str,
        default=DEFAULT_SERVER_URL,
        help="Server",
    )
    subparsers = parser.add_subparsers(dest="command", help="Sub-command help")
    start_parser = subparsers.add_parser("report", help="Generate an error report")
    start_parser.add_argument(
        "--path",
        type=str,
        help="Path to the error report file",
        default=f"./syftbox_logs_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}",
    )

    return parser.parse_args()


def load_or_create_config(args) -> ClientConfig:
    syft_config_dir = os.path.abspath(os.path.expanduser("~/.syftbox"))
    os.makedirs(syft_config_dir, exist_ok=True)

    client_config = None
    try:
        client_config = ClientConfig.load(args.config_path)
    except Exception:
        pass

    if client_config is None and args.config_path:
        config_path = os.path.abspath(os.path.expanduser(args.config_path))
        client_config = ClientConfig(config_path=config_path)

    if client_config is None:
        # config_path = get_user_input("Path to config file?", DEFAULT_CONFIG_PATH)
        config_path = os.path.abspath(os.path.expanduser(config_path))
        client_config = ClientConfig(config_path=config_path)

    if args.sync_folder:
        sync_folder = os.path.abspath(os.path.expanduser(args.sync_folder))
        client_config.sync_folder = sync_folder

    if client_config.sync_folder is None:
        sync_folder = get_user_input(
            "Where do you want to Sync SyftBox to?",
            DEFAULT_SYNC_FOLDER,
        )
        sync_folder = os.path.abspath(os.path.expanduser(sync_folder))
        client_config.sync_folder = sync_folder

    if args.server:
        client_config.server_url = args.server

    if not os.path.exists(client_config.sync_folder):
        os.makedirs(client_config.sync_folder, exist_ok=True)

    if platform.system() == "Darwin":
        macos.copy_icon_file(ICON_FOLDER, client_config.sync_folder)

    if args.email:
        client_config.email = args.email

    if client_config.email is None:
        email = get_user_input("What is your email address? ")
        if not validate_email(email):
            raise Exception(f"Invalid email: {email}")
        client_config.email = email

    if args.port:
        client_config.port = args.port

    if client_config.port is None:
        port = int(get_user_input("Enter the port to use", DEFAULT_PORT))
        client_config.port = port

    email_token = os.environ.get("EMAIL_TOKEN", None)
    if email_token:
        client_config.email_token = email_token

    # Migrate Old Server URL to HTTPS
    if client_config.server_url == "http://20.168.10.234:8080":
        client_config.server_url = "https://syftbox.openmined.org"

    client_config.save(args.config_path)
    return client_config
