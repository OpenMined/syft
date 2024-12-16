from pathlib import Path

import textual
from rich import print as rprint
from textual.app import App
from textual.widgets import Footer, Header, MarkdownViewer, TabbedContent
from typer import Exit

from syftbox.client.base import SyftBoxContextInterface
from syftbox.client.core import SyftBoxRunner
from syftbox.client.tui.api_widget import APIWidget
from syftbox.client.tui.datasites_widget import DatasiteSelector
from syftbox.client.tui.home_widget import intro_md
from syftbox.client.tui.sync_widget import SyncWidget
from syftbox.lib.client_config import SyftClientConfig
from syftbox.lib.exceptions import ClientConfigException


class SyftBoxTUI(App):
    BINDINGS = [("d", "toggle_dark", "Toggle dark mode")]

    def __init__(
        self,
        syftbox_context: SyftBoxContextInterface,
        driver_class=None,
        css_path=None,
        watch_css=False,
        ansi_color=False,
    ):
        self.syftbox_context = syftbox_context
        super().__init__(driver_class, css_path, watch_css, ansi_color)

    def action_toggle_dark(self) -> None:
        """An action to toggle dark mode."""
        self.theme = "textual-dark" if self.theme == "textual-light" else "textual-light"

    def on_mount(self) -> None:
        self.title = "SyftBox"

    def compose(self):
        yield Header(name="SyftBox")
        with TabbedContent("Home", "Datasites", "APIs", "Sync", "Settings"):
            yield MarkdownViewer(intro_md)
            yield DatasiteSelector(
                base_path=self.syftbox_context.workspace.datasites,
                default_datasite=self.syftbox_context.email,
            )
            yield APIWidget()
            yield SyncWidget(self.syftbox_context)
            yield SettingsWidget()
        yield Footer()


class SettingsWidget(textual.widgets.TextArea):
    def on_mount(self) -> None:
        self.text = "Settings"


def get_syftbox_context(config_path: Path) -> SyftBoxContextInterface:
    try:
        conf = SyftClientConfig.load(config_path)
        context = SyftBoxRunner(conf).context
        return context
    except ClientConfigException:
        msg = (
            f"[bold red]Error:[/bold red] Couldn't load config at: [yellow]'{config_path}'[/yellow]\n"
            "Please ensure that:\n"
            "  - The configuration file exists at the specified path.\n"
            "  - You've run the SyftBox atleast once.\n"
            f"  - For custom configs, provide the proper path using [cyan]--config[/cyan] flag"
        )
        rprint(msg)
        raise Exit(1)
    except Exception as e:
        rprint(f"[bold red]Error:[/bold red] {e}")
        raise Exit(1)


if __name__ == "__main__":
    context = get_syftbox_context(Path("~/.syftbox/config.json").expanduser())
    app = SyftBoxTUI(syftbox_context=context)
    app.run()
