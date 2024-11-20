import uuid
from pathlib import Path

from locust import FastHttpUser, between, task

import syftbox.client.exceptions
from syftbox.client.plugins.sync import consumer, endpoints
from syftbox.server.sync.hash import hash_file

file_name = Path("loadtest.txt")


class SyftBoxUser(FastHttpUser):
    network_timeout = 5.0
    connection_timeout = 5.0
    wait_time = between(0.5, 1.5)

    def on_start(self):
        self.datasites = []
        self.email = "aziz@openmined.org"
        self.remote_state: dict[str, list[endpoints.FileMetadata]] = {}

        # patch client for update_remote function
        self.client.sync_folder = Path(".")
        self.client.server_client = self.client

        self.filepath = self.init_file()

    def init_file(self) -> Path:
        # create a file on local and send to server
        filepath = self.client.sync_folder / file_name
        filepath.parent.mkdir(parents=True, exist_ok=True)
        filepath.touch()
        filepath.write_text(uuid.uuid4().hex)
        local_syncstate = hash_file(filepath.absolute(), root_dir=filepath.parent.absolute())
        try:
            endpoints.create(self.client, local_syncstate.path, filepath.read_bytes())
        except syftbox.client.exceptions.SyftServerError:
            pass
        return filepath

    @task
    def sync_datasites(self):
        remote_datasite_states = endpoints.get_datasite_states(
            self.client,
            email=self.email,
        )
        # logger.info(f"Syncing {len(remote_datasite_states)} datasites")
        all_files = []
        for email, remote_state in remote_datasite_states.items():
            all_files.extend(remote_state)

        all_paths = [str(f.path) for f in all_files][:10]
        endpoints.download_bulk(
            self.client,
            all_paths,
        )

    @task
    def apply_diff(self):
        self.filepath.write_text(uuid.uuid4().hex)
        local_syncstate = hash_file(self.filepath, root_dir=self.client.sync_folder)
        remote_syncstate = endpoints.get_metadata(self.client, local_syncstate.path)

        consumer.update_remote(
            self.client,
            local_syncstate=local_syncstate,
            remote_syncstate=remote_syncstate,
        )

    @task
    def download(self):
        endpoints.download(self.client, self.filepath)
