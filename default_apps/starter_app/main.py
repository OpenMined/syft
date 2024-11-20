import os
import shutil
import subprocess
from pathlib import Path

DEFAULT_APPS = [
    "https://github.com/OpenMined/ring",
    "https://github.com/OpenMined/github_app_updater",
    "https://github.com/OpenMined/logged_in",
    "https://github.com/OpenMined/inbox",
]


def clone_apps():
    apps = DEFAULT_APPS

    # this is needed for E2E or integration testing to only install only select apps
    # DO NOT MERGE IT WITH DEFAULT_APPS
    env_apps = os.getenv("SYFTBOX_DEFAULT_APPS", None)
    if env_apps:
        print(f"SYFTBOX_DEFAULT_APPS={env_apps}")
        apps = env_apps.strip().split(",")

    print("Installing", apps)

    # Iterate over the list and clone each repository
    for url in apps:
        subprocess.run(["git", "clone", url])

    print("Done")


if __name__ == "__main__":
    current_directory = Path(os.getcwd())

    apps_directory = current_directory.parent
    os.chdir(apps_directory)
    clone_apps()
    shutil.rmtree(current_directory)
