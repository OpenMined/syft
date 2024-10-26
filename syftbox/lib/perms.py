import json
from pathlib import Path
from typing import Any, Iterable, Optional, Set

import yaml
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator
from typing_extensions import Self

from syftbox.lib.types import PathLike, UserLike

EVERYONE = "*"

_PERMS_FILE = "syft.pub.yaml"
_PERMS_FILE_LEGACY = "_.syftperm"


class PermissionError(Exception):
    """Custom exception for permission-related errors"""

    pass


class Permissions(BaseModel):
    """Permissions schema for SyftBox

    New instances have no permissions.
    Readers and writers can be empty sets, but not None.
    Values must always be set of strings.
    """

    model_config = ConfigDict(extra="ignore")

    owner: Set[str] = Field(default=set(), alias="admin", validation_alias=AliasChoices("owner", "admin"))
    read: Set[str] = Field(default=set())
    write: Set[str] = Field(default=set())
    terminal: bool = False

    @field_validator("owner", "read", "write", mode="before")
    def str_to_set(cls, value: Any):
        if isinstance(value, str):
            return set([value])
        elif isinstance(value, Iterable):
            val = set(value)
            # todo - legacy perms
            if "GLOBAL" in val:
                val.remove("GLOBAL")
                val.add(EVERYONE)
            # todo - end
            return val
        raise TypeError(f"Invalid type {type(value)}")


class SyftPermission:
    """
    Manages SyftBox permissions for a directory in a datasite.

    NOTE: This class should not be serialized.
    """

    def __init__(self, path: PathLike, perms: Permissions):
        self.path = path
        self.__perms = perms

    def __repr__(self):
        return f"SyftPermission(path={self.path}, owner={self.__perms.owner}, read={self.__perms.read}, write={self.__perms.write})"

    def add_owner(self, *args: UserLike) -> Self:
        self.__perms.owner.update(args)
        return self

    def remove_owner(self, *args: UserLike) -> Self:
        self.__perms.owner.difference_update(args)
        return self

    def add_reader(self, *args: UserLike) -> Self:
        self.__perms.read.update(args)
        return self

    def remove_reader(self, *args: UserLike) -> Self:
        self.__perms.read.difference_update(args)
        return self

    def add_writer(self, *args: UserLike) -> Self:
        self.__perms.write.update(args)
        return self

    def remove_writer(self, *args: UserLike) -> Self:
        self.__perms.write.difference_update(args)
        return self

    def is_owner(self, user: str) -> bool:
        return user in self.__perms.owner

    def can_read(self, user: str) -> bool:
        return EVERYONE in self.__perms.read or user in self.__perms.owner or user in self.__perms.write

    def can_write(self, user: str) -> bool:
        return EVERYONE in self.__perms.write or user in self.__perms.owner or user in self.__perms.write

    def can_read_write(self, user: str) -> bool:
        return self.can_read(user) and self.can_write(user)

    def save(self):
        """Save a permissions file."""

        perms_path = SyftPermission.resolve(self.path)
        perms_path.parent.mkdir(parents=True, exist_ok=True)
        # mode=json to serialize sets as list
        data = yaml.dump(
            self.__perms.model_dump(mode="json"),
            sort_keys=False,
        )
        perms_path.write_text(data)

        # todo - legacy perms - currently we write to both files for backward compat
        lperms_path = SyftPermission.resolve(self.path, _PERMS_FILE_LEGACY)
        lperms_path.write_text(self.__perms.model_dump_json(by_alias=True, indent=4))
        # todo - end

    #############  I/O methods #############

    @classmethod
    def load(cls, path: PathLike) -> Permissions:
        """Load a permissions file. Tries to load the legacy file first."""

        # todo - legacy perms
        lperms_path = SyftPermission.resolve(path, _PERMS_FILE_LEGACY)
        perms_path = SyftPermission.resolve(path)

        data = {}
        if perms_path.exists():
            data = yaml.safe_load(perms_path.read_text())
        else:
            data = json.loads(lperms_path.read_text())

        return cls(perms_path, Permissions(**data))

    #############  Util methods #############

    @classmethod
    def resolve(cls, path: PathLike, filename: str = _PERMS_FILE) -> Path:
        """Resolve a file or a dir to concrete permission file path"""

        path = Path(path).expanduser().resolve()
        if cls.is_perms_file(path):
            return path.parent / filename
        return path / filename

    @classmethod
    def exists(cls, path: Optional[PathLike]) -> bool:
        """Check if a permissions file exists"""

        return cls.resolve(path).exists()

    @classmethod
    def is_valid(cls, path: PathLike) -> bool:
        """Check if path is a valid permissions file"""

        try:
            cls.load(path)
            return True
        except Exception:
            return False

    @classmethod
    def is_perms_file(cls, path: PathLike) -> bool:
        """Path is a permissions file"""

        if isinstance(path, str):
            return path.endswith(_PERMS_FILE) or path.endswith(_PERMS_FILE_LEGACY)
        return path.name in (_PERMS_FILE, _PERMS_FILE_LEGACY)

    #############  Factory methods #############

    @classmethod
    def noperms(cls, path: PathLike) -> Self:
        """Create a permission file with no permissions"""
        return cls(path, Permissions(owner=set(), read=set(), write=set()))

    @classmethod
    def private(cls, path: PathLike, owner: UserLike) -> Self:
        """Create a private permissions file"""
        return cls(path, Permissions(owner=owner, read=set(), write=set()))

    @classmethod
    def readable(cls, path: PathLike, owner: UserLike, users: UserLike = EVERYONE) -> Self:
        """Create a permission file with read-only access to users. Default users is everyone."""

        return cls(path, Permissions(owner=owner, read=users, write=set()))

    @classmethod
    def writeable(cls, path: PathLike, owner: UserLike, users: UserLike = EVERYONE) -> Self:
        """Create a permission file with write-only access to users. Default users is everyone."""

        return cls(path, Permissions(owner=owner, read=[], write=users))

    @classmethod
    def readwrite(cls, path: PathLike, owner: UserLike, users: UserLike = EVERYONE) -> Self:
        """Create a permission file with read-write access to users. Default users is everyone."""

        return cls(path, Permissions(owner=owner, read=users, write=users))


if __name__ == "__main__":
    x = SyftPermission.private("./data/", "admin@admin.com")
    x.save()
