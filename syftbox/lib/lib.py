from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import threading
import zlib
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from threading import Lock
from typing import Any

import requests
from typing_extensions import Self

USER_GROUP_GLOBAL = "GLOBAL"

ICON_FILE = "Icon"  # special
IGNORE_FILES = []


def perm_file_path(path: str) -> str:
    return f"{path}/_.syftperm"


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
    def load(cls, filepath: str) -> Self:
        try:
            with open(filepath) as f:
                data = f.read()
                d = json.loads(data)
                return cls(**d)
        except Exception as e:
            raise e
            print(f"Unable to load jsonable file: {filepath}. {e}")
        return None

    def save(self, filepath: str) -> None:
        d = self.to_dict()
        with open(filepath, "w") as f:
            f.write(json.dumps(d))


@dataclass
class SyftPermission(Jsonable):
    admin: list[str]
    read: list[str]
    write: list[str]
    filepath: str | None = None
    terminal: bool = False

    @classmethod
    def datasite_default(cls, email: str) -> Self:
        return SyftPermission(
            admin=[email],
            read=[email],
            write=[email],
        )

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
        if self.filepath.endswith(".syftperm"):
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
    def no_permission(self) -> Self:
        return SyftPermission(admin=[], read=[], write=[])

    @classmethod
    def mine_no_permission(self, email: str) -> Self:
        return SyftPermission(admin=[email], read=[], write=[])

    @classmethod
    def mine_with_public_read(self, email: str) -> Self:
        return SyftPermission(admin=[email], read=[email, "GLOBAL"], write=[email])

    @classmethod
    def mine_with_public_write(self, email: str) -> Self:
        return SyftPermission(
            admin=[email], read=[email, "GLOBAL"], write=[email, "GLOBAL"]
        )

    @classmethod
    def theirs_with_my_read(self, their_email, my_email: str) -> Self:
        return SyftPermission(
            admin=[their_email], read=[their_email, my_email], write=[their_email]
        )

    @classmethod
    def theirs_with_my_read_write(self, their_email, my_email: str) -> Self:
        return SyftPermission(
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


def bintostr(binary_data):
    return base64.b85encode(zlib.compress(binary_data)).decode("utf-8")


def strtobin(encoded_data):
    return zlib.decompress(base64.b85decode(encoded_data.encode("utf-8")))


class FileChangeKind(Enum):
    CREATE: str = "create"
    # READ: str "read"
    WRITE: str = "write"
    # append?
    DELETE: str = "delete"


@dataclass
class FileChange(Jsonable):
    kind: FileChangeKind
    parent_path: str
    sub_path: str
    file_hash: str
    last_modified: float
    sync_folder: str | None = None

    @property
    def kind_write(self) -> bool:
        return self.kind in [FileChangeKind.WRITE, FileChangeKind.CREATE]

    @property
    def kind_delete(self) -> bool:
        return self.kind == FileChangeKind.DELETE

    def to_dict(self) -> dict:
        output = {}
        for k, v in self.__dict__.items():
            if k.startswith("_"):
                continue
            if k == "kind":
                v = v.value
            output[k] = pack(v)
        return output

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

    def read(self) -> bytes:
        # if is_symlink(self.full_path):
        #     # write a text file with a syftlink
        #     data = convert_to_symlink(self.full_path).encode("utf-8")
        #     return data
        # else:
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
            print(f"Failed to delete file at {self.full_path}. {e}")
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
            print("failed to write", path, e)
            return False


@dataclass
class DirState(Jsonable):
    tree: dict[str, FileInfo]
    timestamp: float
    sync_folder: str
    sub_path: str


def get_symlink(file_path) -> str:
    return os.readlink(file_path)


def is_symlink(file_path) -> bool:
    return os.path.islink(file_path)


# def symlink_to_syftlink(file_path):
#     return SyftLink.from_path(file_path)


# def convert_to_symlink(path):
#     if not is_symlink(path):
#         raise Exception(f"Cant convert a non symlink {path}")
#     abs_path = get_symlink(path)
#     syft_link = symlink_to_syftlink(abs_path)
#     return str(syft_link)


def get_file_last_modified(file_path: str) -> float:
    return os.path.getmtime(file_path)


def get_file_hash(file_path: str) -> str:
    # if is_symlink(file_path):
    #     # return the hash of the syftlink instead
    #     sym_link_string = convert_to_symlink(file_path)
    #     return hashlib.md5(sym_link_string.encode("utf-8")).hexdigest()
    # else:
    with open(file_path, "rb") as file:
        return hashlib.md5(file.read()).hexdigest()


def ignore_dirs(directory: str, root: str, ignore_folders=None) -> bool:
    if ignore_folders is not None:
        for ignore_folder in ignore_folders:
            if root.endswith(ignore_folder):
                return True
    return False


@dataclass
class FileInfo(Jsonable):
    file_hash: str
    last_modified: float


def hash_dir(
    sync_folder: str,
    sub_path: str,
    ignore_folders: list | None = None,
) -> DirState:
    state_dict = {}
    full_path = os.path.join(sync_folder, sub_path)
    for root, dirs, files in os.walk(full_path):
        if not ignore_dirs(full_path, root, ignore_folders):
            for file in files:
                if not ignore_file(full_path, root, file):
                    path = os.path.join(root, file)
                    rel_path = os.path.relpath(path, full_path)
                    file_info = FileInfo(
                        file_hash=get_file_hash(path),
                        last_modified=get_file_last_modified(path),
                    )
                    state_dict[rel_path] = file_info

    utc_unix_timestamp = datetime.now().timestamp()
    dir_state = DirState(
        tree=state_dict,
        timestamp=utc_unix_timestamp,
        sync_folder=sync_folder,
        sub_path=sub_path,
    )
    return dir_state


def ignore_file(directory: str, root: str, filename: str) -> bool:
    if directory == root:
        if filename.startswith(ICON_FILE):
            return True
        if filename in IGNORE_FILES:
            return True
    if filename == ".DS_Store":
        return True
    return False


def get_datasites(sync_folder: str) -> list[str]:
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
    root_perm: SyftPermission | None

    @classmethod
    def from_path(cls, parent_path) -> Self:
        perm_dict = {}
        for root, dirs, files in os.walk(parent_path):
            for file in files:
                if file.endswith(".syftperm"):
                    path = os.path.join(root, file)
                    perm_dict[path] = SyftPermission.load(path)

        root_perm = None
        root_perm_path = perm_file_path(parent_path)
        if root_perm_path in perm_dict:
            root_perm = perm_dict[root_perm_path]

        return PermissionTree(
            root_perm=root_perm, tree=perm_dict, parent_path=parent_path
        )

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
                # we could do some overlay with defaults but
                # for now lets just use a fully defined overwriting perm file
                next_perm = self.tree[next_perm_file]
                current_perm = next_perm

            if current_perm.terminal:
                return current_perm

        return current_perm

    def __repr__(self) -> str:
        return f"PermissionTree: {self.parent_path}\n" + build_tree_string(self.tree)


def filter_read_state(user_email: str, dir_state: DirState, perm_tree: PermissionTree):
    filtered_tree = {}
    root_dir = dir_state.sync_folder + "/" + dir_state.sub_path
    for file_path, file_info in dir_state.tree.items():
        full_path = root_dir + "/" + file_path
        perm_file_at_path = perm_tree.permission_for_path(full_path)
        if (
            user_email in perm_file_at_path.read
            or "GLOBAL" in perm_file_at_path.read
            or user_email in perm_file_at_path.admin
        ):
            filtered_tree[file_path] = file_info
    return filtered_tree


class ResettableTimer:
    def __init__(self, timeout, callback, *args, **kwargs):
        self.timeout = timeout
        self.callback = callback
        self.args = args
        self.kwargs = kwargs
        self.timer = None
        self.lock = threading.Lock()

    def _run_callback(self):
        with self.lock:
            self.timer = None
        self.callback(*self.args, **self.kwargs)

    def start(self, *args, **kwargs):
        with self.lock:
            if self.timer:
                self.timer.cancel()

            # If new arguments are passed in start, they will overwrite the initial ones
            if args or kwargs:
                self.args = args
                self.kwargs = kwargs

            self.timer = threading.Timer(self.timeout, self._run_callback)
            self.timer.start()

    def cancel(self):
        with self.lock:
            if self.timer:
                self.timer.cancel()
                self.timer = None


class SharedState:
    def __init__(self, client_config: ClientConfig):
        self.data = {}
        self.lock = Lock()
        self.client_config = client_config
        self.timers: dict[str:ResettableTimer] = {}
        self.fs_events = []

    @property
    def sync_folder(self) -> str:
        return self.client_config.sync_folder

    def get(self, key, default=None):
        with self.lock:
            if key == "my_datasites":
                return self._get_datasites()
            return self.data.get(key, default)

    def set(self, key, value):
        with self.lock:
            self.data[key] = value

    def _get_datasites(self):
        syft_folder = self.data.get(self.client_config.sync_folder)
        if not syft_folder or not os.path.exists(syft_folder):
            return []

        return [
            folder
            for folder in os.listdir(syft_folder)
            if os.path.isdir(os.path.join(syft_folder, folder))
        ]


def get_root_data_path() -> Path:
    # get the PySyft / data directory to share datasets between notebooks
    # on Linux and MacOS the directory is: ~/.syft/data"
    # on Windows the directory is: C:/Users/$USER/.syft/data

    data_dir = Path.home() / ".syft" / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    return data_dir


def autocache(
    url: str, extension: str | None = None, cache: bool = True
) -> Path | None:
    try:
        data_path = get_root_data_path()
        file_hash = hashlib.sha256(url.encode("utf8")).hexdigest()
        filename = file_hash
        if extension:
            filename += f".{extension}"
        file_path = data_path / filename
        if os.path.exists(file_path) and cache:
            return file_path
        return download_file(url, file_path)
    except Exception as e:
        print(f"Failed to autocache: {url}. {e}")
        return None


def download_file(url: str, full_path: str | Path) -> Path | None:
    full_path = Path(full_path)
    if not full_path.exists():
        r = requests.get(url, allow_redirects=True, verify=verify_tls())  # nosec
        if not r.ok:
            print(f"Got {r.status_code} trying to download {url}")
            return None
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_bytes(r.content)
    return full_path


def verify_tls() -> bool:
    return not str_to_bool(str(os.environ.get("IGNORE_TLS_ERRORS", "0")))


def str_to_bool(bool_str: str | None) -> bool:
    result = False
    bool_str = str(bool_str).lower()
    if bool_str == "true" or bool_str == "1":
        result = True
    return result


def validate_email(email: str) -> bool:
    # Define a regex pattern for a valid email
    email_regex = r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"

    # Use the match method to check if the email fits the pattern
    if re.match(email_regex, email):
        return True
    return False


@dataclass
class ClientConfig(Jsonable):
    config_path: Path
    sync_folder: Path | None = None
    port: int | None = None
    email: str | None = None
    token: int | None = None
    server_url: str = "http://localhost:5001"
    email_token: str | None = None

    def save(self, path: str | None = None) -> None:
        if path is None:
            path = self.config_path
        super().save(path)

    @property
    def datasite_path(self) -> Path:
        return os.path.join(self.sync_folder, self.email)

    @property
    def manifest_path(self) -> Path:
        return os.path.join(self.datasite_path, "public/manifest/manifest.json")

    # @property
    # def manifest(self) -> DatasiteManifest:
    #     datasite_manifest = None
    #     try:
    #         datasite_manifest = DatasiteManifest.load(self.manifest_path)
    #     except Exception:
    #         datasite_manifest = DatasiteManifest.create_manifest(
    #             path=self.manifest_path, email=self.email
    #         )

    #     return datasite_manifest

    def get_datasites(self: str) -> list[str]:
        datasites = []
        folders = os.listdir(self.sync_folder)
        for folder in folders:
            if "@" in folder:
                datasites.append(folder)
        return datasites

    # def get_all_manifests(self):
    #     manifests = {}
    #     for datasite in get_datasites(self.sync_folder):
    #         datasite_path = Path(self.sync_folder + "/" + datasite)
    #         datasite_manifest = DatasiteManifest.load_from_datasite(datasite_path)
    #         if datasite_manifest:
    #             manifests[datasite] = datasite_manifest
    #     return manifests

    # def get_datasets(self):
    #     manifests = self.get_all_manifests()
    #     datasets = []
    #     for datasite, manifest in manifests.items():
    #         for dataset_name, dataset_dict in manifest.datasets.items():
    #             try:
    #                 dataset = TabularDataset(**dataset_dict)
    #                 dataset.syft_link = SyftLink(**dataset_dict["syft_link"])
    #                 dataset.readme_link = SyftLink(**dataset_dict["readme_link"])
    #                 dataset.loader_link = SyftLink(**dataset_dict["loader_link"])
    #                 dataset._client_config = self
    #                 datasets.append(dataset)
    #             except Exception as e:
    #                 print(f"Bad dataset format. {datasite} {e}")

    #     return DatasetResults(datasets)

    # def get_code(self):
    #     manifests = self.get_all_manifests()
    #     all_code = []
    #     for datasite, manifest in manifests.items():
    #         for func_name, code_dict in manifest.code.items():
    #             try:
    #                 code = Code(**code_dict)
    #                 code.syft_link = SyftLink(**code_dict["syft_link"])
    #                 code.readme_link = SyftLink(**code_dict["readme_link"])
    #                 code.requirements_link = SyftLink(**code_dict["requirements_link"])
    #                 code._client_config = self
    #                 all_code.append(code)
    #             except Exception as e:
    #                 print(f"Bad dataset format. {datasite} {e}")

    #     return CodeResults(all_code)

    # def resolve_link(self, link: SyftLink | str) -> Path:
    #     if isinstance(link, str):
    #         link = SyftLink.from_url(link)
    #     return Path(os.path.join(os.path.abspath(self.sync_folder), link.sync_path))

    def use(self):
        os.environ["SYFTBOX_CURRENT_CLIENT"] = self.config_path
        os.environ["SYFTBOX_SYNC_DIR"] = self.sync_folder
        print(f"> Setting Sync Dir to: {self.sync_folder}")

    # @classmethod
    # def create_manifest(cls, path: str, email: str):
    #     # make a dir and set the permissions
    #     manifest_dir = os.path.dirname(path)
    #     os.makedirs(manifest_dir, exist_ok=True)

    #     public_read = SyftPermission.mine_with_public_read(email=email)
    #     public_read.save(manifest_dir)

    #     datasite_manifest = DatasiteManifest(datasite=email, file_path=path)
    #     datasite_manifest.save(path)
    #     return datasite_manifest

    def create_folder(self, path: str, permission: SyftPermission):
        os.makedirs(path, exist_ok=True)
        permission.save(path)

    @property
    def root_dir(self) -> Path:
        root_dir = Path(os.path.abspath(os.path.dirname(self.file_path) + "/../"))
        return root_dir

    def create_public_folder(self, path: str):
        full_path = self.root_dir / path
        os.makedirs(str(full_path), exist_ok=True)
        public_read = SyftPermission.mine_with_public_read(email=self.datasite)
        public_read.save(full_path)
        return Path(full_path)

    # def publish(self, item, overwrite: bool = False):
    #     if isinstance(item, Callable):
    #         syftbox_code(item).publish(self, overwrite=overwrite)
