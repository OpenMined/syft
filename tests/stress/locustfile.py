import os
import random
import uuid
from pathlib import Path

from locust import FastHttpUser, between, task

from syftbox.client.plugins.sync import consumer, endpoints
from syftbox.lib.workspace import SyftWorkspace
from syftbox.server.sync.hash import hash_file

file_name = Path("loadtest.txt")

PERCENTAGE_LARGE_FILES = 20
LARGE_FILE_SIZE_MB = 20


class SyftBoxUser(FastHttpUser):
    network_timeout = 5.0
    connection_timeout = 5.0
    wait_time = between(0.5, 1.5)

    def on_start(self):
        self.datasites = []
        self.email = "aziz@openmined.org"
        self.remote_state: dict[str, list[endpoints.FileMetadata]] = {}

        # patch client for update_remote function
        workspace = SyftWorkspace(Path("."))
        self.client.workspace = workspace
        self.client.server_client = self.client

        self.filepath = self.init_file()

    def init_file(self) -> Path:
        # create a file on local and send to server
        filepath = self.client.workspace.datasites / self.email / file_name
        filepath.parent.mkdir(parents=True, exist_ok=True)
        contents = bytes.fromhex(uuid.uuid4().hex)
        filepath.touch()
        filepath.write_bytes(contents)
        local_syncstate = hash_file(filepath.absolute(), root_dir=self.client.workspace.datasites.absolute())
        try:
            endpoints.create(self.client, local_syncstate.path, filepath.read_bytes())
        except endpoints.SyftServerError:
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
        if random.randint(0, 100) < PERCENTAGE_LARGE_FILES:
            contents = os.urandom(LARGE_FILE_SIZE_MB * 1024 * 1024)
        else:
            contents = bytes.fromhex(uuid.uuid4().hex)

        self.filepath.write_bytes(contents)
        local_syncstate = hash_file(self.filepath, root_dir=self.client.workspace.datasites)
        remote_syncstate = endpoints.get_metadata(self.client, local_syncstate.path)

        consumer.update_remote(
            self.client,
            local_syncstate=local_syncstate,
            remote_syncstate=remote_syncstate,
        )

    @task
    def download(self):
        endpoints.download(self.client, self.filepath.relative_to(self.client.workspace.datasites.absolute()))
