import os
import shutil
import sqlite3
import tempfile
from pathlib import Path
from typing import List, Optional

from syftbox.lib.permissions import PermissionFile, PermissionRule
from syftbox.server.models.sync_models import FileMetadata
from syftbox.server.settings import ServerSettings


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
    conn: sqlite3.Connection,
    *,
    origin_path: Path,
    metadata: FileMetadata,
    server_settings: ServerSettings,
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


def query_rules_for_permfile(cursor, file: PermissionFile):
    cursor.execute(
        """
        SELECT * FROM rules WHERE permfile_path = ? ORDER BY priority
    """,
        (str(file.filepath),),
    )
    return cursor.fetchall()


def get_rules_for_permfile(connection: sqlite3.Connection, file: PermissionFile):
    cursor = connection.cursor()
    return [PermissionRule.from_db_row(row) for row in query_rules_for_permfile(cursor, file)]


def get_all_files_under_dir(cursor, dir_path):
    cursor.execute(
        """
        SELECT * FROM file_metadata WHERE path LIKE ?
    """,
        (str(dir_path) + "/%",),
    )
    return cursor.fetchall()


def get_all_files(cursor):
    cursor.execute(
        """
        SELECT * FROM file_metadata
    """
    )
    return cursor.fetchall()


def get_all_files_under_syftperm(cursor, permfile: PermissionFile) -> List[Path]:
    cursor.execute(
        """
        SELECT * FROM file_metadata WHERE path LIKE ?
    """,
        (str(permfile.dir_path) + "/%",),
    )
    return [
        (
            row["id"],
            FileMetadata(
                path=Path(row["path"]),
                hash=row["hash"],
                signature=row["signature"],
                file_size=row["file_size"],
                last_modified=row["last_modified"],
            ),
        )
        for row in cursor.fetchall()
    ]


def get_rules_for_path(connection: sqlite3.Connection, path: Path):
    parents = path.parents
    placeholders = ",".join("?" * len(parents))
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT * FROM rules WHERE permfile_dir in ({})
    """.format(placeholders),
        [str(x) for x in parents],
    )
    return [PermissionRule.from_db_row(row) for row in cursor.fetchall()]


def set_rules_for_permfile(connection, file: PermissionFile):
    """
    Atomically set the rules for a permission file. Basically its just a write operation, but
    we also make sure we delete the rules that are no longer in the file.
    """
    try:
        cursor = connection.cursor()

        cursor.execute(
            """
        DELETE FROM rules
        WHERE permfile_path = ?
        """,
            (str(file.filepath),),
        )

        # TODO
        files_under_dir = get_all_files_under_syftperm(cursor, file)

        rule2files = []

        for rule in file.rules:
            for _id, file_in_dir in files_under_dir:
                match, match_for_email = rule.filepath_matches_rule_path(file_in_dir.path)
                if match:
                    rule2files.append([str(rule.permfile_path), rule.priority, _id, match_for_email])

        rule_rows = [tuple(rule.to_db_row().values()) for rule in file.rules]

        cursor.executemany(
            """
        INSERT INTO rules (
            permfile_path, permfile_dir, permfile_depth, priority, path, user,
            can_read, can_create, can_write, admin,
            disallow, terminal
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(permfile_path, priority) DO UPDATE SET
            path = excluded.path,
            user = excluded.user,
            can_read = excluded.can_read,
            can_create = excluded.can_create,
            can_write = excluded.can_write,
            admin = excluded.admin,
            disallow = excluded.disallow,
            terminal = excluded.terminal;
        """,
            rule_rows,
        )

        cursor.executemany(
            """
            INSERT INTO rule_files (permfile_path, priority, file_id, match_for_email) VALUES (?, ?, ?, ?)
        """,
            rule2files,
        )

        connection.commit()
    except Exception as e:
        connection.rollback()
        raise e


def get_read_permissions_for_user(connection: sqlite3.Connection, user: str):
    cursor = connection.cursor()

    res = cursor.execute(
        """
    SELECT path,
    (
        SELECT COALESCE(max(
            CASE
                WHEN can_read AND NOT disallow AND NOT terminal THEN rule_prio
                WHEN can_read AND NOT disallow AND terminal THEN terminal_prio
                ELSE 0
            END
        ) >
        max(
            CASE
                WHEN can_read AND disallow AND NOT terminal THEN rule_prio
                WHEN can_read AND disallow AND terminal THEN terminal_prio
                ELSE 0
            END
        ), 0)
        or
        COALESCE(max(
            CASE
                WHEN admin AND NOT disallow AND NOT terminal THEN rule_prio
                WHEN admin AND NOT disallow AND terminal THEN terminal_prio
                ELSE 0
            END
        ) >
        max(
            CASE
                WHEN admin AND disallow AND NOT terminal THEN rule_prio
                WHEN admin AND disallow AND terminal THEN terminal_prio
                ELSE 0
            END
        ), 0)
        FROM (
            SELECT can_read, admin, disallow, terminal,
                row_number() OVER (ORDER BY rules.permfile_depth, rules.priority ASC) AS rule_prio,
                row_number() OVER (ORDER BY rules.permfile_depth, rules.priority DESC) * 1000000 AS terminal_prio
            FROM rule_files
            JOIN rules ON rule_files.permfile_path = rules.permfile_path and rule_files.priority = rules.priority
            WHERE rule_files.file_id = f.id and (rules.user = ? or rules.user = "*" or rule_files.match_for_email = ?)
        )
    ) AS read_permission
    FROM file_metadata f
    """,
        (user, user),
    )
    return res.fetchall()
