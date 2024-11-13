from pathlib import Path

from fastapi import Request
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing_extensions import Self, Union


class SMTSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SMTP_")

    use_tls: bool = False
    port: int = 587
    host: str = "localhost"
    username: str = "syftbox"
    password: str = "syftbox"
    email_sender: str = "noreply@openmined.org"


class ServerSettings(BaseSettings):
    """
    Reads the server settings from the environment variables, using the prefix SYFTBOX_.

    example:
    `export SYFTBOX_DATA_FOLDER=data/data_folder`
    will set the server_settings.data_folder to `data/data_folder`

    see: https://docs.pydantic.dev/latest/concepts/pydantic_settings/#parsing-environment-variable-values
    """

    model_config = SettingsConfigDict(env_prefix="SYFTBOX_")

    no_auth: bool = False
    keycloak_url: str = "http://20.56.213.46:8080"
    """Required when no_auth is False"""
    keycloak_admin_token: str | None = None
    """Required when no_auth is False"""

    data_folder: Path = Path("data")
    smtp: SMTSettings = SMTSettings()
    data_folder: Path = Field(default=Path("data").resolve())
    """Absolute path to the server data folder"""

    @field_validator("data_folder", mode="after")
    def data_folder_abs(cls, v):
        return Path(v).expanduser().resolve()

    @property
    def folders(self) -> list[Path]:
        return [self.data_folder, self.snapshot_folder]

    @property
    def snapshot_folder(self) -> Path:
        return self.data_folder / "snapshot"

    @property
    def user_file_path(self) -> Path:
        return self.data_folder / "users.json"

    @classmethod
    def from_data_folder(cls, data_folder: Union[Path, str]) -> Self:
        data_folder = Path(data_folder)
        return cls(
            data_folder=data_folder,
        )

    @property
    def file_db_path(self) -> Path:
        return self.data_folder / "file.db"

    def read(self, path: Path) -> bytes:
        with open(self.snapshot_folder / path, "rb") as f:
            return f.read()


def get_server_settings(request: Request) -> ServerSettings:
    return request.state.server_settings
