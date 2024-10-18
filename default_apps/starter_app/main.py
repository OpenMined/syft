import json
import subprocess
import shutil
from pathlib import Path
import os

# Load the JSON data from a file
with open("default_apps.json", "r") as file:
    repo_urls = json.load(file)


def clone_apps():
    # Iterate over the list and clone each repository
    for url in repo_urls:
        subprocess.run(["git", "clone", url])


if __name__ == "__main__":
    current_directory = Path(os.getcwd())

    apps_directory = current_directory.parent
    os.chdir(apps_directory)
    clone_apps()
    shutil.rmtree(current_directory)
