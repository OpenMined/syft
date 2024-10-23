import hashlib
import os
from enum import Enum
from pathlib import Path

from loguru import logger
from pydantic import BaseModel
from typing_extensions import Optional, Self, Union


class SyftBaseModel(BaseModel):
    def to_dict(self) -> dict:
        # used until we remote Jsonable from the code base
        return self.model_dump(mode="json")

    def save(self, path: Union[str, Path]) -> dict:
        if isinstance(path, Path):
            path = str(path)
        with open(path, "w") as f:
            f.write(self.model_dump_json())
        return self.model_dump(mode="json")

    @classmethod
    def load(cls, filepath: str) -> Self:
        with open(filepath) as f:
            data = f.read()
            return cls.model_validate_json(data)


class FileChangeKind(Enum):
    CREATE: str = "create"
    # READ: str "read"
    WRITE: str = "write"
    # append?
    DELETE: str = "delete"


class FileChange(SyftBaseModel):
    kind: FileChangeKind
    parent_path: str
    sub_path: str
    file_hash: str
    last_modified: float
    sync_folder: Optional[str] = None

    @property
    def kind_write(self) -> bool:
        return self.kind in [FileChangeKind.WRITE, FileChangeKind.CREATE]

    @property
    def kind_delete(self) -> bool:
        return self.kind == FileChangeKind.DELETE

    @property
    def full_path(self) -> str:
        return self.sync_folder + "/" + self.parent_path + "/" + self.sub_path

    @property
    def internal_path(self) -> str:
        return self.parent_path + "/" + self.sub_path

    def hash_equal_or_none(self) -> bool:
        if not os.path.exists(self.full_path):
            return True

        local_file_hash = get_file_hash(self.full_path)
        return self.file_hash == local_file_hash

    def newer(self) -> bool:
        if not os.path.exists(self.full_path):
            return True

        local_last_modified = get_file_last_modified(self.full_path)
        if self.last_modified >= local_last_modified:
            return True

        return False

    def is_directory(self) -> bool:
        return os.path.isdir(self.full_path)

    def read(self) -> Optional[bytes]:
        # if is_symlink(self.full_path):
        #     # write a text file with a syftlink
        #     data = convert_to_symlink(self.full_path).encode("utf-8")
        #     return data
        # else:
        if self.is_directory():
            return None
        with open(self.full_path, "rb") as f:
            return f.read()

    def write(self, data: bytes) -> bool:
        # if its a non private syftlink turn it into a symlink
        # if data.startswith(b"syft://") and not self.full_path.endswith(".private"):
        #     syft_link = SyftLink.from_url(data.decode("utf-8"))
        #     abs_path = os.path.join(
        #         os.path.abspath(self.sync_folder), syft_link.sync_path
        #     )
        #     if not os.path.exists(abs_path):
        #         raise Exception(
        #             f"Cant make symlink because source doesnt exist {abs_path}"
        #         )
        #     dir_path = os.path.dirname(self.full_path)
        #     os.makedirs(dir_path, exist_ok=True)
        #     if os.path.exists(self.full_path) and is_symlink(self.full_path):
        #         os.unlink(self.full_path)
        #     os.symlink(abs_path, self.full_path)
        #     os.utime(
        #         self.full_path,
        #         (self.last_modified, self.last_modified),
        #         follow_symlinks=False,
        #     )

        #     return True
        # else:
        return self.write_to(data, self.full_path)

    def delete(self) -> bool:
        try:
            os.unlink(self.full_path)
            return True
        except Exception as e:
            if "No such file" in str(e):
                return True
            logger.info(f"Failed to delete file at {self.full_path}. {e}")
        return False

    def write_to(self, data: bytes, path: str) -> bool:
        base_dir = os.path.dirname(path)
        os.makedirs(base_dir, exist_ok=True)
        try:
            with open(path, "wb") as f:
                f.write(data)
            os.utime(
                path,
                (self.last_modified, self.last_modified),
                follow_symlinks=False,
            )
            return True
        except Exception as e:
            logger.error(f"failed to write to {path}.")
            logger.exception(e)
            return False


class WriteRequest(BaseModel):
    email: str
    change: FileChange
    is_directory: bool = False
    data: Optional[str] = None


class WriteResponse(BaseModel):
    accepted: bool
    change: FileChange
    status: str


class ListDatasitesResponse(BaseModel):
    datasites: list[str]
    status: str


class ReadResponse(BaseModel):
    change: FileChange
    status: str
    is_directory: bool = False
    data: Optional[str] = None


class ReadRequest(BaseModel):
    email: str
    change: FileChange


class FileInfo(SyftBaseModel):
    file_hash: str
    last_modified: float
    num_bytes: int


class DirState(SyftBaseModel):
    tree: dict[str, FileInfo]
    timestamp: float
    sync_folder: str
    sub_path: str


class DirStateRequest(SyftBaseModel):
    email: str
    sub_path: str


class DirStateResponse(SyftBaseModel):
    sub_path: str
    dir_state: DirState
    status: str


def get_file_last_modified(file_path: str) -> float:
    return os.path.getmtime(file_path)


def get_file_size(file_path: str) -> int:
    return os.path.getsize(file_path)


def get_file_hash(file_path: str) -> str:
    # if is_symlink(file_path):
    #     # return the hash of the syftlink instead
    #     sym_link_string = convert_to_symlink(file_path)
    #     return hashlib.md5(sym_link_string.encode("utf-8")).hexdigest()
    # else:
    # TODO: we will run out of memory for very large files
    with open(file_path, "rb") as file:
        return hashlib.md5(file.read()).hexdigest()
