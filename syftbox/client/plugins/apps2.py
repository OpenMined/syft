import atexit
import json
import os
import shutil
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.schedulers.base import BaseScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field

from syftbox.lib.lib import Client, SharedState, SyftPermission, perm_file_path

# Plugin system constants
DEFAULT_SCHEDULE = 10000
DESCRIPTION = "Runs Apps"

# App constants
BOOTSTRAPPED = False
CONF_LOOKUP = [
    "syftapp.json",
    "syftapp.yml",
    "syftapp.yaml",
    "config.json",
    "config.yml",
    "config.yaml",
]


class RunConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    interval: int | str = 10
    command: List[str] = ["/bin/sh", "run.sh"]


class AppConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    version: str = ""
    env: Dict[str, str] = Field(default_factory=dict)
    run: RunConfig = Field(default_factory=RunConfig)

    @classmethod
    def load(cls, app_path: Path) -> Tuple["AppConfig", Path]:
        lookup_paths = [(app_path / f).resolve() for f in CONF_LOOKUP]
        conf_path = next((f for f in lookup_paths if f.exists()), None)

        if not conf_path:
            return cls(), None

        if conf_path.suffix == ".json":
            data = json.loads(conf_path.read_text())
        else:
            data = yaml.safe_load(conf_path.read_text())

        return AppConfig(**data), conf_path


class App(BaseModel):
    name: str
    path: Path
    config: AppConfig
    conf_path: Optional[Path] = None

    @property
    def entrypoint(self):
        return self.path / "run.sh"

    @property
    def has_entrypoint(self):
        return self.entrypoint.exists()

    @property
    def is_valid(self):
        return self.has_entrypoint or self.has_config

    @property
    def has_config(self) -> bool:
        return bool(self.conf_path) and self.conf_path.exists()

    @classmethod
    def detect(cls, app_path: Path | str) -> Optional["App"]:
        app_path = Path(app_path).resolve()
        if not app_path.is_dir():
            return None
        config, path = AppConfig.load(app_path)
        return cls(
            name=app_path.name,
            path=app_path,
            config=config,
            conf_path=path,
        )


class AppExecutorBase(ABC):
    """Base class for app execution."""

    @abstractmethod
    def run(self, app: App) -> subprocess.CompletedProcess:
        pass


class SubProcessExecutor(AppExecutorBase):
    """Executes configured commands."""

    def run(self, app: App) -> subprocess.CompletedProcess:
        if not app.config.run.command:
            raise ValueError("No command configured")

        return self._run_subprocess(app.config.run.command, app.path, app.config.env)

    def _run_subprocess(
        self, command: List[str], cwd: Path, env: Dict[str, str]
    ) -> subprocess.CompletedProcess:
        return subprocess.run(
            command,
            cwd=str(cwd),
            check=True,
            capture_output=True,
            text=True,
            env=dict(os.environ) | env,
        )


class AppRunner:
    def __init__(
        self,
        apps_folder: Path,
        sched: BaseScheduler,
        executor: AppExecutorBase,
    ):
        self.apps_path = Path(apps_folder)
        self.sched = sched
        self.executor = executor

    def schedule_all(self):
        if not self.apps_path.is_dir():
            logger.warning(f"Not a directory {self.apps_path}")
            return

        for app_path in self.apps_path.iterdir():
            self.schedule_app(app_path)

    def schedule_app(self, app_path: Path):
        if not app_path.is_dir():
            return

        app = App.detect(app_path)
        if not app or not app.is_valid:
            logger.warning(
                f"Skipping app: {app.name} because it has no config or entrypoint"
            )
            return

        job_id = f"job_{app.name}"
        if self.sched.get_job(job_id):
            return

        if isinstance(app.config.run.interval, int):
            trigger = IntervalTrigger(seconds=app.config.run.interval)
        elif isinstance(app.config.run.cron, str):
            trigger = CronTrigger.from_crontab(app.config.run.interval)
        else:
            raise ValueError("Invalid interval for app {app.name}")

        job = self.sched.add_job(
            id=job_id,
            func=self.executor.run,
            args=(app,),
            trigger=trigger,
        )

        logger.info(f"App {app.name} scheduled with job id {job.id}")


def find_default_apps() -> Optional[Path]:
    """Find default_apps directory by searching upwards for syftbox."""
    # Walk up until we find 'syftbox' directory or hit root
    for path in Path(__file__).resolve().parents:
        if path.name != "syftbox":
            continue
        default_apps = path.parent / "default_apps"
        return default_apps if default_apps.exists() else None
    return None


class PluginState:
    def __init__(self):
        self.__bootstrapped = False

    def init(self, client: Client):
        if self.__bootstrapped:
            return

        # make apps dir + syft perms
        user_apps_path = Path(client.sync_folder, "apps")
        user_apps_path.mkdir(parents=True, exist_ok=True)
        self.init_syftperms(user_apps_path, client.email)

        # copy default apps
        self.copy_default_apps(find_default_apps(), user_apps_path)

        # create background scheduler
        sched = BackgroundScheduler(jobstores={"default": MemoryJobStore()})
        sched.start()
        atexit.register(sched.shutdown)

        # create app schedu
        executor = SubProcessExecutor()
        self.runner = AppRunner(user_apps_path, sched, executor)

        self.__bootstrapped = True

    def init_syftperms(
        self,
        apps_path: str | Path,
        email: str,
    ) -> Optional[SyftPermission]:
        """Initialize or load permission file."""
        perms_path = perm_file_path(str(apps_path))

        if Path(perms_path).exists():
            return SyftPermission.load(perms_path)

        logger.info(f"> {email} Creating Apps Permfile")
        try:
            perm_file = SyftPermission.datasite_default(email)
            perm_file.save(perms_path)
            return perm_file
        except Exception as e:
            logger.error(f"Failed to create perm file: {e}")
            return None

    def copy_default_apps(self, source_apps: Path, dest_path: Path) -> None:
        if not source_apps.exists():
            logger.info(f"Apps directory not found: {source_apps}")
            return

        dest_path.mkdir(parents=True, exist_ok=True)
        shutil.copytree(
            source_apps,
            dest_path,
            ignore_dangling_symlinks=True,
            dirs_exist_ok=True,
        )


app_state = PluginState()


def run(shared_state: SharedState, *args, **kwargs) -> None:
    """Plugin entry point."""

    app_state.init(shared_state.client_config)
    app_state.runner.schedule_all()
