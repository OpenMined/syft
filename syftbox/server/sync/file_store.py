from pathlib import Path

from pydantic import BaseModel

from syftbox.server.settings import ServerSettings
from syftbox.server.sync import db
from syftbox.server.sync.db import get_db
from syftbox.server.sync.hash import hash_file
from syftbox.server.sync.models import AbsolutePath, FileMetadata, RelativePath


class SyftFile(BaseModel):
    metadata: FileMetadata
    data: bytes
    absolute_path: AbsolutePath


class FileStore:
    def __init__(self, server_settings: ServerSettings) -> None:
        self.server_settings = server_settings

    @property
    def db_path(self) -> AbsolutePath:
        return self.server_settings.file_db_path

    def delete(self, path: RelativePath) -> None:
        conn = get_db(self.db_path)
        cursor = conn.cursor()
        cursor.execute("BEGIN IMMEDIATE;")
        try:
            db.delete_file_metadata(cursor, str(path))
        except ValueError:
            pass
        abs_path = self.server_settings.snapshot_folder / path
        abs_path.unlink(missing_ok=True)
        conn.commit()
        cursor.close()

    def get(self, path: RelativePath) -> SyftFile:
        with get_db(self.db_path) as conn:
            metadata = db.get_one_metadata(conn, path=str(path))
            abs_path = self.server_settings.snapshot_folder / metadata.path

            if not Path(abs_path).exists():
                self.delete(metadata.path.as_posix())
                raise ValueError("File not found")
            return SyftFile(metadata=metadata, data=self._read_bytes(abs_path), absolute_path=abs_path)

    def exists(self, path: RelativePath) -> bool:
        with get_db(self.db_path) as conn:
            try:
                db.get_one_metadata(conn, path=str(path))
                return True
            except ValueError:
                return False

    def get_metadata(self, path: RelativePath) -> FileMetadata:
        with get_db(self.db_path) as conn:
            metadata = db.get_one_metadata(conn, path=str(path))
            return metadata

    def _read_bytes(self, path: AbsolutePath) -> bytes:
        with open(path, "rb") as f:
            return f.read()

    def put(self, path: Path, contents: bytes) -> None:
        abs_path = self.server_settings.snapshot_folder / path
        abs_path.parent.mkdir(exist_ok=True, parents=True)

        conn = get_db(self.db_path)
        cursor = conn.cursor()
        cursor.execute("BEGIN IMMEDIATE;")
        abs_path.write_bytes(contents)
        metadata = hash_file(abs_path, root_dir=self.server_settings.snapshot_folder)
        db.save_file_metadata(cursor, metadata)
        conn.commit()
        cursor.close()
        conn.close()

    def list(self, path: RelativePath) -> list[FileMetadata]:
        with get_db(self.db_path) as conn:
            metadata = db.get_all_metadata(conn, path_like=path.as_posix())
            return metadata
