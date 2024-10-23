import base64
import sqlite3
import tempfile
from pathlib import Path

import py_fast_rsync
from fastapi import APIRouter, Depends, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from syftbox.lib.lib import PermissionTree, filter_metadata
from syftbox.server.settings import ServerSettings, get_server_settings
from syftbox.server.sync.db import (
    delete_file_metadata,
    get_all_datasites,
    get_all_metadata,
    get_db,
    move_with_transaction,
    save_file_metadata,
)
from syftbox.server.sync.hash import hash_file

from .models import (
    ApplyDiffRequest,
    ApplyDiffResponse,
    DiffRequest,
    DiffResponse,
    FileMetadata,
    FileMetadataRequest,
    FileRequest,
)


def get_db_connection(request: Request):
    conn = get_db(request.state.server_settings.file_db_path)
    yield conn
    conn.close()


def get_file_metadata(
    req: FileMetadataRequest,
    conn=Depends(get_db_connection),
) -> list[FileMetadata]:
    # TODO check permissions

    return get_all_metadata(conn, path_like=req.path_like)


router = APIRouter(prefix="/sync", tags=["sync"])


@router.post("/get_diff", response_model=DiffResponse)
def get_diff(
    req: DiffRequest,
    conn: sqlite3.Connection = Depends(get_db_connection),
    server_settings: ServerSettings = Depends(get_server_settings),
) -> DiffResponse:
    metadata_list = get_all_metadata(conn, path_like=f"{req.path}%")
    if len(metadata_list) == 0:
        raise HTTPException(status_code=404, detail="path not found")
    elif len(metadata_list) > 1:
        raise HTTPException(status_code=400, detail="too many files to get diff")

    metadata = metadata_list[0]
    abs_path = server_settings.snapshot_folder / metadata.path
    with open(abs_path, "rb") as f:
        data = f.read()

    diff = py_fast_rsync.diff(req.signature_bytes, data)
    diff_bytes = base64.b85encode(diff).decode("utf-8")
    return DiffResponse(
        path=metadata.path.as_posix(),
        diff=diff_bytes,
        hash=metadata.hash,
    )


@router.post("/dir_state", response_model=list[FileMetadata])
def dir_state(
    dir: Path,
    conn: sqlite3.Connection = Depends(get_db_connection),
    server_settings: ServerSettings = Depends(get_server_settings),
    email: str = Header(),
) -> list[FileMetadata]:
    if dir.is_absolute():
        raise HTTPException(status_code=400, detail="dir must be relative")

    metadata = get_all_metadata(conn, path_like=f"{dir.as_posix()}%")
    full_path = server_settings.snapshot_folder / dir
    # get the top level perm file
    try:
        perm_tree = PermissionTree.from_path(full_path, raise_on_corrupted_files=True)
    except Exception as e:
        print(f"Failed to parse permission tree: {dir}")
        raise e

    # filter the read state for this user by the perm tree
    filtered_metadata = filter_metadata(email, metadata, perm_tree, server_settings.snapshot_folder)
    return filtered_metadata


@router.post("/get_metadata", response_model=list[FileMetadata])
def get_metadata(
    metadata: list[FileMetadata] = Depends(get_file_metadata),
) -> list[FileMetadata]:
    return metadata


@router.post("/apply_diff", response_model=ApplyDiffResponse)
def apply_diffs(
    req: ApplyDiffRequest,
    conn: sqlite3.Connection = Depends(get_db_connection),
    server_settings: ServerSettings = Depends(get_server_settings),
) -> ApplyDiffResponse:
    metadata_list = get_all_metadata(conn, path_like=f"{req.path}%")

    if len(metadata_list) == 0:
        raise HTTPException(status_code=404, detail="path not found")
    elif len(metadata_list) > 1:
        raise HTTPException(status_code=400, detail="found too many files to apply diff")

    metadata = metadata_list[0]

    abs_path = server_settings.snapshot_folder / metadata.path
    with open(abs_path, "rb") as f:
        data = f.read()
    result = py_fast_rsync.apply(data, req.diff_bytes)

    with tempfile.NamedTemporaryFile(delete=False) as temp_file:
        temp_file.write(result)
        temp_path = Path(temp_file.name)

    new_metadata = hash_file(temp_path)

    if new_metadata.hash != req.expected_hash:
        raise HTTPException(status_code=400, detail="expected_hash mismatch")

    # move temp path to real path and update db
    move_with_transaction(conn, metadata=new_metadata, origin_path=abs_path, server_settings=server_settings)

    return ApplyDiffResponse(path=req.path, current_hash=new_metadata.hash, previous_hash=metadata.hash)


@router.post("/delete", response_class=JSONResponse)
def delete_file(
    req: FileRequest,
    conn: sqlite3.Connection = Depends(get_db_connection),
    server_settings: ServerSettings = Depends(get_server_settings),
) -> JSONResponse:
    metadata_list = get_all_metadata(conn, path_like=f"%{req.path}%")
    if len(metadata_list) == 0:
        raise HTTPException(status_code=404, detail="path not found")
    elif len(metadata_list) > 1:
        raise HTTPException(status_code=400, detail="too many files to delete")

    metadata = metadata_list[0]

    try:
        delete_file_metadata(conn, metadata.path.as_posix())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    conn.commit()
    abs_path = server_settings.snapshot_folder / metadata.path
    Path(abs_path).unlink(missing_ok=True)
    return JSONResponse(content={"status": "success"})


@router.post("/create", response_class=JSONResponse)
def create_file(
    file: UploadFile,
    conn: sqlite3.Connection = Depends(get_db_connection),
    server_settings: ServerSettings = Depends(get_server_settings),
) -> JSONResponse:
    #
    relative_path = Path(file.filename)
    abs_path = server_settings.snapshot_folder / relative_path
    abs_path.parent.mkdir(exist_ok=True, parents=True)
    with open(abs_path, "wb") as f:
        # better to use async aiosqlite
        f.write(file.file.read())

    cursor = conn.cursor()
    metadata = get_all_metadata(cursor, path_like=f"%{file.filename}%")
    if len(metadata) > 0:
        raise HTTPException(status_code=400, detail="file already exists")
    metadata = hash_file(abs_path, root_dir=server_settings.snapshot_folder)
    save_file_metadata(cursor, metadata)
    conn.commit()
    cursor.close()

    return JSONResponse(content={"status": "success"})


@router.post("/download", response_class=FileResponse)
def download_file(
    req: FileRequest,
    conn: sqlite3.Connection = Depends(get_db_connection),
    server_settings: ServerSettings = Depends(get_server_settings),
) -> FileResponse:
    metadata_list = get_all_metadata(conn, path_like=f"%{req.path}%")
    if len(metadata_list) == 0:
        raise HTTPException(status_code=404, detail="path not found")
    elif len(metadata_list) > 1:
        raise HTTPException(status_code=400, detail="too many files to download")

    metadata = metadata_list[0]
    abs_path = server_settings.snapshot_folder / metadata.path
    if not Path(abs_path).exists():
        raise HTTPException(status_code=404, detail="file not found")
    return FileResponse(abs_path)


@router.post("/datasites", response_model=list[str])
def get_datasites(conn: sqlite3.Connection = Depends(get_db_connection)) -> list[str]:
    return get_all_datasites(conn)
