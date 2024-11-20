import base64
from pathlib import Path
from typing import Any

import httpx

from syftbox.client.exceptions import SyftServerError
from syftbox.server.sync.models import ApplyDiffResponse, DiffResponse, FileMetadata


class SyftNotFound(SyftServerError):
    pass


def handle_json_response(endpoint: str, response: httpx.Response) -> Any:
    # endpoint only needed for error message
    if response.status_code == 200:
        return response.json()

    raise SyftServerError(f"[{endpoint}] call failed: {response.text}")


def get_access_token(client: httpx.Client, email: str) -> str:
    """Only for development purposes, should not be used in production"""
    response = client.post("/auth/request_email_token", json={"email": email})
    email_token = response.json()["email_token"]
    response = client.post("/auth/validate_email_token", headers={"Authorization": f"Bearer {email_token}"})
    return response.json()["access_token"]


def get_datasite_states(client: httpx.Client, email: str) -> dict[str, list[FileMetadata]]:
    response = client.post(
        "/sync/datasite_states",
    )

    data = handle_json_response("/sync/datasite_states", response)

    return {email: [FileMetadata(**item) for item in metadata_list] for email, metadata_list in data.items()}


def get_remote_state(client: httpx.Client, path: Path) -> list[FileMetadata]:
    response = client.post(
        "/sync/dir_state",
        params={
            "dir": str(path),
        },
    )

    response_data = handle_json_response("/dir_state", response)
    metadata_list = [FileMetadata(**item) for item in response_data]
    for item in metadata_list:
        if not hasattr(client, "metadata_cache"):
            client.metadata_cache = {}
        client.metadata_cache[item.path] = item
    return metadata_list


def get_metadata(client: httpx.Client, path: Path) -> FileMetadata:
    if hasattr(client, "metadata_cache") and path in client.metadata_cache:
        return client.metadata_cache[path]
    response = client.post(
        "/sync/get_metadata",
        json={
            "path_like": path.as_posix(),
        },
    )

    response_data = handle_json_response("/sync/get_metadata", response)

    return FileMetadata(**response_data)


def get_diff(client: httpx.Client, path: Path, signature: bytes) -> DiffResponse:
    response = client.post(
        "/sync/get_diff",
        json={
            "path": str(path),
            "signature": base64.b85encode(signature).decode("utf-8"),
        },
    )

    response_data = handle_json_response("/sync/get_diff", response)
    return DiffResponse(**response_data)


def apply_diff(client: httpx.Client, path: Path, diff: bytes, expected_hash: str) -> ApplyDiffResponse:
    response = client.post(
        "/sync/apply_diff",
        json={
            "path": str(path),
            "diff": base64.b85encode(diff).decode("utf-8"),
            "expected_hash": expected_hash,
        },
    )

    response_data = handle_json_response("/sync/apply_diff", response)
    return ApplyDiffResponse(**response_data)


def delete(client: httpx.Client, path: Path) -> None:
    response = client.post(
        "/sync/delete",
        json={
            "path": str(path),
        },
    )

    response.raise_for_status()


def create(client: httpx.Client, path: Path, data: bytes) -> None:
    response = client.post("/sync/create", files={"file": (str(path), data, "text/plain")})
    response = handle_json_response("/sync/create", response)
    return


def download(client: httpx.Client, path: Path) -> bytes:
    response = client.post(
        "/sync/download",
        json={
            "path": str(path),
        },
    )

    if response.status_code != 200:
        raise SyftNotFound(f"[/sync/download] not found on server: {path}, {response.text}")

    return response.content


def download_bulk(client: httpx.Client, paths: list[str]) -> bytes:
    response = client.post(
        "/sync/download_bulk",
        json={"paths": paths},
        timeout=30,
    )
    response.raise_for_status()
    return response.content
