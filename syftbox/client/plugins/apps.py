import hashlib
import json
import os
import shutil
import subprocess
import threading
import time
from datetime import datetime
from types import SimpleNamespace
from pathlib import Path

from croniter import croniter
from loguru import logger
from typing_extensions import Any, Optional, Union

from syftbox.lib import (
    SyftPermission,
    perm_file_path,
)


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


DEFAULT_SCHEDULE = 10000
DESCRIPTION = "Runs Apps"
RUNNING_APPS = {}
DEFAULT_APPS_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "default_apps"))


def copy_default_apps(apps_path):
    if not os.path.exists(DEFAULT_APPS_PATH):
        logger.info(f"Default apps directory not found: {DEFAULT_APPS_PATH}")
        return

    for app in os.listdir(DEFAULT_APPS_PATH):
        src_app_path = os.path.join(DEFAULT_APPS_PATH, app)
        dst_app_path = os.path.join(apps_path, app)

        if os.path.isdir(src_app_path):
            if os.path.exists(dst_app_path):
                logger.info(f"App already installed at: {dst_app_path}")
                # shutil.rmtree(dst_app_path)
            else:
                shutil.copytree(src_app_path, dst_app_path)
            logger.info(f"Copied default app: {app}")


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


def run_apps(client_config):
    # create the directory
    apps_path = str(Path(client_config.sync_folder) / "apps")
    os.makedirs(apps_path, exist_ok=True)

    # Copy default apps if they don't exist
    copy_default_apps(apps_path)

    # add the first perm file
    file_path = perm_file_path(apps_path)
    if os.path.exists(file_path):
        perm_file = SyftPermission.load(file_path)
    else:
        logger.info(f"> {client_config.email} Creating Apps Permfile")
        try:
            perm_file = SyftPermission.datasite_default(client_config.email)
            perm_file.save(file_path)
        except Exception as e:
            logger.error("Failed to create perm file")
            logger.exception(e)

    apps = os.listdir(apps_path)
    for app in apps:
        app_path = os.path.abspath(apps_path + "/" + app)
        if os.path.isdir(app_path):
            app_config = load_config(app_path + "/" + "config.json")
            if app_config is None:
                run_app(client_config, app_path)
            elif RUNNING_APPS.get(app, None) is None:
                logger.info("⏱  Scheduling a  new app run.")
                thread = threading.Thread(
                    target=run_custom_app_config,
                    args=(client_config, app_config, app_path),
                )
                thread.start()
                RUNNING_APPS[app] = thread


def get_file_hash(file_path, digest="md5") -> str:
    with open(file_path, "rb") as f:
        return hashlib.file_digest(f, digest)


def output_published(app_output, published_output) -> bool:
    return (
        os.path.exists(app_output)
        and os.path.exists(published_output)
        and get_file_hash(app_output, "md5") == get_file_hash(published_output, "md5")
    )


def run_custom_app_config(client_config, app_config, path):
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

    while True:
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


def run_app(client_config, path):
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


def run(shared_state):
    # logger.info("> Running Apps")
    client_config = shared_state.client_config
    run_apps(client_config)
