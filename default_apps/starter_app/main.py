import os
import shutil
import subprocess
from pathlib import Path

default_apps = [
    "https://github.com/OpenMined/ring",
    "https://github.com/OpenMined/github_app_updater",
    "https://github.com/OpenMined/logged_in",
]


def clone_apps():
    global default_apps
    if os.getenv("SYFTBOX_DEFAULT_APPS", None) is not None:
        default_apps = os.environ["SYFTBOX_DEFAULT_APPS"].strip().split(",")

    # Iterate over the list and clone each repository
    for url in default_apps:
        subprocess.run(["git", "clone", url])


if __name__ == "__main__":
    current_directory = Path(os.getcwd())

    apps_directory = current_directory.parent
    os.chdir(apps_directory)
    clone_apps()
    shutil.rmtree(current_directory)
