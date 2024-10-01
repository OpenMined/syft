import argparse
import os
import shutil

# from dataset import run as make_dataset
from imdb import run as add_imdb_data
from netflix import run as preprocess_netflix
from page import run as make_page
from tmdb import run as get_tmdb_data
from utils import compute_file_hash, load_cache, save_cache


def publish_page(output_path):
    try:
        from syftbox.lib.client_config import ClientConfig

        config_path = os.environ.get("SYFTBOX_CLIENT_CONFIG_PATH", None)
        client_config = ClientConfig.load(config_path)

        file_name = "index.html"
        destination = "public/apps/netflix/"
        destination_path = client_config.datasite_path + "/" + destination
        os.makedirs(destination_path, exist_ok=True)

        shutil.copy2(output_path, destination_path + "/" + file_name)
        print(
            f"> Netflix app published to: {client_config.server_url}/datasites/{client_config.email}/apps/netflix/"
        )
    except Exception as e:
        import traceback

        print(traceback.format_exc())
        print("Couldnt publish", e)
        pass


def main():
    # Create the argument parser
    parser = argparse.ArgumentParser(description="Enter your TMDB API key.")

    # Add an argument for the TMDB API key
    parser.add_argument("--tmdb-api-key", required=False, help="Your TMDB API key")
    parser.add_argument(
        "--missing-imdb-file", required=False, help="Your missing IMDB title file"
    )
    parser.add_argument(
        "--force", action="store_true", default=False, help="Override hash check"
    )

    os.makedirs("./cache", exist_ok=True)
    os.makedirs("./inputs", exist_ok=True)
    os.makedirs("./temp", exist_ok=True)
    os.makedirs("./output", exist_ok=True)

    input_file = "./inputs/NetflixViewingHistory.csv"
    if not os.path.exists(input_file):
        print(f"Error: Netflix file {input_file} required.")
        return

    # Parse the arguments
    args = parser.parse_args()

    # If the API key is not provided via args, ask for it interactively
    tmdb_api_key = args.tmdb_api_key
    if tmdb_api_key is None or tmdb_api_key == "":
        tmdb_api_key = os.environ.get("TMDB_API_KEY", None)
        if not tmdb_api_key:
            tmdb_api_key = input("Please enter your TMDB API key: ")

    if tmdb_api_key is None or tmdb_api_key == "":
        print("Error: TMDB_API_KEY required")
        return

    print(f"Your TMDB API key is: {tmdb_api_key}")

    missing_file = None
    if args.missing_imdb_file:
        if not os.path.exists(args.missing_imdb_file):
            print(f"Can't find missing imdb id file at: {args.missing_imdb_file}")
        missing_file = args.missing_imdb_file

    input_hash = compute_file_hash(input_file)
    output_path = "output/index.html"
    output_hash = None
    if os.path.exists(output_path):
        output_hash = compute_file_hash(output_path)
    last_run = load_cache("last_run.json")
    if (
        "input_hash" in last_run
        and "output_hash" in last_run
        and last_run["input_hash"] == input_hash
        and last_run["output_hash"] == output_hash
        and not args.force
    ):
        print(f"Already generated html for {input_file} with hash: {input_hash}")
        return

    preprocess_netflix()
    get_tmdb_data(tmdb_api_key, missing_file)
    add_imdb_data()
    # make_dataset()
    make_page()

    last_run = {"input_hash": input_hash}
    if os.path.exists(output_path):
        last_run["output_hash"] = compute_file_hash(output_path)
    save_cache(last_run, "last_run.json")
    publish_page(output_path)


if __name__ == "__main__":
    main()
