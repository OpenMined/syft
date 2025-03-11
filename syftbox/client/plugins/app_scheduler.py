import os
import subprocess
import threading
from pathlib import Path
from subprocess import Popen
from typing import Dict, Optional

from loguru import logger

from syftbox.client.base import SyftBoxContextInterface
from syftbox.client.plugins.apps import bootstrap, get_clean_env, path_without_virtualenvs
from syftbox.lib.client_config import CONFIG_PATH_ENV

DEFAULT_INTERVAL = 5


class AppScheduler:
    def __init__(self, context: SyftBoxContextInterface, interval: int = DEFAULT_INTERVAL):
        self.__event = threading.Event()
        self.context = context
        self.apps_path = context.workspace.apps
        self.config_path = context.config.path
        self.interval = interval 
        self.__run_thread: Optional[threading.Thread] = None
        self.running_apps: Dict[Path, Popen] = {} 


    def find_and_run_script(
        self, app_path: Path, extra_args: list[str] = list() 
    ) -> None:
        script_path = os.path.join(app_path, "run.sh")

        clean_env = get_clean_env()
        clean_env.update(
            {
                "PATH": path_without_virtualenvs(),
                CONFIG_PATH_ENV: str(self.config_path),
            }
        )

        # Check if the script exists
        if os.path.isfile(script_path):
            # Set execution bit (+x)
            os.chmod(script_path, os.stat(script_path).st_mode | 0o111)

            # Prepare the command based on whether there's a shebang or not
            command = ["sh", script_path] + extra_args
            
            # Setup log file path
            app_name = str(app_path).split('/')[-1]
            log_dir_path = app_path / "logs"
            log_dir_path.mkdir(exist_ok=True)
            log_file_path = os.path.join(log_dir_path, f"{app_name}.log")
            
            # Create a process to run in background
            with open(log_file_path, 'w') as log_file:

                # Run the subprocess
                process = subprocess.Popen(
                    command,
                    cwd=app_path,
                    stdout=log_file.fileno(), # Save stdout in api/app/logs/<app_name>.log 
                    stderr=log_file.fileno(), # Save stderr, in api/app/logs/<app_name>.log,
                    text=True,
                    env=clean_env,
                )

            # Add the new process in the running_apps dict
            self.running_apps[app_path] = process 
        else:
            raise FileNotFoundError(f"run.sh not found in {app_path}")

    
    def schedule_apps(self) -> None:
        """ Method used to schedule apps.


            Steps:
                1 - Look for previous scheduled apps to check if they crashed. If so, remove them from running_apps list,
                so they can be rescheduled in the next step.

                2 - Iterate over the apps folder and compare with the running_apps. If there's an app folder that ins't 
                in the running_apps list. It needs to be scheduled.

                3 - Iterate over the list of running apps and check if they have their respective paths in apis directory,
                if not, that means that app was uninstalled/removed. So we might terminate its process.
        """
        # Step 1 - Reset crashed apps to be rescheduled
        apps_to_be_rescheduled = []
        for app_name, app_process in self.running_apps.items():
            exit_code = app_process.poll()
            
            # Check if the app isn't running anymore.
            if exit_code is not None:
                # Exit code != 0 means that an error ocurred.
                if exit_code != 0:
                    logger.info(f"The app {app_name} didn't run properly. Deleting it from running apps.'")
                    # Remove app from running apps so it gets rescheduled again.
                    apps_to_be_rescheduled.append(app_name)

        for app in apps_to_be_rescheduled:
            self.running_apps.pop(app, None)


        # Step 2 - Schedule Apps that aren't currently running. 
        installed_apps = [p for p in self.apps_path.iterdir() if p.is_dir()]

        apps_to_be_scheduled = [ app for app in installed_apps if app not in self.running_apps] 
        for app in apps_to_be_scheduled:
            logger.info(f"Scheduling {app}")
            self.find_and_run_script(app_path=app)
        
        # Step 3 - Terminate running Apps that were removed.
        apps_to_be_killed = [ app for app in self.running_apps.keys() if app not in installed_apps]
        for app in apps_to_be_killed:
            logger.info(f"Removing {app}")
            self.running_apps[app].terminate()
            self.running_apps.pop(app, None)
        


    def start(self) -> None:
        def run() -> None:
            # Create the apps/apis directory in case it doesn't exist
            bootstrap(self.context)

            while not self.__event.is_set():
                try:
                    self.schedule_apps()
                    self.__event.wait(self.interval)
                except Exception as e:
                    logger.error(f"Error running apps: {str(e)}")

        self.__run_thread = threading.Thread(target=run)
        self.__run_thread.start()

    def stop(self, blocking: bool = False) -> None:
        if not self.__run_thread:
            return

        self.__event.set()
        if blocking:
            self.__run_thread.join()

