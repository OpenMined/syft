import datetime
import random

import faker
from textual.containers import Horizontal
from textual.widgets import Label, ListItem, ListView, RichLog, Static


def generate_random_loguru_logs(app: str, num_lines: int) -> str:
    now = datetime.datetime.now()
    times = [now - datetime.timedelta(seconds=i) for i in range(num_lines)]
    log_levels = ["INFO", "WARNING"]
    messages = []
    for time in times:
        log_level = random.choice(log_levels)
        message = faker.Faker().sentence()
        messages.append(f"{time} | {log_level} | {app.upper()}: {message}")
    return "\n".join(messages)


class APIWidget(Static):
    APPS = ["Inbox", "Ring", "Broadcast", "FL_client"]

    def compose(self):
        with Horizontal():
            list_view = ListView(*[ListItem(Label(app), id=app) for app in self.APPS])
            list_view.styles.width = "20%"
            yield list_view

            self.log_viewer = RichLog(markup=True, wrap=False)
            self.log_viewer.styles.width = "80%"
            self.log_viewer.write(self._format_logs(self.get_logs(self.APPS[0])), scroll_end=True)
            yield self.log_viewer

    def get_logs(self, app_name: str) -> str:
        return generate_random_loguru_logs(app_name, random.randint(500, 1000))

    def _format_logs(self, logs: str) -> str:
        formatted = []
        for line in logs.splitlines():
            timestamp, level, message = line.split(" | ")
            color = "yellow" if level == "WARNING" else "blue"
            formatted.append(f"[green][dim]{timestamp}[/green][/dim] | [{color}]{level:7}[/{color}] | {message}")
        return "\n".join(formatted)

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        app_name = event.item.id
        self.log_viewer.clear()
        self.log_viewer.write(self._format_logs(self.get_logs(app_name)), scroll_end=True)
        self.log_viewer.scroll_end()
