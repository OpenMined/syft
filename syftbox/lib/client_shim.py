"""
SyftBox Client Shim for apps and external dependencies


NOTE: this will likely get refactored as it's own SDK.
But we need it to maintain compatibility with apps
"""

from pathlib import Path

from typing_extensions import Optional, Self

from syftbox.lib.client_config import SyftClientConfig
from syftbox.lib.types import PathLike, to_path
from syftbox.lib.workspace import SyftWorkspace

# this just makes it a bit clear what the default is for the appdata() method
MY_DATASITE = None


class Client:
    """
    Client shim for SyftBox Apps

    Minimal set of properties and methods exposed to the apps.
    """

    def __init__(self, conf: SyftClientConfig):
        self.config = conf
        self.workspace = SyftWorkspace(self.config.data_dir)

    @property
    def email(self):
        """Email of the current user"""
        return self.config.email

    @property
    def config_path(self) -> Path:
        """Path to the config of the current user"""
        return self.config.path

    @property
    def my_datasite(self) -> Path:
        """Path to the datasite of the current user"""
        return self.workspace.datasites / self.config.email

    @property
    def datasites(self) -> Path:
        """Path to the datasites folder"""
        return self.workspace.datasites

    @property
    def sync_folder(self) -> Path:
        """Deprecated property use `client.datasites` instead"""
        return self.workspace.datasites

    @property
    def datasite_path(self) -> Path:
        """Deprecated property. Use `client.my_datasite` instead"""
        return self.workspace.datasites / self.config.email

    @classmethod
    def load(cls, filepath: Optional[PathLike] = None) -> Self:
        """
        Load the client configuration from the given file path or env var or default location
        Raises: ClientConfigException
        """
        return cls(conf=SyftClientConfig.load(filepath))

    def appdata(self, app_name: str, datasite: Optional[str] = MY_DATASITE) -> Path:
        datasite = datasite or self.config.email
        return self.workspace.datasites / datasite / "app_pipelines" / app_name

    def makedirs(self, *paths: PathLike) -> None:
        """Create directories"""

        for path in paths:
            to_path(path).mkdir(parents=True, exist_ok=True)
