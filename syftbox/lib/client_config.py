import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import markdown
from typing_extensions import Self

from syftbox.lib.jsonable import Jsonable
from syftbox.lib.lib import SyftPermission, get_datasites
from syftbox.lib.link import SyftLink


def markdown_to_html(markdown_text):
    html = markdown.markdown(markdown_text)
    return html


@dataclass
class DatasiteManifest(Jsonable):
    datasite: str
    file_path: str
    datasets: dict = field(default_factory=dict)
    code: dict = field(default_factory=dict)

    @classmethod
    def load_from_datasite(cls, path: str) -> Self | None:
        datasite_path = Path(os.path.abspath(path))
        manifest_path = datasite_path / "public" / "manifest" / "manifest.json"
        try:
            manifest = DatasiteManifest.load(manifest_path)
            return manifest
        except Exception:
            pass
        return None

    class Dataset:
        sync_path: str


@dataclass
class ClientConfig(Jsonable):
    config_path: Path
    sync_folder: Path | None = None
    port: int | None = None
    email: str | None = None
    token: int | None = None
    server_url: str = "http://localhost:5001"
    email_token: str | None = None

    def save(self, path: str | None = None) -> None:
        if path is None:
            path = self.config_path
        super().save(path)

    @property
    def datasite_path(self) -> Path:
        return os.path.join(self.sync_folder, self.email)

    @property
    def manifest_path(self) -> Path:
        return os.path.join(self.datasite_path, "public/manifest/manifest.json")

    @property
    def manifest(self) -> DatasiteManifest:
        datasite_manifest = None
        try:
            datasite_manifest = DatasiteManifest.load(self.manifest_path)
        except Exception:
            datasite_manifest = DatasiteManifest.create_manifest(
                path=self.manifest_path, email=self.email
            )

        return datasite_manifest

    def get_datasites(self: str) -> list[str]:
        datasites = []
        folders = os.listdir(self.sync_folder)
        for folder in folders:
            if "@" in folder:
                datasites.append(folder)
        return datasites

    def get_all_manifests(self):
        manifests = {}
        for datasite in get_datasites(self.sync_folder):
            datasite_path = Path(self.sync_folder + "/" + datasite)
            datasite_manifest = DatasiteManifest.load_from_datasite(datasite_path)
            if datasite_manifest:
                manifests[datasite] = datasite_manifest
        return manifests

    def get_datasets(self):
        manifests = self.get_all_manifests()
        datasets = []
        for datasite, manifest in manifests.items():
            for dataset_name, dataset_dict in manifest.datasets.items():
                try:
                    dataset = TabularDataset(**dataset_dict)
                    dataset.syft_link = SyftLink(**dataset_dict["syft_link"])
                    dataset.readme_link = SyftLink(**dataset_dict["readme_link"])
                    dataset.loader_link = SyftLink(**dataset_dict["loader_link"])
                    dataset._client_config = self
                    datasets.append(dataset)
                except Exception as e:
                    print(f"Bad dataset format. {datasite} {e}")

        return DatasetResults(datasets)

    def get_code(self):
        manifests = self.get_all_manifests()
        all_code = []
        for datasite, manifest in manifests.items():
            for func_name, code_dict in manifest.code.items():
                try:
                    code = Code(**code_dict)
                    code.syft_link = SyftLink(**code_dict["syft_link"])
                    code.readme_link = SyftLink(**code_dict["readme_link"])
                    code.requirements_link = SyftLink(**code_dict["requirements_link"])
                    code._client_config = self
                    all_code.append(code)
                except Exception as e:
                    print(f"Bad dataset format. {datasite} {e}")

        return CodeResults(all_code)

    def resolve_link(self, link: SyftLink | str) -> Path:
        if isinstance(link, str):
            link = SyftLink.from_url(link)
        return Path(os.path.join(os.path.abspath(self.sync_folder), link.sync_path))

    def use(self):
        os.environ["SYFTBOX_CURRENT_CLIENT"] = self.config_path
        os.environ["SYFTBOX_SYNC_DIR"] = self.sync_folder
        print(f"> Setting Sync Dir to: {self.sync_folder}")

    @classmethod
    def create_manifest(cls, path: str, email: str):
        # make a dir and set the permissions
        manifest_dir = os.path.dirname(path)
        os.makedirs(manifest_dir, exist_ok=True)

        public_read = SyftPermission.mine_with_public_read(email=email)
        public_read.save(manifest_dir)

        datasite_manifest = DatasiteManifest(datasite=email, file_path=path)
        datasite_manifest.save(path)
        return datasite_manifest

    def create_folder(self, path: str, permission: SyftPermission):
        os.makedirs(path, exist_ok=True)
        permission.save(path)

    @property
    def root_dir(self) -> Path:
        root_dir = Path(os.path.abspath(os.path.dirname(self.file_path) + "/../"))
        return root_dir

    def create_public_folder(self, path: str):
        full_path = self.root_dir / path
        os.makedirs(str(full_path), exist_ok=True)
        public_read = SyftPermission.mine_with_public_read(email=self.datasite)
        public_read.save(full_path)
        return Path(full_path)

    def publish(self, item, overwrite: bool = False):
        if isinstance(item, Callable):
            syftbox_code(item).publish(self, overwrite=overwrite)
