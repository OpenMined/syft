import base64
import hashlib
import sqlite3
import zipfile
from io import BytesIO

import py_fast_rsync
from fastapi import APIRouter, Depends, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from loguru import logger

from syftbox.lib.lib import PermissionTree, SyftPermission, filter_metadata
from syftbox.server.analytics import log_analytics_event, log_file_change_event
from syftbox.server.settings import ServerSettings, get_server_settings
from syftbox.server.sync.db import (
    get_all_datasites,
    get_db,
)
from syftbox.server.sync.file_store import FileStore, SyftFile
from syftbox.server.users.auth import get_current_user

from .models import (
    ApplyDiffRequest,
    ApplyDiffResponse,
    BatchFileRequest,
    DiffRequest,
    DiffResponse,
    FileMetadata,
    FileMetadataRequest,
    FileRequest,
    RelativePath,
)


def get_db_connection(request: Request):
    conn = get_db(request.state.server_settings.file_db_path)
    yield conn
    conn.close()


def get_file_store(request: Request):
    store = FileStore(
        server_settings=request.state.server_settings,
    )
    yield store


router = APIRouter(prefix="/sync", tags=["sync"])


@router.post("/get_diff", response_model=DiffResponse)
def get_diff(
    req: DiffRequest,
    file_store: FileStore = Depends(get_file_store),
    email: str = Depends(get_current_user),
) -> DiffResponse:
    try:
        file = file_store.get(req.path)
    except ValueError:
        raise HTTPException(status_code=404, detail="file not found")
    diff = py_fast_rsync.diff(req.signature_bytes, file.data)
    diff_bytes = base64.b85encode(diff).decode("utf-8")
    return DiffResponse(
        path=file.metadata.path.as_posix(),
        diff=diff_bytes,
        hash=file.metadata.hash,
    )


@router.post("/datasite_states", response_model=dict[str, list[FileMetadata]])
def get_datasite_states(
    conn: sqlite3.Connection = Depends(get_db_connection),
    file_store: FileStore = Depends(get_file_store),
    server_settings: ServerSettings = Depends(get_server_settings),
    email: str = Depends(get_current_user),
) -> dict[str, list[FileMetadata]]:
    all_datasites = get_all_datasites(conn)
    datasite_states: dict[str, list[FileMetadata]] = {}
    for datasite in all_datasites:
        try:
            datasite_state = dir_state(RelativePath(datasite), file_store, server_settings, email)
        except Exception as e:
            logger.error(f"Failed to get dir state for {datasite}: {e}")
            continue
        datasite_states[datasite] = datasite_state

    return datasite_states


@router.post("/dir_state", response_model=list[FileMetadata])
def dir_state(
    dir: RelativePath,
    file_store: FileStore = Depends(get_file_store),
    server_settings: ServerSettings = Depends(get_server_settings),
    email: str = Depends(get_current_user),
) -> list[FileMetadata]:
    full_path = server_settings.snapshot_folder / dir
    # get the top level perm file
    try:
        perm_tree = PermissionTree.from_path(full_path, raise_on_corrupted_files=True)
    except ValueError:
        raise HTTPException(status_code=500, detail=f"Failed to parse permission tree: {dir}")

    # filter the read state for this user by the perm tree
    metadata_list = file_store.list(dir)
    filtered_metadata = filter_metadata(email, metadata_list, perm_tree, server_settings.snapshot_folder)
    return filtered_metadata


@router.post("/get_metadata", response_model=FileMetadata)
def get_metadata(
    req: FileMetadataRequest,
    file_store: FileStore = Depends(get_file_store),
    email: str = Depends(get_current_user),
) -> FileMetadata:
    try:
        metadata = file_store.get_metadata(req.path_like)
        log_analytics_event(
            "/sync/get_metadata",
            email=email,
            file_metadata=metadata,
        )
        return metadata
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/apply_diff", response_model=ApplyDiffResponse)
def apply_diffs(
    req: ApplyDiffRequest,
    file_store: FileStore = Depends(get_file_store),
    email: str = Depends(get_current_user),
) -> ApplyDiffResponse:
    try:
        file = file_store.get(req.path)
    except ValueError:
        raise HTTPException(status_code=404, detail="file not found")

    result = py_fast_rsync.apply(file.data, req.diff_bytes)
    new_hash = hashlib.sha256(result).hexdigest()

    if new_hash != req.expected_hash:
        raise HTTPException(status_code=400, detail="hash mismatch, skipped writing")

    if SyftPermission.is_permission_file(file.metadata.path) and not SyftPermission.is_valid(result):
        raise HTTPException(status_code=400, detail="invalid syftpermission contents, skipped writing")

    file_store.put(req.path, result)

    log_file_change_event(
        "/sync/apply_diff",
        email=email,
        relative_path=req.path,
        file_store=file_store,
    )

    return ApplyDiffResponse(path=req.path, current_hash=new_hash, previous_hash=file.metadata.hash)


@router.post("/delete", response_class=JSONResponse)
def delete_file(
    req: FileRequest,
    file_store: FileStore = Depends(get_file_store),
    email: str = Depends(get_current_user),
) -> JSONResponse:
    log_file_change_event(
        "/sync/delete",
        email=email,
        relative_path=req.path,
        file_store=file_store,
    )

    file_store.delete(req.path)
    return JSONResponse(content={"status": "success"})


@router.post("/create", response_class=JSONResponse)
def create_file(
    file: UploadFile,
    file_store: FileStore = Depends(get_file_store),
    email: str = Depends(get_current_user),
) -> JSONResponse:
    relative_path = RelativePath(file.filename)
    if "%" in file.filename:
        raise HTTPException(status_code=400, detail="filename cannot contain '%'")

    if file_store.exists(relative_path):
        raise HTTPException(status_code=400, detail="file already exists")

    contents = file.file.read()

    if SyftPermission.is_permission_file(relative_path) and not SyftPermission.is_valid(contents):
        raise HTTPException(status_code=400, detail="invalid syftpermission contents, skipped writing")

    file_store.put(
        relative_path,
        contents,
    )

    log_file_change_event(
        "/sync/create",
        email=email,
        relative_path=relative_path,
        file_store=file_store,
    )
    return JSONResponse(content={"status": "success"})


@router.post("/download", response_class=FileResponse)
def download_file(
    req: FileRequest,
    file_store: FileStore = Depends(get_file_store),
    email: str = Depends(get_current_user),
) -> FileResponse:
    try:
        abs_path = file_store.get(req.path).absolute_path
        return FileResponse(abs_path)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/datasites", response_model=list[str])
def get_datasites(
    conn: sqlite3.Connection = Depends(get_db_connection),
    email: str = Depends(get_current_user),
) -> list[str]:
    return get_all_datasites(conn)


def create_zip_from_files(files: list[SyftFile]) -> BytesIO:
    memory_file = BytesIO()
    with zipfile.ZipFile(memory_file, "w") as zf:
        for file in files:
            zf.writestr(file.metadata.path.as_posix(), file.data)
    memory_file.seek(0)
    return memory_file


@router.post("/download_bulk")
async def get_files(
    req: BatchFileRequest,
    file_store: FileStore = Depends(get_file_store),
    email: str = Depends(get_current_user),
) -> StreamingResponse:
    all_files = []
    for path in req.paths:
        try:
            file = file_store.get(path)
        except ValueError:
            logger.warning(f"File not found: {path}")
            continue
        all_files.append(file)
    zip_file = create_zip_from_files(all_files)
    return Response(content=zip_file.read(), media_type="application/zip")
