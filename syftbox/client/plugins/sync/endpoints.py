import base64
from pathlib import Path
from typing import Any

import httpx

from syftbox.server.sync.models import ApplyDiffResponse, DiffResponse, FileMetadata


class SyftServerError(Exception):
    pass


class SyftNotFound(SyftServerError):
    pass


def handle_json_response(endpoint: str, response: httpx.Response) -> Any:
    # endpoint only needed for error message
    if response.status_code == 200:
        return response.json()

    raise SyftServerError(f"[{endpoint}] call failed: {response.text}")


def list_datasites(client: httpx.Client) -> list[str]:
    response = client.post(
        "/sync/datasites",
    )

    data = handle_json_response("/sync/datasites", response)
    return data


def get_remote_state(client: httpx.Client, email: str, path: Path) -> list[FileMetadata]:
    response = client.post(
        "/sync/dir_state",
        params={
            "dir": str(path),
        },
        headers={"email": email},
    )

    response_data = handle_json_response("/dir_state", response)
    return [FileMetadata(**item) for item in response_data]


def get_metadata(client: httpx.Client, path: Path) -> FileMetadata:
    response = client.post(
        "/sync/get_metadata",
        json={
            "path_like": path.as_posix(),
        },
    )

    response_data = handle_json_response("/sync/get_metadata", response)

    if len(response_data) == 0:
        raise SyftNotFound(f"[/sync/get_metadata] not found on server: {path}")
    return FileMetadata(**response_data[0])


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
