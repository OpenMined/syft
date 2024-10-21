from pathlib import Path
from typing import Callable, TypeAlias

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

__all__ = [
    "FSWatchdog",
    "AnyFileSystemEventHandler",
    "FSEventCallbacks",
    "FileSystemEvent",
]

FSEventCallbacks: TypeAlias = list[Callable[[FileSystemEvent], None]]


class FSWatchdog:
    def __init__(self, watch_dir: Path, event_handler: FileSystemEventHandler):
        self.watch_dir = watch_dir
        self.event_handler = event_handler
        self._observer = Observer()

    def start(self):
        # observer starts it's own thread
        self._observer.schedule(
            self.event_handler,
            self.watch_dir,
            recursive=True,
        )
        self._observer.start()

    def stop(self):
        self._observer.stop()
        self._observer.join()


class AnyFileSystemEventHandler(FileSystemEventHandler):
    def __init__(
        self,
        watch_dir: Path,
        callbacks: FSEventCallbacks,
        ignored: list[str] = [],
    ):
        self.watch_dir = watch_dir
        self.callbacks = callbacks
        self.ignored = [Path(self.watch_dir, ignore) for ignore in ignored]

    def on_any_event(self, event: FileSystemEvent) -> None:
        for ignore in self.ignored:
            if event.src_path.startswith(str(ignore)):
                return

        for cb in self.callbacks:
            cb(event)
