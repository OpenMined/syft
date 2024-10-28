import json
import os
from pathlib import Path
from typing import Optional

from syftbox_sdk.exception import ClientException
from syftbox_sdk.permissions import EVERYONE, SyftPermission
from syftbox_sdk.types import PathLike, UserLike, to_path

DEFAULT_CONFIG_PATH = Path(Path.home(), ".syftbox", "client_config.json")


class SyftBoxContext:
    """
    A client context for working with datasites and permissions in the SyftBox file system.

    Attributes:
        __data_dir (Path): Base directory for all data storage.
        __email (str): User's email address for identification.

    Examples:
        >>> # Initialize from config file
        >>> ctx = SyftBoxContext.load()
        >>>
        >>> # Get user's datasite and set permissions
        >>> datasite = ctx.get_datasite()
        >>> ctx.set_writable(datasite)
    """

    __slots__ = ["__data_dir", "__email"]

    def __init__(self, data_dir: PathLike, email: str):
        """
        To initialize a context, use `SyftBoxContext.load()` instead.
        """
        self.__data_dir = Path(data_dir).resolve()
        self.__email = email

    def get_datasite(self, datasite: Optional[str] = None) -> Path:
        """
        Get the directory path for a specific datasite.

        If no datasite is specified, returns the user's personal datasite directory.

        Args:
            datasite (Optional[str]): Email address of the datasite owner.
                                    Defaults to None, which returns the current user's datasite.

        Returns:
            Path: Directory path for the specified datasite.

        Examples:
            >>> ctx = SyftBoxContext("/data", "user@example.com")
            >>> # Get user's personal datasite
            >>> my_site = ctx.get_datasite()  # Returns: /data/user@example.com
            >>> # Get another user's datasite
            >>> other_site = ctx.get_datasite("other@example.com")  # Returns: /data/other@example.com
        """
        datasite = datasite or self.__email
        return self.__data_dir / datasite

    def get_app_data(self, app_name: str, datasite: Optional[str] = None) -> Path:
        """
        Get the application data directory path for a specific app within a datasite.

        Args:
            app_name (str): Name of the application.
            datasite (Optional[str]): Email address of the datasite owner.
                                    Defaults to None, which uses the current user's datasite.

        Returns:
            Path: Directory path for the application data.

        Examples:
            >>> ctx = SyftBoxContext("/data", "user@example.com")
            >>> # Get app data in user's datasite
            >>> app_dir = ctx.get_app_data("my_app")
            >>> # Returns: /data/user@example.com/app_pipelines/my_app
            >>>
            >>> # Get app data in another user's datasite
            >>> other_app = ctx.get_app_data("my_app", "other@example.com")
            >>> # Returns: /data/other@example.com/app_pipelines/my_app
        """
        return Path(self.get_datasite(datasite) / "app_pipelines" / app_name)

    def set_writable(self, path: PathLike, writers: UserLike = EVERYONE) -> None:
        """
        Set write permissions for a directory by creating a public permissions file.

        Args:
            path    (PathLike): Directory path to set permissions for.
            writers (UserLike): One ore more email addresses with write permission, Defaults to '*'.

        Examples:
            >>> ctx = SyftBoxContext("/data", "user@example.com")
            >>> data_path = ctx.get_datasite() / "shared_data"
            >>> # Make writable by everyone
            >>> ctx.set_writable(data_path)
            >>> # Make writable by specific users
            >>> ctx.set_writable(data_path, ["user1@example.com", "user2@example.com"])
        """
        if SyftPermission.exists(path):
            perms = SyftPermission.load(path)
            perms.add_writer(writers).save()
        else:
            SyftPermission.writeable(path, owner=self.__email, users=writers).save()

    def set_readable(self, path: PathLike, readers=EVERYONE) -> None:
        """
        Set read-only permissions for a directory by creating a private permissions file.

        Args:
            path    (PathLike): Directory path to set permissions for.
            readers (UserLike): List of email addresses with read permission, Defaults to '*'.

        Examples:
            >>> ctx = SyftBoxContext("/data", "user@example.com")
            >>> data_path = ctx.get_datasite() / "public_data"
            >>> # Make readable by everyone
            >>> ctx.set_readable(data_path)
            >>> # Make readable by specific users
            >>> ctx.set_readable(data_path, ["user1@example.com"])
        """
        if SyftPermission.exists(path):
            perms = SyftPermission.load(path)
            perms.add_reader(readers).save()
        else:
            SyftPermission.readable(path, owner=self.__email, users=readers).save()

    def make_dirs(self, *args: PathLike) -> None:
        """
        Create multiple directories if they don't exist.

        Args:
            *args (Path): Variable number of Path objects representing directories to create.

        Examples:
            >>> ctx = SyftBoxContext("/data", "user@example.com")
            >>> input_dir = ctx.get_app_data("app_name") / "input"
            >>> output_dir = ctx.get_app_data("app_name", "other@openmined.org") / "output"
            >>> ctx.make_dirs(input_dir, output_dir)
        """
        for path in args:
            to_path(path).mkdir(parents=True, exist_ok=True)

    @staticmethod
    def load(config_path: Optional[PathLike] = None) -> "SyftBoxContext":
        """
        Create a Context from the SyftBox config file.

        The configuration file should be a JSON file containing 'sync_folder' and 'email' fields.
        The default location is `~/.syftbox/client_config.json`, but this can be overridden
        using the SYFTBOX_CLIENT_CONFIG_PATH environment variable.

        Returns:
            SyftBoxContext: context instance

        Raises:
            ClientException: If the configuration file is not found.

        Examples:
            >>> # With default config path (~/.syftbox/client_config.json)
            >>> ctx = SyftBoxContext.load()
            >>>
            >>> # With custom config
            >>> import os
            >>> ctx = SyftBoxContext.load("/custom/path/config.json")
            >>>
            >>> # With environment variable
            >>> import os
            >>> os.environ["SYFTBOX_CLIENT_CONFIG_PATH"] = "/custom/path/config.json"
            >>> ctx = SyftBoxContext.load()
        """
        config_path = config_path or Path(os.getenv("SYFTBOX_CLIENT_CONFIG_PATH", DEFAULT_CONFIG_PATH))

        if not config_path.exists():
            raise ClientException(f"Config file not found at {config_path}")

        obj = json.loads(config_path.read_text())
        return SyftBoxContext(obj["sync_folder"], obj["email"])
