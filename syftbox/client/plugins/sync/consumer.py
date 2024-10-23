import hashlib
import threading
from enum import Enum
from pathlib import Path
from typing import Optional

import py_fast_rsync
from loguru import logger
from pydantic import BaseModel, model_validator

from syftbox.client.plugins.sync.endpoints import (
    SyftServerError,
    apply_diff,
    create,
    delete,
    download,
    get_diff,
    get_metadata,
)
from syftbox.client.plugins.sync.queue import SyncQueue, SyncQueueItem
from syftbox.client.plugins.sync.sync import SyncSide
from syftbox.lib.lib import Client
from syftbox.server.sync.hash import hash_file
from syftbox.server.sync.models import FileMetadata


class SyncDecisionType(Enum):
    NOOP = 0
    CREATE = 1
    MODIFY = 2
    DELETE = 3


def update_local(client: Client, local_syncstate: FileMetadata, remote_syncstate: FileMetadata):
    diff = get_diff(client.server_client, local_syncstate.path, remote_syncstate.signature_bytes)
    abs_path = client.sync_folder / local_syncstate.path
    local_data = abs_path.read_bytes()

    new_data = py_fast_rsync.apply(local_data, diff.diff_bytes)
    new_hash = hashlib.sha256(new_data).hexdigest()

    if new_hash != diff.hash:
        # TODO handle
        raise ValueError("hash mismatch")

    # TODO implement safe write with tempfile + rename
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    abs_path.write_bytes(new_data)


def update_remote(client: Client, local_syncstate: FileMetadata, remote_syncstate: FileMetadata):
    abs_path = client.sync_folder / local_syncstate.path
    local_data = abs_path.read_bytes()

    diff = py_fast_rsync.diff(remote_syncstate.signature_bytes, local_data)
    apply_diff(client.server_client, local_syncstate.path, diff, local_syncstate.hash)


def delete_local(client: Client, remote_syncstate: FileMetadata):
    abs_path = client.sync_folder / remote_syncstate.path
    abs_path.unlink()


def delete_remote(client: Client, local_syncstate: FileMetadata):
    delete(client.server_client, local_syncstate.path)


def create_local(client: Client, remote_syncstate: FileMetadata):
    abs_path = client.sync_folder / remote_syncstate.path
    content_bytes = download(client.server_client, remote_syncstate.path)
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    abs_path.write_bytes(content_bytes)


def create_remote(client: Client, local_syncstate: FileMetadata):
    abs_path = client.sync_folder / local_syncstate.path
    data = abs_path.read_bytes()
    create(client.server_client, local_syncstate.path, data)


class SyncDecision(BaseModel):
    operation: SyncDecisionType
    side_to_update: SyncSide
    local_syncstate: Optional[FileMetadata]
    remote_syncstate: Optional[FileMetadata]

    def execute(self, client: Client):
        if self.operation == SyncDecisionType.NOOP:
            return

        to_local = self.side_to_update == SyncSide.LOCAL
        to_remote = self.side_to_update == SyncSide.REMOTE

        if self.operation == SyncDecisionType.CREATE and to_remote:
            create_remote(client, self.local_syncstate)
        elif self.operation == SyncDecisionType.CREATE and to_local:
            create_local(client, self.remote_syncstate)
        elif self.operation == SyncDecisionType.DELETE and to_remote:
            delete_remote(client, self.remote_syncstate)
        elif self.operation == SyncDecisionType.DELETE and to_local:
            delete_local(client, self.local_syncstate)
        elif self.operation == SyncDecisionType.MODIFY and to_remote:
            update_remote(client, self.local_syncstate, self.remote_syncstate)
        elif self.operation == SyncDecisionType.MODIFY and to_local:
            update_local(client, self.local_syncstate, self.remote_syncstate)

    @classmethod
    def noop(
        cls,
        local_syncstate: FileMetadata,
        remote_syncstate: FileMetadata,
    ):
        return cls(
            operation=SyncDecisionType.NOOP,
            side_to_update=SyncSide.LOCAL,
            local_syncstate=local_syncstate,
            remote_syncstate=remote_syncstate,
        )

    @classmethod
    def from_modified_states(
        cls,
        local_syncstate: Optional[FileMetadata],
        remote_syncstate: Optional[FileMetadata],
        side_to_update: SyncSide,
    ):
        """Asssumes at least on of the states is modified"""

        delete = (
            side_to_update == SyncSide.REMOTE
            and local_syncstate is None
            or side_to_update == SyncSide.LOCAL
            and remote_syncstate is None
        )

        create = (
            side_to_update == SyncSide.REMOTE
            and remote_syncstate is None
            or side_to_update == SyncSide.LOCAL
            and local_syncstate is None
        )

        if delete:
            operation = SyncDecisionType.DELETE
        elif create:
            operation = SyncDecisionType.CREATE
        else:
            operation = SyncDecisionType.MODIFY

        return cls(
            operation=operation,
            side_to_update=side_to_update,
            local_syncstate=local_syncstate,
            remote_syncstate=remote_syncstate,
        )


class SyncDecisionTuple(BaseModel):
    remote_decision: SyncDecision
    local_decision: SyncDecision

    @property
    def result_local_state(self):
        if self.local_decision.operation == SyncDecisionType.NOOP:
            return self.local_decision.local_syncstate
        else:
            return self.local_decision.remote_syncstate

    @classmethod
    def from_states(
        cls,
        current_local_syncstate: Optional[FileMetadata],
        previous_local_syncstate: Optional[FileMetadata],
        current_remote_syncstate: Optional[FileMetadata],
    ):
        def noop() -> SyncDecision:
            return SyncDecision.noop(
                local_syncstate=current_local_syncstate,
                remote_syncstate=current_remote_syncstate,
            )

        local_modified = current_local_syncstate != previous_local_syncstate
        remote_modified = previous_local_syncstate != current_remote_syncstate
        in_sync = current_remote_syncstate == current_local_syncstate
        conflict = local_modified and remote_modified and not in_sync

        logger.debug(
            f"local_modified: {local_modified}, remote_modified: {remote_modified}, in_sync: {in_sync}, conflict: {conflict}"
        )

        if in_sync:
            return cls(
                remote_decision=noop(),
                local_decision=noop(),
            )
        elif conflict:
            # in case of conflict we always use the server state, because it was updated earlier
            remote_decision = noop()
            # we apply the server state locally
            local_decision = SyncDecision.from_modified_states(
                local_syncstate=current_local_syncstate,
                remote_syncstate=current_remote_syncstate,
                side_to_update=SyncSide.LOCAL,
            )
            return cls(remote_decision=remote_decision, local_decision=local_decision)
        else:
            # here we can assume only one party changed
            # assert (local_modified and not server_modified) or (server_modified and not local_modified)
            if local_modified:
                return cls(
                    local_decision=noop(),
                    remote_decision=SyncDecision.from_modified_states(
                        local_syncstate=current_local_syncstate,
                        remote_syncstate=current_remote_syncstate,
                        side_to_update=SyncSide.REMOTE,
                    ),
                )
            else:
                return cls(
                    local_decision=SyncDecision.from_modified_states(
                        local_syncstate=current_local_syncstate,
                        remote_syncstate=current_remote_syncstate,
                        side_to_update=SyncSide.LOCAL,
                    ),
                    remote_decision=noop(),
                )


class LocalState(BaseModel):
    path: Path
    states: dict[Path, FileMetadata] = {}

    @model_validator(mode="after")
    def init_dir(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        return self

    def insert(self, path: Path, state: FileMetadata):
        if state is None:
            self.states.pop(path, None)
        else:
            self.states[path] = state
        self.save()

    def save(self):
        with threading.Lock():
            self.path.write_text(self.model_dump_json())

    def load(self):
        with threading.Lock():
            if self.path.exists():
                data = self.path.read_text()
                loaded_state = self.model_validate_json(data)
                self.states = loaded_state.states


class SyncConsumer:
    def __init__(self, client: Client, queue: SyncQueue):
        self.client = client
        self.queue = queue
        self.previous_state = LocalState(path=Path(client.sync_folder) / ".syft" / "local_syncstate.json")
        self.previous_state.load()

    def consume_all(self):
        while not self.queue.empty():
            item = self.queue.get(timeout=0.1)
            try:
                self.process_filechange(item)
            except Exception:
                logger.exception(f"Failed to sync file {item.data.path}")

    def get_decisions(self, item: SyncQueueItem) -> SyncDecisionTuple:
        path = item.data.path
        current_local_syncstate: FileMetadata = self.get_current_local_syncstate(path)
        previous_local_syncstate = self.get_previous_local_syncstate(path)
        # TODO, rename to remote
        current_server_state = self.get_current_server_state(path)

        local_hash = current_local_syncstate.hash if current_local_syncstate else None
        server_hash = current_server_state.hash if current_server_state else None
        previous_local_hash = previous_local_syncstate.hash if previous_local_syncstate else None

        logger.debug(
            f"Processing {path} with local hash {local_hash}, server hash {server_hash}, previous local hash {previous_local_hash}"
        )

        return SyncDecisionTuple.from_states(current_local_syncstate, previous_local_syncstate, current_server_state)

    def process_decision(self, path: Path, decision: SyncDecisionTuple):
        decision.remote_decision.execute(self.client)
        decision.local_decision.execute(self.client)
        logger.debug(f"Saving state for {path}, {decision.result_local_state}")

        self.previous_state.insert(path=path, state=decision.result_local_state)

    def process_filechange(self, item: SyncQueueItem) -> None:
        decisions = self.get_decisions(item)
        logger.debug(
            f"Processing {item.data.path} with decisions {decisions.local_decision.operation}, {decisions.remote_decision.operation}"
        )
        self.process_decision(item.data.path, decisions)

    def get_current_local_syncstate(self, path: Path) -> Optional[FileMetadata]:
        abs_path = self.client.sync_folder / path
        if not abs_path.is_file():
            return None
        return hash_file(abs_path, root_dir=self.client.sync_folder)

    def get_previous_local_syncstate(self, path: Path) -> Optional[FileMetadata]:
        return self.previous_state.states.get(path, None)

    def get_current_server_state(self, path: Path) -> Optional[FileMetadata]:
        try:
            return get_metadata(self.client.server_client, path)
        except SyftServerError:
            return None
