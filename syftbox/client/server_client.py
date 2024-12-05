import httpx

from syftbox.client.base import ClientBase
from syftbox.client.plugins.sync.sync_client import SyncClient


class SyftBoxClient(ClientBase):
    def __init__(self, conn: httpx.Client):
        self.conn = conn

        self.auth = AuthClient(conn)
        self.sync = SyncClient(conn)

    def register(self, email: str) -> str:
        response = self.conn.post("/register", json={"email": email})
        self.raise_for_status()
        return response.json().get("token")

    def info(self) -> dict:
        response = self.conn.get("/info")
        self.raise_for_status(response)
        return response.json()

    def log_analytics_event(self, event_name: str, **kwargs) -> None:
        """Log an event to the server"""
        event_data = {
            "event_name": event_name,
            **kwargs,
        }

        response = self.server_client.post("/log_event", json=event_data)
        self.raise_for_status(response)


class AuthClient(ClientBase):
    def whoami(self):
        response = self.conn.post("/auth/whoami")
        self.raise_for_status(response)
        return response.json()
