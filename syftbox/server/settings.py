from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class SMTPSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SMTP_")
    tls: bool = True
    port: int = 587
    host: str
    username: str
    password: str
    sender: str


class ServerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SYFTBOX_")
    data_folder: Path = Path("data")
    snapshot_folder: Path = Path("data/snapshot")
    user_file_path: Path = Path("data/users.json")
    smtp: "SMTPSettings" = SMTPSettings()

    @property
    def folders(self):
        return [self.data_folder, self.snapshot_folder]
