import hashlib
import json
import os
import shutil
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from croniter import croniter
from loguru import logger
from typing_extensions import Any, Optional, Union

from syftbox.client.base import SyftClientInterface
from syftbox.lib.client_config import CONFIG_PATH_ENV

DEFAULT_INTERVAL = 10
RUNNING_APPS = {}
DEFAULT_APPS_PATH = Path(os.path.join(os.path.dirname(__file__), "..", "..", "..", "default_apps")).absolute().resolve()
EVENT = threading.Event()


def path_without_virtualenvs() -> str:
    env_path = os.getenv("PATH", "")
    if not env_path:
        return env_path

    venv_hints = [
        f"env{os.sep}bin",
        f"env{os.sep}Scripts",
        "conda",
        ".virtualenvs",
        "pyenv",
    ]

    # activated venv will have VIRTUAL_ENV and VIRTUAL_ENV/bin in PATH
    # so axe it
    env_venv = os.getenv("VIRTUAL_ENV", "")
    if env_venv:
        venv_hints.append(env_venv)

    cleaned_path = [
        entry for entry in env_path.split(os.pathsep) if not any(hint in entry.lower() for hint in venv_hints)
    ]

    return os.pathsep.join(cleaned_path)


def get_clean_env():
    clean_env = {}

    essential_vars = {
        "PATH",
        "HOME",
        "USER",
        "TEMP",
        "TMP",
        "TMPDIR",
        "SHELL",
        "LANG",
        "LC_ALL",
        "DISPLAY",  # X11 specific (Linux)
        "DBUS_SESSION_BUS_ADDRESS",  # X11 specific (Linux)
        "SYSTEMROOT",  # Windows specific
    }

    # Copy essential and SYFTBOX_* variables
    for key, value in os.environ.items():
        if key in essential_vars or key.startswith("SYFTBOX_"):
            clean_env[key] = value

    return clean_env


def find_and_run_script(app_path: Path, extra_args: list, config_path: Path):
    script_path = os.path.join(app_path, "run.sh")

    clean_env = get_clean_env()
    clean_env.update(
        {
            "PATH": path_without_virtualenvs(),
            CONFIG_PATH_ENV: str(config_path),
        }
    )

    # Check if the script exists
    if os.path.isfile(script_path):
        # Set execution bit (+x)
        os.chmod(script_path, os.stat(script_path).st_mode | 0o111)

        # Prepare the command based on whether there's a shebang or not
        command = ["sh", script_path] + extra_args
        return subprocess.run(
            command,
            cwd=app_path,
            check=True,
            capture_output=True,
            text=True,
            env=clean_env,
        )
    else:
        raise FileNotFoundError(f"run.sh not found in {app_path}")


def copy_default_apps(apps_path: Path):
    if not DEFAULT_APPS_PATH.exists():
        logger.info(f"Default apps directory not found: {DEFAULT_APPS_PATH}")
        return

    for app in DEFAULT_APPS_PATH.iterdir():
        src_app_path = DEFAULT_APPS_PATH / app
        dst_app_path = apps_path / app.name

        if src_app_path.is_dir():
            if dst_app_path.exists():
                logger.info(f"App already installed at: {dst_app_path}")
                # shutil.rmtree(dst_app_path)
            else:
                shutil.copytree(src_app_path, dst_app_path)
                logger.info(f"Copied default app:: {app}")


def dict_to_namespace(data) -> Union[SimpleNamespace, list, Any]:
    if isinstance(data, dict):
        return SimpleNamespace(**{key: dict_to_namespace(value) for key, value in data.items()})
    elif isinstance(data, list):
        return [dict_to_namespace(item) for item in data]
    else:
        return data


def load_config(path: str) -> Optional[SimpleNamespace]:
    try:
        with open(path, "r") as f:
            data = json.load(f)
        return dict_to_namespace(data)
    except Exception:
        return None


def bootstrap(client: SyftClientInterface):
    # create the directory
    apps_path = client.workspace.apps

    apps_path.mkdir(exist_ok=True)

    # Copy default apps if they don't exist
    copy_default_apps(apps_path)


def run_apps(apps_path: Path, client_config: Path):
    # create the directory

    for app in apps_path.iterdir():
        app_path = apps_path.absolute() / app
        if app_path.is_dir():
            app_config = load_config(app_path / "config.json")
            if app_config is None:
                run_app(app_path, client_config)
            elif RUNNING_APPS.get(app, None) is None:
                logger.info("⏱  Scheduling a  new app run.")
                thread = threading.Thread(
                    target=run_custom_app_config,
                    args=(app_config, app_path, client_config),
                )
                thread.start()
                RUNNING_APPS[os.path.basename(app)] = thread


def get_file_hash(file_path, digest="md5") -> str:
    with open(file_path, "rb") as f:
        return hashlib.file_digest(f, digest)


def output_published(app_output, published_output) -> bool:
    return (
        os.path.exists(app_output)
        and os.path.exists(published_output)
        and get_file_hash(app_output, "md5") == get_file_hash(published_output, "md5")
    )


def run_custom_app_config(app_config: SimpleNamespace, app_path: Path, client_config: Path):
    app_name = os.path.basename(app_path)
    clean_env = {
        "PATH": path_without_virtualenvs(),
        CONFIG_PATH_ENV: str(client_config),
    }
    # Update environment with any custom variables in app_config
    app_envs = getattr(app_config.app, "env", {})
    if not isinstance(app_envs, dict):
        app_envs = vars(app_envs)
    clean_env.update(app_envs)

    # Retrieve the cron-style schedule from app_config
    cron_iter = None
    interval = None
    cron_schedule = getattr(app_config.app.run, "schedule", None)
    if cron_schedule is not None:
        base_time = datetime.now()
        cron_iter = croniter(cron_schedule, base_time)
    elif getattr(app_config.app.run, "interval", None) is not None:
        interval = app_config.app.run.interval
    else:
        raise Exception("There's no schedule configuration. Please add schedule or interval in your app config.json")

    while not EVENT.is_set():
        current_time = datetime.now()
        logger.info(f"👟 Running {app_name} at scheduled time {current_time.strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"Running command: {app_config.app.run.command}")
        try:
            result = subprocess.run(
                app_config.app.run.command,
                cwd=app_path,
                check=True,
                capture_output=True,
                text=True,
                env=clean_env,
            )
            logger.info(f"App '{app_name}' ran sucessfully.\nstdout:\n{result.stdout}stderr:\n{result.stderr}")
        except subprocess.CalledProcessError as e:
            logger.error(f"Error running '{app_name}' - {e}\nstdout:\n{e.stdout}\nstderr:\n{e.stderr}")
        except Exception as e:
            logger.error(f"Error running '{app_name}' - {e}")

        if cron_iter is not None:
            # Schedule the next exection
            next_execution = cron_iter.get_next(datetime)
            time_to_wait = int((next_execution - current_time).total_seconds())
            logger.info(
                f"⏲ Waiting for scheduled time. Current time: {current_time.strftime('%Y-%m-%d %H:%M:%S')}, Next execution: {next_execution.strftime('%Y-%m-%d %H:%M:%S')}"
            )
        else:
            time_to_wait = int(interval)
        time.sleep(time_to_wait)


def run_app(app_path: Path, config_path: Path):
    app_name = os.path.basename(app_path)

    extra_args = []
    try:
        logger.info(f"Running '{app_name}' app")
        result = find_and_run_script(app_path, extra_args, config_path)
        logger.info(f"App '{app_name}' ran sucessfully.\nstdout:\n{result.stdout}stderr:\n{result.stderr}")
    except subprocess.CalledProcessError as e:
        logger.error(f"Error running '{app_name}' - {e}\nstdout:\n{e.stdout}\nstderr:\n{e.stderr}")
    except Exception as e:
        logger.error(f"Error running '{app_name}' - {e}")


class AppRunner:
    def __init__(self, client: SyftClientInterface, interval: int = DEFAULT_INTERVAL):
        self.client = client
        self.__event = threading.Event()
        self.interval = interval
        self.__run_thread: threading.Thread

    def start(self):
        def run():
            bootstrap(self.client)

            while not self.__event.is_set():
                try:
                    run_apps(
                        apps_path=self.client.workspace.apps,
                        client_config=self.client.config.path,
                    )
                except Exception as e:
                    logger.error(f"Error running apps: {e}")
                time.sleep(self.interval)

        self.__run_thread = threading.Thread(target=run)
        self.__run_thread.start()

    def stop(self, blocking: bool = False):
        if not self.__run_thread:
            return

        EVENT.set()
        self.__event.set()
        blocking and self.__run_thread.join()
