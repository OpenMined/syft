import os

import pandas as pd

from syftbox.lib import SyftVault, TabularDataset
from syftbox.lib.client_config import ClientConfig


def run():
    try:
        imdb_df = pd.read_csv("./temp/3_imdb.csv")

        dataset_filename = "NetflixViewingHistory_TMDB_IMDB.csv"
        imdb_mock_df = pd.read_csv("./data/NetflixViewingHistory_TMDB_IMDB.mock.csv")

        if set(imdb_df.columns) != set(imdb_mock_df.columns):
            raise Exception("Netflix real vs mock schema are different")

        config_path = os.environ.get("SYFTBOX_CLIENT_CONFIG_PATH", None)
        client_config = ClientConfig.load(config_path)
        manifest = client_config.manifest

        # create public datasets folder
        datasets_path = manifest.create_public_folder("datasets")

        dataset_path = datasets_path / "netflix_tmdb_imdb"
        csv_file = dataset_path / dataset_filename
        os.makedirs(dataset_path, exist_ok=True)

        # write mock data
        imdb_mock_df.to_csv(csv_file)

        dataset = TabularDataset.from_csv(
            csv_file, name="Netflix_TMDB_IMDB", has_private=True
        )
        dataset.publish(manifest, overwrite=True)

        # write private file
        private_path = os.path.abspath(f"./output/{dataset_filename}")
        imdb_df.to_csv(private_path)
        print(f"> Writing private {dataset_filename} to {private_path}")

        SyftVault.link_private(csv_file, private_path)

    except Exception as e:
        print("Failed to make dataset with dataset.py", e)
