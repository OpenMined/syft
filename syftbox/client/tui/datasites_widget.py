from pathlib import Path
from typing import List

from textual.containers import Container
from textual.suggester import Suggester, SuggestFromList
from textual.widgets import DirectoryTree, Input, Label, Static


class DatasiteSuggester(Suggester):
    def __init__(self, *, base_path: Path, use_cache=True, case_sensitive=False):
        super().__init__(use_cache=use_cache, case_sensitive=case_sensitive)
        self.base_path = base_path

    async def get_suggestion(self, value: str) -> None:
        paths = [p.name for p in self.base_path.iterdir() if p.is_dir()]
        return await SuggestFromList(
            paths,
            case_sensitive=self.case_sensitive,
        ).get_suggestion(value)


class DatasiteSelector(Static):
    def __init__(self, base_path: Path, default_datasite: str) -> None:
        super().__init__()
        self.base_path = base_path.expanduser()
        self.default_datasite = default_datasite
        self.current_datasite = self.base_path / default_datasite

    def compose(self):
        yield Label("Search Datasite:")
        path_input = Input(
            value=self.default_datasite,
            placeholder="Enter datasite path...",
            suggester=DatasiteSuggester(base_path=self.base_path),
        )
        path_input.styles.width = "100%"
        yield path_input

        yield Static("", classes="spacer")  # Spacer with vertical margin

        self.files_container = Container()
        with self.files_container:
            yield Label("Files:")
            yield DirectoryTree(str(self.current_datasite))

        self.error_message = Static("", classes="error")
        self.error_message.visible = False
        yield self.error_message

    def _get_available_datasites(self) -> List[str]:
        return [p.name for p in self.base_path.iterdir() if p.is_dir()]

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.current_datasite = self.base_path / event.value
        if not self.current_datasite.exists():
            self.error_message.update(f"[red]Datasite '{event.value}' does not exist[/red]")
            self.error_message.visible = True
            self.files_container.visible = False
        else:
            self.error_message.visible = False
            self.files_container.visible = True
            self.query_one(DirectoryTree).path = str(self.current_datasite)

    CSS = """
    .spacer {
        height: 1;
    }
    """
