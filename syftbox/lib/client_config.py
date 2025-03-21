import json
import os
import shutil
from pathlib import Path
from typing import Optional, Union

from pydantic import AliasChoices, AnyHttpUrl, BaseModel, ConfigDict, EmailStr, Field, field_validator
from pydantic.main import IncEx
from pydantic_core import Url
from typing_extensions import Self

from syftbox.client.utils.net import get_free_port
from syftbox.lib.constants import (
    DEFAULT_CLIENT_TIMEOUT,
    DEFAULT_CONFIG_PATH,
    DEFAULT_DATA_DIR,
    DEFAULT_SERVER_URL,
)
from syftbox.lib.exceptions import ClientConfigException
from syftbox.lib.types import PathLike, to_path

__all__ = ["SyftClientConfig"]

# Environment variables
CONFIG_PATH_ENV = "SYFTBOX_CLIENT_CONFIG_PATH"
EMAIL_ENV = "SYFTBOX_EMAIL"
SERVER_URL_ENV = "SYFTBOX_SERVER_URL"
DATA_DIR_ENV = "SYFTBOX_DATA_DIR"
PORT_ENV = "SYFTBOX_PORT"
ACCESS_TOKEN_ENV = "SYFTBOX_ACCESS_TOKEN"
CLIENT_TIMEOUT_ENV = "SYFTBOX_CLIENT_TIMEOUT"

# Old configuration file path for the client
LEGACY_CONFIG_NAME = "client_config.json"


class SyftClientConfig(BaseModel):
    """SyftBox client configuration"""

    # model config
    model_config = ConfigDict(extra="ignore", json_encoders={AnyHttpUrl: lambda v: str(v)})

    data_dir: Path = Field(
        validation_alias=AliasChoices("data_dir", "sync_folder"),
        default=DEFAULT_DATA_DIR,
        description="Local directory where client data is stored",
    )
    """Local directory where client data is stored"""

    server_url: AnyHttpUrl = Field(
        default=DEFAULT_SERVER_URL,
        description="URL of the remote SyftBox server",
    )
    """URL of the remote SyftBox server"""

    client_url: AnyHttpUrl = Field(
        validation_alias=AliasChoices("client_url", "port"),
        description="URL where the client is running",
    )
    """URL where the client is running"""

    email: EmailStr = Field(description="Email address of the user")
    """Email address of the user"""

    token: Optional[str] = Field(
        default=None, description="Depracated: Use access_token instead. API token for the user", deprecated=True
    )
    """Depracated: Use access_token instead. API token for the user"""

    access_token: Optional[str] = Field(default=None, description="Access token for the user")
    """Access token for the user"""

    # WARN: we don't need `path` to be serialized, hence exclude=True
    path: Path = Field(exclude=True, description="Path to the config file")
    """Path to the config file"""

    client_timeout: float = Field(
        default=DEFAULT_CLIENT_TIMEOUT, description="Timeout used by the client connection to the SyftBox server"
    )
    """Timeout used by the client connection to the SyftBox server"""

    @field_validator("client_url", mode="before")
    def port_to_url(cls, val: Union[int, str]) -> Optional[str]:
        if isinstance(val, int):
            return f"http://127.0.0.1:{val}"
        return val

    @field_validator("token", mode="before")
    def token_to_str(cls, v: Union[int, str, None]) -> Optional[str]:
        if not v:
            return None
        elif isinstance(v, int):
            return str(v)
        return v

    def set_server_url(self, server: str) -> None:
        self.server_url = Url(server)

    def set_port(self, port: int) -> None:
        self.client_url = Url(f"http://127.0.0.1:{port}")

    @classmethod
    def from_env(cls, ignore_existing_config: bool = True) -> Self:
        """
        Get the client configuration from environment variables.

        Required environment variables:
        - SYFTBOX_CLIENT_CONFIG_PATH: Path to store the configuration file
        - SYFTBOX_EMAIL: User's email address
        - SYFTBOX_ACCESS_TOKEN: User's access token

        Optional environment variables:
        - SYFTBOX_DATA_DIR: Directory to store synced data
        - SYFTBOX_SERVER_URL: URL of the remote SyftBox server
        - SYFTBOX_PORT: Port for the local client (defaults to 8000)

        Raises ValueError if required configuration is missing.
        """
        try:
            config_path = Path(os.environ[CONFIG_PATH_ENV])
        except KeyError:
            raise ValueError(f"Environment variable {CONFIG_PATH_ENV} is required")
        except ValueError:
            raise ValueError(f"Invalid path provided in {CONFIG_PATH_ENV}")

        if not ignore_existing_config and config_path.exists():
            existing_config = SyftClientConfig.load(config_path)
            config_args = existing_config.model_dump(exclude={"path"})
        else:
            config_args = {}

        if DATA_DIR_ENV in os.environ:
            config_args["data_dir"] = os.environ[DATA_DIR_ENV]
        if SERVER_URL_ENV in os.environ:
            config_args["server_url"] = os.environ[SERVER_URL_ENV]
        if CLIENT_TIMEOUT_ENV in os.environ:
            config_args["client_timeout"] = float(os.environ[CLIENT_TIMEOUT_ENV])
        if EMAIL_ENV in os.environ:
            config_args["email"] = os.environ[EMAIL_ENV]
        if ACCESS_TOKEN_ENV in os.environ:
            config_args["access_token"] = os.environ[ACCESS_TOKEN_ENV]

        if PORT_ENV in os.environ:
            config_args["port"] = os.environ[PORT_ENV]
        else:
            config_args["port"] = get_free_port()

        return cls(
            path=config_path,
            **config_args,
        )

    @classmethod
    def load(cls, conf_path: Optional[PathLike] = None) -> Self:
        try:
            # args or env or default
            path = conf_path or os.getenv(CONFIG_PATH_ENV, DEFAULT_CONFIG_PATH)
            if path is None:
                raise ClientConfigException(f"Config file path not provided or set in env '{CONFIG_PATH_ENV}'")
            path = to_path(path)
            data = {}

            # todo migration stuff we can remove later
            legacy_path = Path(path.parent, LEGACY_CONFIG_NAME)
            # prefer to load config.json instead of client_config.json
            # initially config.json WILL NOT exist, so we fallback to client_config.json
            if path.exists():
                data = json.loads(path.read_text())
            elif legacy_path.exists():
                data = json.loads(legacy_path.read_text())
                path = legacy_path
            else:
                raise FileNotFoundError(f"Config file not found at '{conf_path}'")
            # todo end

            return cls(path=path, **data)
        except Exception as e:
            raise ClientConfigException(f"Failed to load config from '{conf_path}' - {e}")

    @classmethod
    def exists(cls, path: PathLike) -> bool:
        return to_path(path).exists()

    def migrate(self) -> Self:
        """Explicit call to migrate the config file"""

        # if we loaded the legacy config, we need to move it to new config
        if self.path.name == LEGACY_CONFIG_NAME:
            new_path = Path(self.path.parent, DEFAULT_CONFIG_PATH.name)
            shutil.move(str(self.path), str(new_path))
            self.path = new_path
            self.save()

        return self

    def as_dict(self, exclude: Optional[IncEx] = None) -> dict:
        return self.model_dump(exclude=exclude, exclude_none=True, warnings="none")

    def as_json(self, indent: int = 4) -> str:
        return self.model_dump_json(indent=indent, exclude_none=True, warnings="none")

    def save(self) -> Self:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(self.as_json())
        return self
