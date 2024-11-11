import json
import os
from pathlib import Path
from typing import Optional

from pydantic import AliasChoices, AnyHttpUrl, BaseModel, ConfigDict, EmailStr, Field, field_validator
from pydantic_core import Url
from typing_extensions import Self

from syftbox.lib.constants import DEFAULT_CONFIG_PATH, DEFAULT_DATA_DIR, DEFAULT_SERVER_URL
from syftbox.lib.exceptions import ClientConfigException
from syftbox.lib.types import PathLike, to_path

__all__ = ["SyftClientConfig"]

# env or default
CONFIG_PATH_ENV = "SYFTBOX_CLIENT_CONFIG_PATH"

# Old configuration file path for the client
LEGACY_CONFIG_NAME = "client_config.json"


class SyftClientConfig(BaseModel):
    """SyftBox client configuration"""

    # model config
    model_config = ConfigDict(extra="ignore")

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

    token: Optional[str] = Field(default=None, description="API token for the user")
    """API token for the user"""

    # WARN: we don't need `path` to be serialized, hence exclude=True
    path: Path = Field(exclude=True, description="Path to the config file")
    """Path to the config file"""

    @field_validator("client_url", mode="before")
    def port_to_url(cls, val):
        if isinstance(val, int):
            return f"http://127.0.0.1:{val}"
        return val

    @field_validator("token", mode="before")
    def token_to_str(cls, v):
        if not v:
            return None
        elif isinstance(v, int):
            return str(v)
        return v

    def set_server_url(self, server: str):
        self.server_url = Url(server)

    def set_port(self, port: int):
        self.client_url = Url(f"http://127.0.0.1:{port}")

    @classmethod
    def load(cls, conf_path: Optional[PathLike] = None) -> Self:
        try:
            # args or env or default
            path = conf_path or os.getenv(CONFIG_PATH_ENV, DEFAULT_CONFIG_PATH)
            path = to_path(path)

            # todo migration stuff we can remove later
            legacy_path = Path(path.parent, LEGACY_CONFIG_NAME)
            # prefer to load config.json instead of client_config.json
            # initially config.json WILL NOT exist, so we fallback to client_config.json
            if path.exists():
                data = json.loads(path.read_text())
            elif legacy_path.exists():
                data = json.loads(legacy_path.read_text())
                path = legacy_path
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
            self.path = self.path.rename(new_path)
            self.save()

        return self

    def as_dict(self, exclude=None):
        return self.model_dump(exclude=exclude, exclude_none=True, warnings="none")

    def as_json(self, indent=4):
        return self.model_dump_json(indent=indent, exclude_none=True, warnings="none")

    def save(self) -> Self:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(self.as_json())
        return self