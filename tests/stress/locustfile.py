import uuid
from pathlib import Path

from locust import FastHttpUser, between, task

import syftbox.client.exceptions
from syftbox.client.plugins.sync import consumer
from syftbox.client.plugins.sync.sync_client import SyncClient
from syftbox.lib.workspace import SyftWorkspace
from syftbox.server.sync.hash import hash_file
from syftbox.server.sync.models import FileMetadata

file_name = Path("loadtest.txt")


class SyftBoxUser(FastHttpUser):
    network_timeout = 5.0
    connection_timeout = 5.0
    wait_time = between(0.5, 1.5)

    def on_start(self):
        self.datasites = []
        self.email = "aziz@openmined.org"
        self.remote_state: dict[str, list[FileMetadata]] = {}

        self.sync_client = SyncClient(
            email=self.email,
            client=self.client,
            workspace=SyftWorkspace(data_dir=Path(".")),
        )

        self.filepath = self.init_file()

    def init_file(self) -> Path:
        # create a file on local and send to server
        filepath = self.client.sync_folder / file_name
        filepath.parent.mkdir(parents=True, exist_ok=True)
        filepath.touch()
        filepath.write_text(uuid.uuid4().hex)
        local_syncstate = hash_file(filepath.absolute(), root_dir=filepath.parent.absolute())
        try:
            self.sync_client.create(local_syncstate.path, filepath.read_bytes())
        except syftbox.client.exceptions.SyftServerError:
            pass
        return filepath

    @task
    def sync_datasites(self):
        remote_datasite_states = self.sync_client.get_datasite_states()
        # logger.info(f"Syncing {len(remote_datasite_states)} datasites")
        all_files: list[FileMetadata] = []
        for remote_state in remote_datasite_states.values():
            all_files.extend(remote_state)

        all_paths = [f.path for f in all_files][:10]
        self.sync_client.download_bulk(all_paths)

    @task
    def apply_diff(self):
        self.filepath.write_text(uuid.uuid4().hex)
        local_syncstate = hash_file(self.filepath, root_dir=self.client.sync_folder)
        remote_syncstate = self.sync_client.get_metadata(self.filepath)

        consumer.update_remote(
            self.sync_client,
            local_syncstate=local_syncstate,
            remote_syncstate=remote_syncstate,
        )

    @task
    def download(self):
        self.sync_client.download(self.filepath)
