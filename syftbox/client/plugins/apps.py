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

DEFAULT_INTERVAL = 10
RUNNING_APPS = {}
DEFAULT_APPS_PATH = Path(os.path.join(os.path.dirname(__file__), "..", "..", "..", "default_apps")).absolute().resolve()
EVENT = threading.Event()


def find_and_run_script(task_path, extra_args):
    script_path = os.path.join(task_path, "run.sh")
    env = os.environ.copy()  # Copy the current environment

    # Check if the script exists
    if os.path.isfile(script_path):
        # Set execution bit (+x)
        os.chmod(script_path, os.stat(script_path).st_mode | 0o111)

        # Check if the script has a shebang
        with open(script_path, "r") as script_file:
            first_line = script_file.readline().strip()
            has_shebang = first_line.startswith("#!")

        # Prepare the command based on whether there's a shebang or not
        command = [script_path] + extra_args if has_shebang else ["/bin/bash", script_path] + extra_args

        try:
            result = subprocess.run(
                command,
                cwd=task_path,
                check=True,
                capture_output=True,
                text=True,
                env=env,
            )

            # logger.info("✅ Script run.sh executed successfully.")
            return result
        except subprocess.CalledProcessError as e:
            logger.info(f"Error running shell script: {str(e.stderr)}")
    else:
        raise FileNotFoundError(f"run.sh not found in {task_path}")


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


def run_apps(apps_path: Path):
    # create the directory

    for app in apps_path.iterdir():
        app_path = apps_path.absolute() / app
        if app_path.is_dir():
            app_config = load_config(app_path / "config.json")
            if app_config is None:
                run_app(app_path)
            elif RUNNING_APPS.get(app, None) is None:
                logger.info("⏱  Scheduling a  new app run.")
                thread = threading.Thread(
                    target=run_custom_app_config,
                    args=(app_config, app_path),
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


def run_custom_app_config(app_config: SimpleNamespace, path: Path):
    env = os.environ.copy()
    app_name = os.path.basename(path)

    # Update environment with any custom variables in app_config
    app_envs = getattr(app_config.app, "env", {})
    if not isinstance(app_envs, dict):
        app_envs = vars(app_envs)
    env.update(app_envs)

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
                cwd=path,
                check=True,
                capture_output=True,
                text=True,
                env=env,
            )
            logger.info(result.stdout)
            logger.error(result.stderr)
        except subprocess.CalledProcessError as e:
            logger.error(f"Error running {app_name}: {e.stderr}")

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


def run_app(path: Path):
    app_name = os.path.basename(path)

    extra_args = []
    try:
        logger.info(f"👟 Running {app_name} app", end="")
        result = find_and_run_script(path, extra_args)
        if hasattr(result, "returncode"):
            if "Already generated" not in str(result.stdout):
                logger.info("\n")
                logger.info(result.stdout)
            else:
                logger.info(" - no change")
            exit_code = result.returncode
            if exit_code != 0:
                logger.info(f"Error running: {app_name}", result.stdout, result.stderr)
    except Exception as e:
        logger.info(f"Failed to run. {e}")


class AppRunner:
    def __init__(self, client: SyftClientInterface, interval: int = DEFAULT_INTERVAL):
        self.client = client
        self.__event = threading.Event()
        self.interval = interval
        self.__run_thread: threading.Thread

    def start(self):
        def run():
            bootstrap(self.client)
            os.environ["SYFTBOX_CLIENT_CONFIG_PATH"] = str(self.client.config.path)
            while not self.__event.is_set():
                try:
                    run_apps(apps_path=self.client.workspace.apps)
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
