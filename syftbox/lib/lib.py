from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from loguru import logger
from typing_extensions import Any, Optional, Self, Union

from syftbox.lib.constants import PERM_FILE
from syftbox.server.sync.models import FileMetadata

USER_GROUP_GLOBAL = "GLOBAL"

ICON_FILE = "Icon"  # special
IGNORE_FILES = []


def perm_file_path(path: str) -> str:
    return os.path.join(path, PERM_FILE)


def is_primitive_json_serializable(obj):
    if isinstance(obj, (str, int, float, bool, type(None))):
        return True
    return False


def pack(obj) -> Any:
    if is_primitive_json_serializable(obj):
        return obj

    if hasattr(obj, "to_dict"):
        return obj.to_dict()

    if isinstance(obj, list):
        return [pack(val) for val in obj]

    if isinstance(obj, dict):
        return {k: pack(v) for k, v in obj.items()}

    if isinstance(obj, Path):
        return str(obj)

    raise Exception(f"Unable to pack type: {type(obj)} value: {obj}")


class Jsonable:
    def to_dict(self) -> dict:
        output = {}
        for k, v in self.__dict__.items():
            if k.startswith("_"):
                continue
            output[k] = pack(v)
        return output

    def __iter__(self):
        for key, val in self.to_dict().items():
            if key.startswith("_"):
                yield key, val

    def __getitem__(self, key):
        if key.startswith("_"):
            return None
        return self.to_dict()[key]

    @classmethod
    def load(cls, file_or_bytes: Union[str, Path, bytes]) -> Self:
        try:
            if isinstance(file_or_bytes, (str, Path)):
                with open(file_or_bytes) as f:
                    data = f.read()
            else:
                data = file_or_bytes
            d = json.loads(data)
            return cls(**d)
        except Exception as e:
            raise e

    def save(self, filepath: str) -> None:
        d = self.to_dict()
        with open(Path(filepath).expanduser(), "w") as f:
            f.write(json.dumps(d))


@dataclass
class SyftPermission(Jsonable):
    admin: list[str]
    read: list[str]
    write: list[str]
    filepath: Optional[str] = None
    terminal: bool = False

    @classmethod
    def datasite_default(cls, email: str) -> Self:
        return cls(
            admin=[email],
            read=[email],
            write=[email],
        )

    @staticmethod
    def is_permission_file(path: Union[Path, str], check_exists: bool = False) -> bool:
        path = Path(path)
        if check_exists and not path.is_file():
            return False
        return path.name == "_.syftperm"

    @classmethod
    def is_valid(cls, path_or_bytes: Union[str, Path, bytes]):
        try:
            SyftPermission.load(path_or_bytes)
            return True
        except Exception:
            return False

    def is_admin(self, email: str) -> bool:
        return email in self.admin

    def has_read_permission(self, email: str) -> bool:
        return email in self.read or USER_GROUP_GLOBAL in self.read

    def has_write_permission(self, email: str) -> bool:
        return email in self.write or USER_GROUP_GLOBAL in self.write

    def __eq__(self, other):
        if not isinstance(other, SyftPermission):
            return NotImplemented
        return (
            self.admin == other.admin
            and self.read == other.read
            and self.write == other.write
            and self.filepath == other.filepath
            and self.terminal == other.terminal
        )

    def perm_path(self, path=None) -> str:
        if path is not None:
            self.filepath = path

        if self.filepath is None:
            raise Exception(f"Saving requites a path: {self}")

        if os.path.isdir(self.filepath):
            self.filepath = perm_file_path(self.filepath)
        return self.filepath

    def save(self, path=None) -> bool:
        self.perm_path(path=path)
        if str(self.filepath).endswith(".syftperm"):
            super().save(self.filepath)
        else:
            raise Exception(f"Perm file must end in .syftperm. {self.filepath}")
        return True

    def ensure(self, path=None) -> bool:
        # make sure the contents matches otherwise write it
        self.perm_path(path=path)
        try:
            prev_perm_file = SyftPermission.load(self.filepath)
            if self == prev_perm_file:
                # no need to write
                return True
        except Exception:
            pass
        return self.save(path)

    @classmethod
    def no_permission(cls) -> Self:
        return cls(admin=[], read=[], write=[])

    @classmethod
    def mine_no_permission(cls, email: str) -> Self:
        return cls(admin=[email], read=[], write=[])

    @classmethod
    def mine_with_public_read(cls, email: str) -> Self:
        return cls(admin=[email], read=[email, "GLOBAL"], write=[email])

    @classmethod
    def mine_with_public_write(cls, email: str) -> Self:
        return cls(admin=[email], read=[email, "GLOBAL"], write=[email, "GLOBAL"])

    @classmethod
    def theirs_with_my_read(cls, their_email, my_email: str) -> Self:
        return cls(admin=[their_email], read=[their_email, my_email], write=[their_email])

    @classmethod
    def theirs_with_my_read_write(cls, their_email, my_email: str) -> Self:
        return cls(
            admin=[their_email],
            read=[their_email, my_email],
            write=[their_email, my_email],
        )

    def __repr__(self) -> str:
        string = "SyftPermission:\n"
        string += f"{self.filepath}\n"
        string += "ADMIN: ["
        for v in self.admin:
            string += v + ", "
        string += "]\n"

        string += "READ: ["
        for r in self.read:
            string += r + ", "
        string += "]\n"

        string += "WRITE: ["
        for w in self.write:
            string += w + ", "
        string += "]\n"
        return string


def get_datasites(sync_folder: Union[str, Path]) -> list[str]:
    sync_folder = str(sync_folder.resolve()) if isinstance(sync_folder, Path) else sync_folder
    datasites = []
    folders = os.listdir(sync_folder)
    for folder in folders:
        if "@" in folder:
            datasites.append(folder)
    return datasites


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


@dataclass
class PermissionTree(Jsonable):
    tree: dict[str, SyftPermission]
    parent_path: str
    root_perm: Optional[SyftPermission]

    corrupted_permission_files: list[str] = field(default_factory=list)

    @classmethod
    def from_path(cls, parent_path, raise_on_corrupted_files: bool = False) -> Self:
        corrupted_permission_files = []
        perm_dict = {}
        for root, dirs, files in os.walk(parent_path):
            for file in files:
                if file.endswith(".syftperm"):
                    path = os.path.join(root, file)
                    try:
                        perm_dict[path] = SyftPermission.load(path)
                    except Exception:
                        corrupted_permission_files.append(path)

        root_perm = None
        root_perm_path = perm_file_path(parent_path)
        if root_perm_path in perm_dict:
            root_perm = perm_dict[root_perm_path]

        if corrupted_permission_files:
            if raise_on_corrupted_files:
                raise ValueError(f"Found corrupted permission files: {corrupted_permission_files}")
            logger.warning(f"Found corrupted permission files: {corrupted_permission_files}")

        return cls(
            root_perm=root_perm,
            tree=perm_dict,
            parent_path=parent_path,
            corrupted_permission_files=corrupted_permission_files,
        )

    def has_corrupted_permission(self, path: Union[str, Path]) -> bool:
        path = Path(path).resolve()
        corrupted_permission_paths = [Path(p).parent.resolve() for p in self.corrupted_permission_files]
        for perm_path in corrupted_permission_paths:
            if path.is_relative_to(perm_path):
                return True
        return False

    @property
    def root_or_default(self) -> SyftPermission:
        if self.root_perm:
            return self.root_perm
        return SyftPermission.no_permission()

    def permission_for_path(self, path: str) -> SyftPermission:
        parent_path = os.path.normpath(self.parent_path)
        current_perm = self.root_or_default

        # default
        if parent_path not in path:
            return current_perm

        sub_path = path.replace(parent_path, "")
        current_perm_level = parent_path
        for part in sub_path.split("/"):
            if part == "":
                continue

            current_perm_level += "/" + part
            next_perm_file = perm_file_path(current_perm_level)
            if next_perm_file in self.tree:
                next_perm = self.tree[next_perm_file]
                current_perm = next_perm

            if current_perm.terminal:
                return current_perm

        return current_perm

    def __repr__(self) -> str:
        return f"PermissionTree: {self.parent_path}\n" + build_tree_string(self.tree)


def filter_metadata(
    user_email: str,
    metadata_list: list[FileMetadata],
    perm_tree: PermissionTree,
    snapshot_folder: Path,
) -> list[FileMetadata]:
    filtered_metadata = []
    for metadata in metadata_list:
        perm_file_at_path = perm_tree.permission_for_path((snapshot_folder / metadata.path).as_posix())
        if (
            user_email in perm_file_at_path.read
            or "GLOBAL" in perm_file_at_path.read
            or user_email in perm_file_at_path.admin
        ):
            filtered_metadata.append(metadata)
    return filtered_metadata
