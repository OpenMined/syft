from datetime import timedelta
from pathlib import Path
from typing import Optional

from fastapi import Request
from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing_extensions import Self, Union


class ServerSettings(BaseSettings):
    """
    Reads the server settings from the environment variables, using the prefix SYFTBOX_.

    example:
    `export SYFTBOX_DATA_FOLDER=data/data_folder`
    will set the server_settings.data_folder to `data/data_folder`

    see: https://docs.pydantic.dev/latest/concepts/pydantic_settings/#parsing-environment-variable-values
    """

    model_config = SettingsConfigDict(env_prefix="SYFTBOX_", env_file="server.env")
    sendgrid_secret: Optional[SecretStr] = None

    data_folder: Path = Field(default=Path("data").resolve())
    """Absolute path to the server data folder"""

    email_service_api_key: str = Field(default="")
    """API key for the email service"""

    jwt_secret: SecretStr = ""
    jwt_email_token_exp: timedelta = timedelta(hours=1)
    jwt_access_token_exp: Optional[timedelta] = None
    jwt_algorithm: str = "HS256"
    auth_enabled: bool = False

    @field_validator("data_folder", mode="after")
    def data_folder_abs(cls, v) -> Path:
        return Path(v).expanduser().resolve()

    @model_validator(mode="after")
    def auth_secret_not_empty(self):
        if self.auth_enabled and not self.jwt_secret:
            raise ValueError("auth is enabled, but no jwt_secret is defined")

        # NOTE to ensure we're never accidentally disabling auth
        if not self.auth_enabled and self.jwt_secret:
            raise ValueError("jwt_secret is defined, but no_auth is enabled")

        return self

    @model_validator(mode="after")
    def sendgrid_secret_not_empty(self):
        if self.auth_enabled and self.sendgrid_secret is None:
            raise ValueError("auth is enabled, but no sendgrid_secret is defined")

        return self

    @property
    def folders(self) -> list[Path]:
        return [self.data_folder, self.snapshot_folder]

    @property
    def snapshot_folder(self) -> Path:
        return self.data_folder / "snapshot"

    @property
    def logs_folder(self) -> Path:
        return self.data_folder / "logs"

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
