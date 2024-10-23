import base64
import enum
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field


class DiffRequest(BaseModel):
    path: Path
    signature: str

    @property
    def signature_bytes(self) -> bytes:
        return base64.b85decode(self.signature)


class DiffResponse(BaseModel):
    path: Path
    diff: str
    hash: str

    @property
    def diff_bytes(self) -> bytes:
        return base64.b85decode(self.diff)


class SignatureError(str, enum.Enum):
    FILE_NOT_FOUND = "FILE_NOT_FOUND"
    FILE_NOT_WRITEABLE = "FILE_NOT_WRITEABLE"
    FILE_NOT_READABLE = "FILE_NOT_READABLE"
    NOT_A_FILE = "NOT_A_FILE"


class SignatureResponse(BaseModel):
    path: str
    signature: Optional[str] = None
    error: Optional[SignatureError] = None


class FileMetadataRequest(BaseModel):
    path_like: str = Field(description="Path to search for files, uses SQL LIKE syntax")


class FileRequest(BaseModel):
    path: str = Field(description="Path to search for files, uses SQL LIKE syntax")


class ApplyDiffRequest(BaseModel):
    path: str
    diff: str
    expected_hash: str

    @property
    def diff_bytes(self) -> bytes:
        return base64.b85decode(self.diff)


class ApplyDiffResponse(BaseModel):
    path: str
    current_hash: str
    previous_hash: str


class FileMetadata(BaseModel):
    path: Path
    hash: str
    signature: str
    file_size: int = 0  # limit file sizes?
    last_modified: datetime

    @property
    def signature_bytes(self) -> bytes:
        return base64.b85decode(self.signature)

    @property
    def hash_bytes(self) -> bytes:
        return base64.b85decode(self.hash)

    def __eq__(self, value: Any):
        if not isinstance(value, FileMetadata):
            return False
        return self.path == value.path and self.hash == value.hash


class SyncLog(BaseModel):
    path: Path
    method: str  # pull or push
    status: str  # success or failure
    timestamp: datetime
    requesting_user: str
