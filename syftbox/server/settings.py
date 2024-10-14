from pathlib import Path

from fastapi import Request
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing_extensions import Self


class ServerSettings(BaseSettings):
    """
    Reads the server settings from the environment variables, using the prefix SYFTBOX_.

    example:
    `export SYFTBOX_DATA_FOLDER=data/data_folder`
    will set the server_settings.data_folder to `data/data_folder`

    see: https://docs.pydantic.dev/latest/concepts/pydantic_settings/#parsing-environment-variable-values
    """

    model_config = SettingsConfigDict(env_prefix="SYFTBOX_")

    data_folder: Path = Path("data")
    snapshot_folder: Path = Path("data/snapshot")
    user_file_path: Path = Path("data/users.json")

    @property
    def folders(self) -> list[Path]:
        return [self.data_folder, self.snapshot_folder]

    @classmethod
    def from_data_folder(cls, data_folder: Path | str) -> Self:
        data_folder = Path(data_folder)
        return cls(
            data_folder=data_folder,
            snapshot_folder=data_folder / "snapshot",
            user_file_path=data_folder / "users.json",
        )


def get_server_settings(request: Request) -> ServerSettings:
    return request.state.server_settings
