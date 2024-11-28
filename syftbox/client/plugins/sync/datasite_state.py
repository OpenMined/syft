from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from loguru import logger

from syftbox.client.base import SyftClientInterface
from syftbox.client.plugins.sync.endpoints import get_remote_state
from syftbox.client.plugins.sync.types import FileChangeInfo, SyncSide
from syftbox.lib.ignore import filter_ignored_paths
from syftbox.lib.lib import SyftPermission
from syftbox.server.sync.hash import collect_files, hash_dir
from syftbox.server.sync.models import FileMetadata


def format_paths(path_list: list[Path]) -> str:
    tree = ""
    folders_seen = set()

    for p in path_list:
        parts = p.parts
        for i in range(len(parts)):
            current_path = "/".join(parts[: i + 1])
            if current_path not in folders_seen:
                depth = i
                name = parts[i]
                is_file = i == len(parts) - 1
                prefix = "  " * depth + "├── "

                if is_file:
                    tree += f"{prefix}{name}\n"
                else:
                    tree += f"{prefix}{name}/\n"
                folders_seen.add(current_path)

    return tree


@dataclass
class DatasiteChanges:
    permissions: list[FileChangeInfo]
    files: list[FileChangeInfo]


class DatasiteState:
    def __init__(
        self, client: SyftClientInterface, email: str, remote_state: Optional[list[FileMetadata]] = None
    ) -> None:
        """A class to represent the state of a datasite

        Args:
            ctx (SyftClientInterface): Context of the syft client
            email (str): Email of the datasite
            remote_state (Optional[list[FileMetadata]], optional): Remote state of the datasite.
                If not provided, it will be fetched from the server. Defaults to None.
        """
        self.client: SyftClientInterface = client
        self.email: str = email
        self.remote_state: Optional[list[FileMetadata]] = remote_state

    def __repr__(self) -> str:
        return f"DatasiteState<{self.email}>"

    def tree_repr(self) -> str:
        remote_state = self.remote_state or []
        rel_paths = sorted([file.path for file in remote_state])
        path_str = format_paths(rel_paths)
        return f"""DatasiteState:
{path_str}
        """

    @property
    def path(self) -> Path:
        p = self.client.workspace.datasites / self.email
        return p.expanduser().resolve()

    def get_current_local_state(self) -> list[FileMetadata]:
        return hash_dir(self.path, root_dir=self.client.workspace.datasites)

    def get_remote_state(self) -> list[FileMetadata]:
        if self.remote_state is None:
            self.remote_state = get_remote_state(self.client.server_client, path=Path(self.email))
        return self.remote_state

    def is_in_sync(self) -> bool:
        changes = self.get_datasite_changes()
        return len(changes.files) == 0 and len(changes.permissions) == 0

    def get_ignored_local_files(self, include_hidden: bool = True, include_symlinks: bool = True) -> set[Path]:
        all_paths = collect_files(self.path)
        relative_paths = [file.relative_to(self.client.workspace.datasites) for file in all_paths]
        filtered_paths = filter_ignored_paths(
            datasites_dir=self.client.workspace.datasites,
            relative_paths=relative_paths,
            ignore_hidden_files=include_hidden,
            ignore_symlinks=include_symlinks,
        )

        return set(relative_paths) - set(filtered_paths)

    def get_datasite_changes(
        self,
    ) -> DatasiteChanges:
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
        all_files_filtered = filter_ignored_paths(
            datasites_dir=self.client.workspace.datasites,
            relative_paths=list(all_files),
            ignore_hidden_files=True,
            ignore_symlinks=True,
        )

        all_changes = []
        for afile in all_files_filtered:
            local_info = local_state_dict.get(afile)
            remote_info = remote_state_dict.get(afile)

            try:
                change_info = compare_fileinfo(self.client.workspace.datasites, afile, local_info, remote_info)
            except Exception as e:
                logger.error(
                    f"Failed to compare file {afile.as_posix()}, it will be retried in the next sync. Reason: {e}"
                )
                continue

            if change_info is not None:
                all_changes.append(change_info)

        permission_changes, file_changes = split_permissions(all_changes)
        return DatasiteChanges(
            permissions=permission_changes,
            files=file_changes,
        )


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