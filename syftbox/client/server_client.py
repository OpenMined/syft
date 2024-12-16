import base64
from pathlib import Path
from typing import Any, Union

import httpx

from syftbox.client.base import ClientBase

# TODO move shared models to lib/models
from syftbox.server.models.sync_models import ApplyDiffResponse, DiffResponse, FileMetadata


class SyftBoxClient(ClientBase):
    def __init__(self, conn: httpx.Client):
        super().__init__(conn)

        self.auth = AuthClient(conn)
        self.sync = SyncClient(conn)

    def register(self, email: str) -> str:
        response = self.conn.post("/register", json={"email": email})
        self.raise_for_status(response)
        return response.json().get("token")

    def info(self) -> dict:
        response = self.conn.get("/info")
        self.raise_for_status(response)
        return response.json()

    def log_analytics_event(self, event_name: str, **kwargs: dict) -> None:
        """Log an event to the server"""
        event_data = {
            "event_name": event_name,
            **kwargs,
        }

        response = self.conn.post("/log_event", json=event_data)
        self.raise_for_status(response)


class AuthClient(ClientBase):
    def whoami(self) -> Any:
        response = self.conn.post("/auth/whoami")
        self.raise_for_status(response)
        return response.json()


class SyncClient(ClientBase):
    def get_datasite_states(self) -> dict[str, list[FileMetadata]]:
        response = self.conn.post("/sync/datasite_states")
        self.raise_for_status(response)
        data = response.json()

        result = {}
        for email, metadata_list in data.items():
            result[email] = [FileMetadata(**item) for item in metadata_list]

        return result

    def get_remote_state(self, relative_path: Path) -> list[FileMetadata]:
        response = self.conn.post(
            "/sync/dir_state",
            params={"dir": relative_path.as_posix()},
        )
        self.raise_for_status(response)
        data = response.json()
        return [FileMetadata(**item) for item in data]

    def get_metadata(self, path: Path) -> FileMetadata:
        response = self.conn.post(
            "/sync/get_metadata",
            json={"path": path.as_posix()},
        )
        self.raise_for_status(response)
        return FileMetadata(**response.json())

    def get_diff(self, relative_path: Path, signature: Union[str, bytes]) -> DiffResponse:
        """Get rsync-style diff between local and remote file.

        Args:
            relative_path: Path to file relative to workspace root
            signature: b85 encoded signature of the local file

        Returns:
            DiffResponse containing the diff and expected hash
        """
        if not isinstance(signature, str):
            signature = base64.b85encode(signature).decode("utf-8")

        response = self.conn.post(
            "/sync/get_diff",
            json={
                "path": relative_path.as_posix(),
                "signature": signature,
            },
        )

        self.raise_for_status(response)
        return DiffResponse(**response.json())

    def apply_diff(self, relative_path: Path, diff: Union[str, bytes], expected_hash: str) -> ApplyDiffResponse:
        """Apply an rsync-style diff to update a remote file.

        Args:
            relative_path: Path to file relative to workspace root
            diff: py_fast_rsync binary diff to apply
            expected_hash: Expected hash of the file after applying diff, used for verification.

        Returns:
            ApplyDiffResponse containing the result of applying the diff
        """
        if not isinstance(diff, str):
            diff = base64.b85encode(diff).decode("utf-8")

        response = self.conn.post(
            "/sync/apply_diff",
            json={
                "path": relative_path.as_posix(),
                "diff": diff,
                "expected_hash": expected_hash,
            },
        )

        self.raise_for_status(response)
        return ApplyDiffResponse(**response.json())

    def delete(self, relative_path: Path) -> None:
        response = self.conn.post(
            "/sync/delete",
            json={"path": relative_path.as_posix()},
        )
        self.raise_for_status(response)

    def create(self, relative_path: Path, data: bytes) -> None:
        response = self.conn.post(
            "/sync/create",
            files={"file": (relative_path.as_posix(), data, "text/plain")},
        )
        self.raise_for_status(response)

    def download(self, relative_path: Path) -> bytes:
        response = self.conn.post(
            "/sync/download",
            json={"path": relative_path.as_posix()},
        )
        self.raise_for_status(response)
        return response.content

    def download_bulk(self, relative_paths: list[Path]) -> bytes:
        paths: list[str] = [path.as_posix() for path in relative_paths]
        response = self.conn.post(
            "/sync/download_bulk",
            json={"paths": paths},
        )
        self.raise_for_status(response)
        return response.content