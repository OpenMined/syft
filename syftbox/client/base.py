from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import httpx
from typing_extensions import Protocol

from syftbox.lib.client_config import SyftClientConfig
from syftbox.lib.workspace import SyftWorkspace


class Plugins(Protocol):
    """All initialized plugins."""

    if TYPE_CHECKING:
        from syftbox.client.plugins.apps import AppRunner
        from syftbox.client.plugins.sync.manager import SyncManager

    @property
    def sync_manager(self) -> SyncManager:
        """SyncManager instance for managing synchronization tasks."""
        ...

    @property
    def app_runner(self) -> AppRunner:
        """AppRunner instance for managing application execution."""
        ...


class SyftClientInterface(Protocol):
    """
    Protocol defining the essential attributes required by SyftClient plugins/components.

    This interface serves two main purposes:
    1. Prevents circular dependencies by providing a minimal interface that
       plugins/components can import and type hint against, instead of importing
       the full SyftClient class.
    2. Enables dependency injection by defining a contract that any context
       or mock implementation can fulfill for testing or modular configuration.

    Attributes:
        config: Configuration settings for the Syft client
        workspace: Workspace instance managing data and computation
        server_client: HTTP client for server communication
    """

    config: SyftClientConfig
    """Configuration settings for the Syft client."""

    workspace: SyftWorkspace
    """Paths to different dirs in Syft"""

    plugins: Plugins
    """All initialized plugins."""

    server_client: httpx.Client
    """HTTP client for server communication."""

    @property
    def email(self) -> str:
        """Email address of the current user."""
        ...

    @property
    def datasite(self) -> Path:
        """Path to the datasite directory for the current user."""
        ...  # pragma: no cover

    @property
    def all_datasites(self) -> list[str]:
        """Path to the datasite directory for the current user."""
        ...  # pragma: no cover

    def log_analytics_event(self, event_name: str, **kwargs) -> None:
        """Log an analytics event to the server."""
        ...  # pragma: no cover

    def whoami(self) -> str:
        """Get the email address of the current user from the server."""
        ...  # pragma: no cover
