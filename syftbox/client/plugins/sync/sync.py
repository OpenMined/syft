import os
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional, Union

from loguru import logger

from syftbox import Client
from syftbox.client.plugins.sync.endpoints import get_remote_state
from syftbox.lib import DirState
from syftbox.lib.ignore import filter_ignored_paths
from syftbox.server.models import SyftBaseModel
from syftbox.server.sync.hash import hash_dir
from syftbox.server.sync.models import FileMetadata


def is_permission_file(path: Union[Path, str], check_exists: bool = False) -> bool:
    path = Path(path)
    if check_exists and not path.is_file():
        return False

    return path.name == "_.syftperm"


class SyncSide(str, Enum):
    LOCAL = "local"
    REMOTE = "remote"


class FileChangeInfo(SyftBaseModel, frozen=True):
    path: Path
    side_last_modified: SyncSide
    date_last_modified: datetime
    file_size: int = 1

    def get_priority(self) -> int:
        if is_permission_file(self.path):
            return 0
        else:
            return max(1, self.file_size)

    def __lt__(self, other: "FileChangeInfo") -> bool:
        return self.path < other.path


class DatasiteState:
    def __init__(self, client: Client, email: str):
        """
        NOTE DatasiteState is not threadsafe, this should be handled by the caller
        """
        self.client = client
        self.email = email

    @property
    def path(self) -> Path:
        p = Path(self.client.sync_folder) / self.email
        return p.expanduser().resolve()

    def get_current_local_state(self) -> list[FileMetadata]:
        return hash_dir(self.path, root_dir=self.client.sync_folder)

    def get_remote_state(self) -> list[FileMetadata]:
        return get_remote_state(self.client.server_client, email=self.client.email, path=Path(self.email))

    def get_out_of_sync_files(
        self,
    ) -> tuple[list[FileChangeInfo], list[FileChangeInfo]]:
        """
        calculate the files that are out of sync

        NOTE: we are not handling local permissions here,
        they will be handled by the server and consumer
        TODO: we are not handling empty folders
        """
        try:
            local_state = self.get_current_local_state()
        except Exception:
            logger.error(f"Failed to get local state for {self.email}")
            return [], []

        try:
            remote_state = self.get_remote_state()
        except Exception:
            logger.error(f"Failed to get remote state from server {self.email}")
            return [], []

        local_state_dict = {file.path: file for file in local_state}
        remote_state_dict = {file.path: file for file in remote_state}
        all_files = set(local_state_dict.keys()) | set(remote_state_dict.keys())
        all_files_filtered = filter_ignored_paths(client=self.client, paths=list(all_files))

        all_changes = []

        for afile in all_files_filtered:
            local_info = local_state_dict.get(afile)
            remote_info = remote_state_dict.get(afile)

            try:
                change_info = compare_fileinfo(afile, local_info, remote_info)
            except Exception:
                logger.exception(f"Failed to compare file {afile}")
                continue

            if change_info is not None:
                all_changes.append(change_info)

        # TODO implement ignore rules
        # ignore_rules = get_ignore_rules(local_state)
        # filtered_changes = filter_ignored_changes(all_changes, ignore_rules)

        permission_changes, file_changes = split_permissions(all_changes)
        # TODO debounce changes
        # filtered_changes = filter_recent_local_changes(filtered_changes)

        return permission_changes, file_changes


def split_permissions(
    changes: list[FileChangeInfo],
) -> tuple[list[FileChangeInfo], list[FileChangeInfo]]:
    permissions = []
    files = []
    for change in changes:
        if is_permission_file(change.path):
            permissions.append(change)
        else:
            files.append(change)
    return permissions, files


def compare_fileinfo(
    path: Path,
    local_info: Optional[FileMetadata],
    remote_info: Optional[FileMetadata],
) -> Optional[FileChangeInfo]:
    if local_info is None and remote_info is None:
        return

    if local_info is None and remote_info is not None:
        # File only exists on remote
        return FileChangeInfo(
            path=path,
            side_last_modified=SyncSide.REMOTE,
            date_last_modified=remote_info.last_modified,
            file_size=remote_info.file_size,
        )

    if remote_info is None and local_info is not None:
        # File only exists on local
        return FileChangeInfo(
            path=path,
            side_last_modified=SyncSide.LOCAL,
            date_last_modified=local_info.last_modified,
            file_size=local_info.file_size,
        )

    if local_info.hash != remote_info.hash:
        # File is different on both sides
        if local_info.last_modified > remote_info.last_modified:
            date_last_modified = local_info.last_modified
            side_last_modified = SyncSide.LOCAL
            file_size = local_info.file_size
        else:
            date_last_modified = remote_info.last_modified
            side_last_modified = SyncSide.REMOTE
            file_size = remote_info.file_size

        return FileChangeInfo(
            path=path,
            side_last_modified=side_last_modified,
            date_last_modified=date_last_modified,
            file_size=file_size,
        )


def get_ignore_rules(dir_state: DirState) -> list[str, str, str]:
    """
    TODO refactor, abs/relative paths are not handled correctly
    returns a list of ignore rules (prefix, folder, ignore_file)
    """
    # get the ignore files
    syft_ignore_files = []
    folder_path = dir_state.sync_folder + "/" + dir_state.sub_path
    for afile, file_info in dir_state.tree.items():
        full_path = folder_path + "/" + afile
        sub_folder = os.path.dirname(full_path)

        if afile.endswith(".syftignore") and os.path.isfile(full_path):
            ignore_list = []
            with open(full_path) as f:
                ignore_list = f.readlines()
            for ignore_rule in ignore_list:
                ignore_rule = ignore_rule.strip()
                rule_prefix = sub_folder + "/" + ignore_rule
                syft_ignore_files.append((rule_prefix, sub_folder, afile))

    return syft_ignore_files


def filter_ignored_changes(
    all_changes: list[FileChangeInfo], ignore_rules: list[str, str, str]
) -> list[FileChangeInfo]:
    """
    Filter out changes that are ignored by .syftignore files
    """
    filtered_changes = []
    for change in all_changes:
        keep = True
        for rule_prefix, ignore_folder, ignore_file_path in ignore_rules:
            if change.path.startswith(rule_prefix):
                keep = False
                break
        if keep:
            filtered_changes.append(change)
    return filtered_changes
