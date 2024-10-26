import os
from pathlib import Path
from typing import Iterator

from loguru import logger

from syftbox.lib.perms import SyftPermission
from syftbox.lib.types import PathLike, to_path


class PermissionManager:
    def __init__(self, state: dict[str, SyftPermission], root: PathLike):
        self.state = state
        self.root_path = to_path(root)

    @property
    def root_perms(self) -> SyftPermission:
        # 3.7+ insertion order is maintained.
        return self.state[self.root_path]

    def get_permissions(self, root_path: PathLike) -> SyftPermission:
        # get nearest parent permission
        root_path = to_path(root_path)
        while root_path not in self.state:
            root_path = root_path.parent
        return self.state[root_path]

    @classmethod
    def from_path(cls, root_path: PathLike, raise_on_error: bool = True) -> "PermissionManager":
        perms_state = {}
        root_path = to_path(root_path)

        for path in scan_perm_files(root_path):
            # todo - this case is to handle legacy perms file
            if path.parent in perms_state:
                continue
            # todo - end

            try:
                perms = SyftPermission.load(path)
                perms_state[path.parent] = perms
            except Exception as e:
                logger.warning("invalid perms file", path)
                if raise_on_error:
                    raise e

        return cls(perms_state, root_path)


def scan_files(root: PathLike) -> Iterator[os.DirEntry]:
    """Yield file & directory paths in the provided directory."""

    with os.scandir(str(root)) as it:
        for entry in it:
            if entry.is_file():
                yield entry
            if entry.is_dir():
                yield entry
                yield from scan_files(entry.path)


def scan_perm_files(root: PathLike) -> Iterator[Path]:
    """Yield all permission files in the provided directory."""

    for entry in scan_files(root):
        if SyftPermission.is_perms_file(entry.path):
            yield to_path(entry.path)


def build_tree_string(paths_dict, prefix=""):
    lines = []
    items = list(paths_dict.items())

    for index, (key, value) in enumerate(items):
        # Determine if it's the last item in the current directory level
        connector = "└── " if index == len(items) - 1 else "├── "
        lines.append(f"{prefix}{connector}{repr(key)}")

        # Prepare the prefix for the next level
        if isinstance(value, dict):
            extension = "    " if index == len(items) - 1 else "│   "
            lines.append(build_tree_string(value, prefix + extension))

    return "\n".join(lines)
