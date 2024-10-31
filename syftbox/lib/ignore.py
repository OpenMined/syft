from pathlib import Path
from typing import Optional

import pathspec
from loguru import logger

from syftbox.lib import Client

IGNORE_FILENAME = "_.syftignore"

DEFAULT_IGNORE = """
# Syft
/_.syftignore
/.syft*
/apps
/staging
/syft_changelog

# Python
.ipynb_checkpoints/
__pycache__/
*.py[cod]
.venv/

# OS-specific
.DS_Store
Icon

# IDE/Editor-specific
*.swp
*.swo
.vscode/
.idea/
*.iml

# General excludes
*.tmp

# excluded datasites
# example:
# /user_to_exclude@example.com/
"""


def create_default_ignore_file(client: Client) -> None:
    ignore_file = Path(client.sync_folder) / IGNORE_FILENAME
    if not ignore_file.is_file():
        logger.info(f"Creating default ignore file: {ignore_file}")
        ignore_file.write_text(DEFAULT_IGNORE)


def get_ignore_rules(client: Client) -> Optional[pathspec.PathSpec]:
    ignore_file = Path(client.sync_folder) / IGNORE_FILENAME
    if ignore_file.is_file():
        with open(ignore_file) as f:
            lines = f.readlines()
        return pathspec.PathSpec.from_lines("gitwildmatch", lines)
    return None


def filter_ignored_paths(client: Client, paths: list[Path]) -> list[Path]:
    ignore_rules = get_ignore_rules(client)
    if ignore_rules is None:
        return paths

    filtered_paths = []
    for path in paths:
        if not ignore_rules.match_file(path):
            filtered_paths.append(path)

    return filtered_paths
