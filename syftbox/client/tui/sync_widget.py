from typing import List

from textual.binding import Binding
from textual.widgets import DataTable, Input, Static

from syftbox.client.base import SyftBoxContextInterface
from syftbox.client.plugins.sync.local_state import SyncStatusInfo
from syftbox.client.routers.sync_router import get_status_info


def get_sync_status_info(context: SyftBoxContextInterface, path_glob: str | None = None) -> List[SyncStatusInfo]:
    return get_status_info(
        path_glob=path_glob,
        sync_manager=context.plugins.sync_manager,
    )


class SyncWidget(Static):
    BINDINGS = [
        Binding("f", "focus_search", "Search", show=True),
    ]

    def __init__(self, context: SyftBoxContextInterface) -> None:
        super().__init__()
        self.context = context

    def compose(self):
        yield Input(placeholder="Filter paths (glob pattern)...", id="path_filter")

        self.table = DataTable()
        self.table.add_columns("Path", "Status", "Action", "Last Update", "Message")
        yield self.table

        # Move initial refresh to on_mount

    def on_mount(self) -> None:
        self._refresh_table()

    def _refresh_table(self, path_filter: str | None = None) -> None:
        self.table.clear()

        status_info = get_sync_status_info(self.context, path_filter)
        for info in status_info:
            self.table.add_row(
                str(info.path),
                info.status.value,
                info.action.value if info.action else "",
                info.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                info.message or "",
            )

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "path_filter":
            self._refresh_table(event.value)

    def action_focus_search(self) -> None:
        self.query_one(Input).focus()
