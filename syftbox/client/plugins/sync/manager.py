import time
from threading import Thread
from typing import Optional

from loguru import logger

from syftbox.client.base import SyftClientInterface
from syftbox.client.plugins.sync.consumer import SyncConsumer
from syftbox.client.plugins.sync.endpoints import get_datasite_states
from syftbox.client.plugins.sync.exceptions import FatalSyncError
from syftbox.client.plugins.sync.queue import SyncQueue, SyncQueueItem
from syftbox.client.plugins.sync.sync import DatasiteState, FileChangeInfo


class SyncManager:
    def __init__(self, client: SyftClientInterface):
        self.client = client
        self.queue = SyncQueue()
        self.consumer = SyncConsumer(client=self.client, queue=self.queue)
        self.sync_interval = 1  # seconds
        self.thread: Optional[Thread] = None
        self.is_stop_requested = False
        self.sync_run_once = False

    def is_alive(self) -> bool:
        return self.thread is not None and self.thread.is_alive()

    def stop(self, blocking: bool = False):
        self.is_stop_requested = True
        if blocking:
            self.thread.join()

    def start(self):
        def _start(manager: SyncManager):
            while not manager.is_stop_requested:
                try:
                    manager.run_single_thread()
                    time.sleep(manager.sync_interval)
                except FatalSyncError as e:
                    logger.error(f"Syncing encountered a fatal error: {e}")
                    break

        self.is_stop_requested = False
        t = Thread(target=_start, args=(self,), daemon=True)
        t.start()
        logger.info(f"Sync started, syncing every {self.sync_interval} seconds")
        self.thread = t

    def enqueue(self, change: FileChangeInfo) -> None:
        self.queue.put(SyncQueueItem(priority=change.get_priority(), data=change))

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

    def enqueue_datasite_changes(self, datasite: DatasiteState):
        try:
            permission_changes, file_changes = datasite.get_out_of_sync_files()
            total = len(permission_changes) + len(file_changes)

            if total != 0:
                logger.debug(
                    f"Enqueuing {len(permission_changes)} permissions and {len(file_changes)} files for {datasite.email}"
                )
        except Exception as e:
            logger.error(f"Failed to get out of sync files for {datasite.email}. Reason: {e}")
            permission_changes, file_changes = [], []

        for change in permission_changes + file_changes:
            self.enqueue(change)

    def run_single_thread(self):
        # NOTE first implementation will be unthreaded and just loop through all datasites

        datasite_states = self.get_datasite_states()
        logger.debug(f"Syncing {len(datasite_states)} datasites")

        if not self.sync_run_once:
            # Download all missing files at the start
            self.consumer.download_all_missing(
                datasite_states=datasite_states,
            )

        for datasite_state in datasite_states:
            self.enqueue_datasite_changes(datasite_state)

        # TODO stop consumer if self.is_stop_requested
        self.consumer.consume_all()

        self.sync_run_once = True
