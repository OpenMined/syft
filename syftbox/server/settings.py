from pathlib import Path

from fastapi import Request
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class SMTSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SMTP_")

    use_tls: bool = False
    port: int = 587
    host: str = "localhost"
    username: str = "syftbox"
    password: str = "syftbox"
    email_sender: str = "noreply@openmined.org"


class ServerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SYFTBOX_")

    admin_username: SecretStr = "info@openmined.org"
    admin_password: SecretStr = "changethis"
    jwt_secret: SecretStr = "changethis"

    data_folder: Path = Path("data")
    snapshot_folder: Path = Path("data/snapshot")
    user_file_path: Path = Path("data/users.json")
    smtp: SMTSettings = SMTSettings()

    @property
    def folders(self) -> list[Path]:
        return [self.data_folder, self.snapshot_folder]


def get_server_settings(request: Request) -> ServerSettings:
    return request.state.server_settings
