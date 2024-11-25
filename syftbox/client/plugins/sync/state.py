import threading
from datetime import datetime, timezone
from enum import Enum, auto
from pathlib import Path
from typing import Optional

from loguru import logger
from pydantic import BaseModel, Field

from syftbox.client.plugins.sync.exceptions import SyncEnvironmentError
from syftbox.server.sync.models import FileMetadata


class SyncStatus(Enum):
    QUEUED = auto()
    IN_PROGRESS = auto()
    SYNCED = auto()
    ERROR = auto()
    REJECTED = auto()
    IGNORED = auto()


class SyncStatusInfo(BaseModel):
    path: Path
    time: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))
    status: SyncStatus
    message: Optional[str] = None


class LocalState(BaseModel):
    file_path: Path = Field(description="Path to the LocalState file", exclude=True)
    # The state of files on last successful sync
    states: dict[Path, FileMetadata] = {}
    # The status of files on last sync
    status_info: dict[Path, SyncStatusInfo] = {}

    def insert_synced_file(self, path: Path, state: FileMetadata):
        if not isinstance(path, Path):
            raise ValueError(f"path must be a Path object, got {path}")
        if not self.file_path.is_file():
            # If the LocalState file does not exist, the sync environment is corrupted and syncing should be aborted

            # NOTE: this can occur when the user deletes the sync folder, but a different plugin re-creates it.
            # If the sync folder exists but the LocalState file does not, it means the sync folder was deleted
            # during syncing and might cause unexpected behavior like deleting files on the remote
            raise SyncEnvironmentError("Your previous sync state has been deleted by a different process.")

        if state is None:
            self.states.pop(path, None)
        else:
            self.states[path] = state

        self.insert_status_info(path, SyncStatus.SYNCED)
        self.save()

    def insert_status_info(self, path: Path, status: SyncStatus, message: Optional[str] = None):
        if not isinstance(path, Path):
            raise ValueError(f"path must be a Path object, got {path}")
        self.status_info[path] = SyncStatusInfo(path=path, time=datetime.now(), status=status, message=message)
        self.save()

    def save(self):
        try:
            with threading.Lock():
                self.file_path.write_text(self.model_dump_json())
        except Exception:
            logger.exception(f"Failed to save {self.file_path}")

    def load(self):
        with threading.Lock():
            if self.file_path.exists():
                data = self.file_path.read_text()
                loaded_state = self.model_validate_json(data)
                self.states = loaded_state.states
            else:
                # Ensure the file exists for the next save
                self.save()
