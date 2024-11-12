import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from syftbox.server.settings import ServerSettings
from syftbox.server.sync.file_store import FileStore
from syftbox.server.sync.hash import hash_file


def test_put_atomic(tmpdir):
    settings = ServerSettings.from_data_folder(tmpdir)
    syft_path = Path("test.txt")
    system_path = settings.snapshot_folder / syft_path

    with ThreadPoolExecutor(max_workers=5) as executor:
        executor.map(lambda _: FileStore(settings).put(syft_path, uuid.uuid4().bytes), range(25))

    assert system_path.exists()
    metadata = FileStore(settings).get_metadata(syft_path)
    assert metadata.hash_bytes == hash_file(system_path).hash_bytes
