from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

from loguru import logger
from pydantic import BaseModel

from syftbox.client.plugins.sync.endpoints import get_remote_state
from syftbox.lib import Client
from syftbox.lib.ignore import filter_ignored_paths
from syftbox.lib.lib import SyftPermission
from syftbox.server.sync.hash import hash_dir
from syftbox.server.sync.models import FileMetadata


class SyncSide(str, Enum):
    LOCAL = "local"
    REMOTE = "remote"


class FileChangeInfo(BaseModel, frozen=True):
    local_sync_folder: Path
    path: Path
    side_last_modified: SyncSide
    date_last_modified: datetime
    file_size: int = 1

    @property
    def local_abs_path(self) -> Path:
        return self.local_sync_folder / self.path

    def get_priority(self) -> int:
        if SyftPermission.is_permission_file(self.path):
            return 0
        else:
            return max(1, self.file_size)

    def __lt__(self, other: "FileChangeInfo") -> bool:
        return self.path < other.path


class DatasiteState:
    def __init__(self, client: Client, email: str, remote_state: Optional[list[FileMetadata]] = None) -> None:
        """A class to represent the state of a datasite

        Args:
            client (Client): User client
            email (str): Email of the datasite
            remote_state (Optional[list[FileMetadata]], optional): Remote state of the datasite.
                If not provided, it will be fetched from the server. Defaults to None.
        """
        self.client: Client = client
        self.email: str = email
        self.remote_state: Optional[list[FileMetadata]] = remote_state

    def __repr__(self) -> str:
        return f"DatasiteState<{self.email}>"

    @property
    def path(self) -> Path:
        p = Path(self.client.sync_folder) / self.email
        return p.expanduser().resolve()

    def get_current_local_state(self) -> list[FileMetadata]:
        return hash_dir(self.path, root_dir=self.client.sync_folder)

    def get_remote_state(self) -> list[FileMetadata]:
        if self.remote_state is None:
            self.remote_state = get_remote_state(
                self.client.server_client, email=self.client.email, path=Path(self.email)
            )
        return self.remote_state

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
                change_info = compare_fileinfo(self.client.sync_folder, afile, local_info, remote_info)
            except Exception as e:
                logger.exception(f"Failed to compare file {afile}. Reason: {e}")
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
        if SyftPermission.is_permission_file(change.path):
            permissions.append(change)
        else:
            files.append(change)
    return permissions, files


def compare_fileinfo(
    local_sync_folder: Path,
    path: Path,
    local_info: Optional[FileMetadata],
    remote_info: Optional[FileMetadata],
) -> Optional[FileChangeInfo]:
    if local_info is None and remote_info is None:
        return

    if local_info is None and remote_info is not None:
        # File only exists on remote
        return FileChangeInfo(
            local_sync_folder=local_sync_folder,
            path=path,
            side_last_modified=SyncSide.REMOTE,
            date_last_modified=remote_info.last_modified,
            file_size=remote_info.file_size,
        )

    if remote_info is None and local_info is not None:
        # File only exists on local
        return FileChangeInfo(
            local_sync_folder=local_sync_folder,
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
            local_sync_folder=local_sync_folder,
            path=path,
            side_last_modified=side_last_modified,
            date_last_modified=date_last_modified,
            file_size=file_size,
        )
