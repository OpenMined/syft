import json
import os
import shutil
import subprocess
import threading
from types import SimpleNamespace

from loguru import logger
from typing_extensions import Any

from syftbox.lib import (
    SyftPermission,
    get_file_hash,
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
        command = (
            [script_path] + extra_args
            if has_shebang
            else ["/bin/bash", script_path] + extra_args
        )

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
        except Exception as e:
            logger.info("Error running shell script", e)
    else:
        raise FileNotFoundError(f"run.sh not found in {task_path}")


DEFAULT_SCHEDULE = 10000
DESCRIPTION = "Runs Apps"
RUNNING_APPS = {}
DEFAULT_APPS_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "default_apps")
)


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


def dict_to_namespace(data) -> SimpleNamespace | list | Any:
    if isinstance(data, dict):
        return SimpleNamespace(
            **{key: dict_to_namespace(value) for key, value in data.items()}
        )
    elif isinstance(data, list):
        return [dict_to_namespace(item) for item in data]
    else:
        return data


def load_config(path: str) -> None | SimpleNamespace:
    try:
        with open(path, "r") as f:
            data = json.load(f)
        return dict_to_namespace(data)
    except Exception:
        return None


def run_apps(client_config):
    # create the directory
    apps_path = client_config.sync_folder + "/" + "apps"
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


def output_published(app_output, published_output) -> bool:
    return (
        os.path.exists(app_output)
        and os.path.exists(published_output)
        and get_file_hash(app_output) == get_file_hash(published_output)
    )


def run_custom_app_config(client_config, app_config, path):
    import time

    env = os.environ.copy()  # Copy the current environment
    app_name = os.path.basename(path)

    app_envs = getattr(app_config.app, "env", {})
    if not isinstance(app_envs, dict):
        app_envs = vars(app_envs)

    env.update(app_envs)
    while True:
        logger.info(f"👟 Running {app_name}")
        _ = subprocess.run(
            app_config.app.run.command,
            cwd=path,
            check=True,
            capture_output=True,
            text=True,
            env=env,
        )
        time.sleep(int(app_config.app.run.interval))


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
