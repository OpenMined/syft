import time
from threading import Thread

from loguru import logger

from syftbox import Client
from syftbox.client.plugins.sync.consumer import SyncConsumer
from syftbox.client.plugins.sync.endpoints import list_datasites
from syftbox.client.plugins.sync.queue import SyncQueue, SyncQueueItem
from syftbox.client.plugins.sync.sync import DatasiteState, FileChangeInfo


class SyncManager:
    def __init__(self, client: Client):
        self.client = client
        self.queue = SyncQueue()
        self.consumer = SyncConsumer(client=self.client, queue=self.queue)

    def start(self):
        def _start(manager: SyncManager):
            while True:
                manager.run_single_thread()
                time.sleep(1)

        t = Thread(target=_start, args=[self])
        t.start()

    def setup(self):
        self.change_log_folder.mkdir(exist_ok=True)

    def enqueue(self, change: FileChangeInfo) -> None:
        self.queue.put(SyncQueueItem(priority=change.get_priority(), data=change))

    def get_datasites(self) -> list[DatasiteState]:
        try:
            datasite_names = list_datasites(self.client.server_client)
        except Exception as e:
            logger.error(f"Failed to retrieve datasites from server, only syncing own datasite. Reason: {e}")
            datasite_names = []

        # Ensure we are always syncing own datasite
        if self.client.email not in datasite_names:
            datasite_names.append(self.client.email)

        datasites = [DatasiteState(client=self.client, email=email) for email in datasite_names]
        return datasites

    def enqueue_datasite_changes(self, datasite: DatasiteState):
        try:
            permission_changes, file_changes = datasite.get_out_of_sync_files()
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
        self.datasites = self.get_datasites()
        logger.debug(f"Syncing {len(self.datasites)} datasites: {[datasite.email for datasite in self.datasites]}")

        for datasite in self.datasites:
            self.enqueue_datasite_changes(datasite)
            self.consumer.consume_all()
