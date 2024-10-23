import threading
from dataclasses import dataclass
from queue import PriorityQueue
from typing import Optional

from syftbox.client.plugins.sync.sync import FileChangeInfo


@dataclass(order=True)
class SyncQueueItem:
    priority: int
    data: FileChangeInfo


class SyncQueue:
    """
    A thread-safe priority queue that supports deduplication based on the data field.

    Adding an item to the queue that already exists will be ignored, even if the priority is different.
    """

    def __init__(self, maxsize: int = 0):
        self.queue = PriorityQueue(maxsize=maxsize)
        self.dedupe_set = set()

        # Lock is required to make put/get atomic when threading is used
        self.lock = threading.Lock()

    def put(self, item: SyncQueueItem, block: bool = False, timeout: Optional[float] = None) -> None:
        with self.lock:
            if item.data not in self.dedupe_set:
                self.queue.put(item, block=block, timeout=timeout)
                self.dedupe_set.add(item.data)

    def get(self, block: bool = False, timeout: Optional[float] = None) -> SyncQueueItem:
        with self.lock:
            item: SyncQueueItem = self.queue.get(block=block, timeout=timeout)
            self.dedupe_set.discard(item.data)
            return item

    def empty(self) -> bool:
        return self.queue.empty()
