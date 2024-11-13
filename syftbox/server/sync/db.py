import os
import shutil
import sqlite3
import tempfile
from pathlib import Path
from typing import Optional

from syftbox.server.settings import ServerSettings
from syftbox.server.sync.models import FileMetadata


# @contextlib.contextmanager
def get_db(path: str):
    conn = sqlite3.connect(path, check_same_thread=False)

    with conn:
        conn.execute("PRAGMA cache_size=10000;")
        conn.execute("PRAGMA synchronous=OFF;")
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=5000;")
        # Create the table if it doesn't exist
        conn.execute("""
        CREATE TABLE IF NOT EXISTS file_metadata (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            path TEXT NOT NULL UNIQUE,
            hash TEXT NOT NULL,
            signature TEXT NOT NULL,
            file_size INTEGER NOT NULL,
            last_modified TEXT NOT NULL        )
        """)
    return conn


def save_file_metadata(conn: sqlite3.Connection, metadata: FileMetadata):
    # Insert the metadata into the database or update if a conflict on 'path' occurs
    conn.execute(
        """
    INSERT INTO file_metadata (path, hash, signature, file_size, last_modified)
    VALUES (?, ?, ?, ?, ?)
    ON CONFLICT(path) DO UPDATE SET
        hash = excluded.hash,
        signature = excluded.signature,
        file_size = excluded.file_size,
        last_modified = excluded.last_modified
    """,
        (
            str(metadata.path),
            metadata.hash,
            metadata.signature,
            metadata.file_size,
            metadata.last_modified.isoformat(),
        ),
    )


def delete_file_metadata(conn: sqlite3.Connection, path: str):
    cur = conn.execute("DELETE FROM file_metadata WHERE path = ?", (path,))
    # get number of changes
    if cur.rowcount != 1:
        raise ValueError(f"Failed to delete metadata for {path}.")


def get_all_metadata(conn: sqlite3.Connection, path_like: Optional[str] = None) -> list[FileMetadata]:
    query = "SELECT * FROM file_metadata"
    params = ()

    if path_like:
        if "%" in path_like:
            raise ValueError("we don't support % in paths")
        path_like = path_like + "%"
        escaped_path = path_like.replace("_", "\\_")
        query += " WHERE path LIKE ? ESCAPE '\\' "
        params = (escaped_path,)

    cursor = conn.execute(query, params)
    # would be nice to paginate
    return [
        FileMetadata(
            path=row[1],
            hash=row[2],
            signature=row[3],
            file_size=row[4],
            last_modified=row[5],
        )
        for row in cursor
    ]


def get_one_metadata(conn: sqlite3.Connection, path: str) -> FileMetadata:
    cursor = conn.execute("SELECT * FROM file_metadata WHERE path = ?", (path,))
    rows = cursor.fetchall()
    if len(rows) == 0 or len(rows) > 1:
        raise ValueError(f"Expected 1 metadata entry for {path}, got {len(rows)}")
    row = rows[0]
    return FileMetadata(
        path=row[1],
        hash=row[2],
        signature=row[3],
        file_size=row[4],
        last_modified=row[5],
    )


def get_all_datasites(conn: sqlite3.Connection) -> list[str]:
    # INSTR(path, '/'): Finds the position of the first slash in the path.
    cursor = conn.execute(
        """SELECT DISTINCT SUBSTR(path, 1, INSTR(path, '/') - 1) AS root_folder
        FROM file_metadata;
        """
    )
    return [row[0] for row in cursor if row[0]]


def move_with_transaction(
    conn: sqlite3.Connection, *, origin_path: Path, metadata: FileMetadata, server_settings: ServerSettings
):
    """The file system and database do not share transactions,
    so this operation is not atomic.
    Ideally, files (blobs) should be immutable,
    and the path should update to a new location
    whenever there is a change to the file contents.
    """

    # backup the original file
    with tempfile.NamedTemporaryFile(delete=False) as temp_file:
        temp_path = temp_file.name

    shutil.copy(origin_path, temp_path)

    # Update database entry
    from_path = metadata.path
    relative_path = origin_path.relative_to(server_settings.snapshot_folder)
    metadata.path = relative_path

    cur = conn.cursor()
    save_file_metadata(cur, metadata)
    cur.close()
    conn.commit()

    # WARNING: between the move and the commit
    # the database will be in an inconsistent state

    shutil.move(from_path, origin_path)
    # Delete the temp file if it exists
    if os.path.exists(temp_path):
        os.remove(temp_path)
