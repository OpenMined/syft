from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from syftbox.lib.constants import DEFAULT_CONFIG_PATH

__all__ = ["syftbox_env"]


class SyftEnvVars(BaseSettings):
    """SyftBox environment variables."""

    DISABLE_ICONS: bool = Field(default=False)
    """Disable copying icons to the datasite dir."""

    CLIENT_CONFIG_PATH: Path = Field(default=DEFAULT_CONFIG_PATH)
    """Path to the client configuration file."""

    ACCESS_TOKEN: str = Field(default="")
    """Access token for the datasite."""

    KEYCLOAK_ADMIN_TOKEN: str = Field(default="")

    model_config = SettingsConfigDict(env_file=".env", env_prefix="SYFTBOX_")


syftbox_env = SyftEnvVars()
