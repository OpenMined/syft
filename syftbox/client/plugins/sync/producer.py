from pathlib import Path

from loguru import logger

from syftbox.client.base import SyftClientInterface
from syftbox.client.plugins.sync.endpoints import get_datasite_states
from syftbox.client.plugins.sync.queue import SyncQueue, SyncQueueItem
from syftbox.client.plugins.sync.state import LocalState, SyncStatus
from syftbox.client.plugins.sync.sync import DatasiteState, FileChangeInfo


class SyncProducer:
    def __init__(self, client: SyftClientInterface, queue: SyncQueue, local_state: LocalState):
        self.client = client
        self.queue = queue
        self.local_state = local_state

    def get_datasite_states(self) -> list[DatasiteState]:
        try:
            remote_datasite_states = get_datasite_states(self.client.server_client, email=self.client.email)
        except Exception as e:
            logger.error(f"Failed to retrieve datasites from server, only syncing own datasite. Reason: {e}")
            remote_datasite_states = {}

        # Ensure we are always syncing own datasite
        if self.client.email not in remote_datasite_states:
            remote_datasite_states[self.client.email] = []

        datasite_states = [
            DatasiteState(self.client, email, remote_state=remote_state)
            for email, remote_state in remote_datasite_states.items()
        ]
        return datasite_states

    def add_ignored_to_local_state(self, ignored_paths: list[Path]) -> None:
        for path in ignored_paths:
            prev_status_info = self.local_state.status_info.get(path, None)
            # Only add to local state if it's not already ignored previously
            is_ignored_previously = prev_status_info is not None and prev_status_info.status == SyncStatus.IGNORED
            if not is_ignored_previously:
                self.local_state.insert_status_info(path, SyncStatus.IGNORED)

    def enqueue_datasite_changes(self, datasite: DatasiteState):
        """
        Enqueue all out of sync files for the datasite,
        and track the ignored files in the local state.
        """
        try:
            out_of_sync_files = datasite.get_out_of_sync_files()

            if len(out_of_sync_files.permissions) or len(out_of_sync_files.files):
                logger.debug(
                    f"Enqueuing {len(out_of_sync_files.permissions)} permissions and {len(out_of_sync_files.files)} files for {datasite.email}"
                )
        except Exception as e:
            logger.error(f"Failed to get out of sync files for {datasite.email}. Reason: {e}")
            return

        for change in out_of_sync_files.permissions + out_of_sync_files.files:
            self.enqueue(change)

        self.add_ignored_to_local_state(out_of_sync_files.ignored)

    def enqueue(self, change: FileChangeInfo) -> None:
        self.queue.put(SyncQueueItem(priority=change.get_priority(), data=change))
