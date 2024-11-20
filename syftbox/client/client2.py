import asyncio
import json
import platform
import shutil
from functools import lru_cache
from pathlib import Path

import httpx
import uvicorn
from loguru import logger
from pid import PidFile, PidFileAlreadyLockedError, PidFileAlreadyRunningError

from syftbox.__version__ import __version__
from syftbox.client.api import create_api
from syftbox.client.base import SyftClientInterface
from syftbox.client.env import syftbox_env
from syftbox.client.exceptions import SyftBoxAlreadyRunning, SyftInitializationError, SyftServerError
from syftbox.client.logger import setup_logger
from syftbox.client.plugins.apps import AppRunner
from syftbox.client.plugins.sync.manager import SyncManager
from syftbox.client.utils import error_reporting, file_manager, macos
from syftbox.lib.client_config import SyftClientConfig
from syftbox.lib.datasite import create_datasite
from syftbox.lib.exceptions import SyftBoxException
from syftbox.lib.ignore import IGNORE_FILENAME
from syftbox.lib.workspace import SyftWorkspace

SCRIPT_DIR = Path(__file__).parent
ASSETS_FOLDER = SCRIPT_DIR.parent / "assets"
ICON_FOLDER = ASSETS_FOLDER / "icon"
METADATA_FILENAME = ".metadata.json"


class SyftClient:
    """The SyftBox Client

    This is the main SyftBox client that handles workspace data, server
    communication, and local API services. Only one client instance can run
    for a given workspace directory.

    Warning:
        This class should not be imported directly by sub-systems.
        Use the provided interfaces and context objects instead.

    Raises:
        SyftBoxAlreadyRunning: If another client is already running for the same workspace
        Exception: If the client fails to start due to any reason
    """

    def __init__(self, config: SyftClientConfig, log_level: str = "INFO", **kwargs):
        self.config = config
        self.log_level = log_level

        self.workspace = SyftWorkspace(self.config.data_dir)
        self.pid = PidFile(pidname="syftbox.pid", piddir=self.workspace.data_dir)
        self.server_client = httpx.Client(
            base_url=str(self.config.server_url),
            follow_redirects=True,
            headers={"email": self.config.email, "Authorization": f"Bearer {self.config.access_token}"},
        )

        # kwargs for making customization/unit testing easier
        # this will be replaced with a sophisticated plugin system
        self.__sync_manager: SyncManager = kwargs.get("sync_manager", None)
        self.__app_runner: AppRunner = kwargs.get("app_runner", None)
        self.__local_server: uvicorn.Server = None

    @property
    def sync_manager(self):
        """the sync manager. lazily initialized"""
        if self.__sync_manager is None:
            try:
                self.__sync_manager = SyncManager(self.as_context())
            except Exception as e:
                raise SyftInitializationError(f"Failed to initialize sync manager - {e}") from e
        return self.__sync_manager

    @property
    def app_runner(self):
        """the app runner. lazily initialized"""
        if self.__app_runner is None:
            try:
                self.__app_runner = AppRunner(self.as_context())
            except Exception as e:
                raise SyftInitializationError(f"Failed to initialize app runner - {e}") from e
        return self.__app_runner

    @property
    def is_registered(self) -> bool:
        """Check if the current user is registered with the server"""
        return bool(self.config.token)

    @property
    def datasite(self) -> Path:
        """The datasite of the current user"""
        return self.workspace.datasites / self.config.email

    @property
    def public_dir(self) -> Path:
        """The public directory in the datasite of the current user"""
        return self.datasite / "public"

    def start(self):
        try:
            self.pid.create()
        except PidFileAlreadyLockedError:
            raise SyftBoxAlreadyRunning(f"Another instance of SyftBox is running on {self.config.data_dir}")
        self.create_metadata_file()

        logger.info("Started SyftBox client")

        self.config.save()  # commit config changes (like migration) to disk after PID is created
        self.workspace.mkdirs()  # create the workspace directories
        self.register_self()  # register the email with the server
        self.init_datasite()  # init the datasite on local machine

        # start plugins/components
        self.sync_manager.start()
        self.app_runner.start()
        return self.__run_local_server()

    @property
    def metadata_path(self) -> Path:
        return self.workspace.data_dir / METADATA_FILENAME

    def create_metadata_file(self) -> None:
        metadata_json = self.config.model_dump(mode="json")
        metadata_json["version"] = __version__
        self.metadata_path.write_text(json.dumps(metadata_json, indent=2))

    def shutdown(self):
        if self.__local_server:
            _result = asyncio.run(self.__local_server.shutdown())

        if self.__sync_manager:
            self.__sync_manager.stop()

        if self.__app_runner:
            self.__app_runner.stop()

        self.pid.close()
        logger.info("SyftBox client shutdown complete")

    def check_pidfile(self) -> str:
        """Check if another instance of SyftBox is running"""

        try:
            return self.pid.check()
        except PidFileAlreadyRunningError:
            raise SyftBoxAlreadyRunning(f"Another instance of SyftBox is running on {self.config.data_dir}")

    def init_datasite(self):
        if self.datasite.exists():
            return
        create_datasite(self.workspace.datasites, self.config.email)

    def register_self(self):
        """Register the user's email with the SyftBox cache server"""
        if self.is_registered:
            return
        try:
            token = self.__register_email()
            # TODO + FIXME - once we have JWT, we should not store token in config!
            # ideally in OS keychain (using keyring) or
            # in a separate location under self.workspace.plugins
            self.config.token = str(token)
            self.config.save()
            logger.info("Email registration successful")
        except Exception as e:
            raise SyftBoxException(f"Failed to register with the server - {e}") from e

    @lru_cache(1)
    def as_context(self) -> "SyftClientContext":
        """Return a implementation of SyftClientInterface to be injected into sub-systems"""
        return SyftClientContext(self.config, self.workspace, self.server_client)

    def __run_local_server(self):
        logger.info(f"Starting local server on {self.config.client_url}")
        app = create_api(self.as_context())
        self.__local_server = uvicorn.Server(
            config=uvicorn.Config(
                app=app,
                host=self.config.client_url.host,
                port=self.config.client_url.port,
                log_level=self.log_level.lower(),
            )
        )
        return self.__local_server.run()

    def __register_email(self) -> str:
        # TODO - this should probably be wrapped in a SyftCacheServer API?
        response = self.server_client.post("/register", json={"email": self.config.email})
        response.raise_for_status()
        return response.json().get("token")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.shutdown()

    # utils
    def open_datasites_dir(self):
        file_manager.open_dir(self.workspace.datasites)

    def copy_icons(self):
        self.workspace.mkdirs()
        if platform.system() == "Darwin":
            macos.copy_icon_file(ICON_FOLDER, self.workspace.data_dir)


class SyftClientContext(SyftClientInterface):
    """
    Concrete implementation of SyftClientInterface that provides a lightweight
    client context for components.

    This class encapsulates the minimal set of attributes needed by components
    without exposing the full SyftClient implementation.

    It will be instantiated by SyftClient, but sub-systems can freely pass it around.
    """

    def __init__(
        self,
        config: SyftClientConfig,
        workspace: SyftWorkspace,
        server_client: httpx.Client,
    ):
        self.config = config
        self.workspace = workspace
        self.server_client = server_client

    @property
    def email(self) -> str:
        return self.config.email

    @property
    def datasite(self) -> Path:
        return self.workspace.datasites / self.config.email

    @property
    def all_datasites(self) -> list[str]:
        """List all datasites in the workspace"""
        return [d.name for d in self.workspace.datasites.iterdir() if (d.is_dir() and "@" in d.name)]

    def __repr__(self) -> str:
        return f"SyftClientContext<{self.config.email}, {self.config.data_dir}>"

    def log_analytics_event(self, event_name: str, **kwargs) -> None:
        """Log an event to the server"""
        event_data = {
            "event_name": event_name,
            **kwargs,
        }

        response = self.server_client.post("/log_event", headers={"email": self.email}, json=event_data)
        if response.status_code != 200:
            raise SyftServerError(f"Failed to log event: {response.text}")


def run_apps_to_api_migration(new_ws: SyftWorkspace):
    old_sync_folder = new_ws.data_dir
    old_apps_dir = old_sync_folder / "apps"
    new_apps_dir = new_ws.apps

    if old_apps_dir.exists():
        logger.info(f"Migrating directory apps —> {new_apps_dir.relative_to(new_ws.data_dir)}...")
        if new_apps_dir.exists():
            shutil.rmtree(new_apps_dir)
        shutil.move(str(old_apps_dir), str(new_apps_dir))


def run_migration(config: SyftClientConfig, migrate_datasite=True):
    # first run config migration
    config.migrate()

    # then run workspace migration
    new_ws = SyftWorkspace(config.data_dir)

    # migrate workspace/apps to workspace/apis
    run_apps_to_api_migration(new_ws)

    # check for old dir structure and migrate to new
    # data_dir == sync_folder
    old_sync_folder = new_ws.data_dir
    old_datasite_path = Path(old_sync_folder, config.email)

    if not migrate_datasite:
        return

    # Option 2: if syftbox folder has old structure, migrate to new
    if old_datasite_path.exists():
        logger.info("Migrating to new datasite structure")
        new_ws.mkdirs()

        # create the datasites directory & move all under it
        for dir in old_sync_folder.glob("*@*"):
            shutil.move(str(dir), str(new_ws.datasites))

        # move syftignore file
        old_ignore_file = old_sync_folder / IGNORE_FILENAME
        if old_ignore_file.exists():
            shutil.move(str(old_ignore_file), str(new_ws.datasites / IGNORE_FILENAME))

        # move old sync state file
        old_sync_state = old_sync_folder / ".syft" / "local_syncstate.json"
        if old_sync_state.exists():
            shutil.move(str(old_sync_state), str(new_ws.plugins / "local_syncstate.json"))
        if old_sync_state.parent.exists():
            shutil.rmtree(str(old_sync_state.parent))


def run_client(
    client_config: SyftClientConfig, open_dir: bool = False, log_level: str = "INFO", migrate_datasite=True
) -> int:
    """Run the SyftBox client"""
    client = None

    setup_logger(log_level, log_dir=client_config.data_dir / "logs")

    error_config = error_reporting.make_error_report(client_config)
    logger.info(f"Client metadata\n{error_config.model_dump_json(indent=2)}")

    # a flag to disable icons
    # GitHub CI needs to zip sync dir in tests and fails when it encounters Icon\r files
    if syftbox_env.DISABLE_ICONS:
        logger.debug("Directory icons are disabled")

    try:
        client = SyftClient(client_config, log_level=log_level)
        # we don't want to run migration if another instance of client is already running
        bool(client.check_pidfile()) and run_migration(client_config, migrate_datasite=migrate_datasite)
        (not syftbox_env.DISABLE_ICONS) and client.copy_icons()
        open_dir and client.open_datasites_dir()
        client.start()
    except SyftBoxAlreadyRunning as e:
        logger.error(e)
        return -1
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt. Shutting down the client")
    except Exception as e:
        logger.exception("Unhandled exception when starting the client", e)
        return -2
    finally:
        client and client.shutdown()
    return 0
