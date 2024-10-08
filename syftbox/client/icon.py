from pathlib import Path
import os

from const import ASSETS_FOLDER

def find_icon_file(src_folder: str) -> Path:
    """
    Searches for an icon file in the given source folder,
    handling special macOS icon files.
    """
    src_path = Path(src_folder)

    # Function to search for Icon\r file
    def search_icon_file():
        if os.path.exists(src_folder):
            for file_path in src_path.iterdir():
                if "Icon" in file_path.name and "\r" in file_path.name:
                    return file_path
        return None

    # First attempt to find the Icon\r file
    icon_file = search_icon_file()
    if icon_file:
        return icon_file

    # If Icon\r is not found, search for icon.zip and unzip it
    zip_file = ASSETS_FOLDER / "icon.zip"

    if zip_file.exists():
        try:
            # cant use other zip tools as they don't unpack it correctly
            subprocess.run(
                ["ditto", "-xk", str(zip_file), str(src_path.parent)],
                check=True,
            )

            # Try to find the Icon\r file again after extraction
            icon_file = search_icon_file()
            if icon_file:
                return icon_file
        except subprocess.CalledProcessError:
            raise RuntimeError("Failed to unzip icon.zip using macOS CLI tool.")

    # If still not found, raise an error
    raise FileNotFoundError(
        "Icon file with a carriage return not found, and icon.zip did not contain it.",
    )


def copy_icon_file(icon_folder: str, dest_folder: str) -> None:
    """
    Copies the icon file to the destination folder,
    setting the correct attributes on the destination folder.
    """
    src_icon_path = find_icon_file(icon_folder)
    if not os.path.isdir(dest_folder):
        raise FileNotFoundError(f"Destination folder '{dest_folder}' does not exist.")

    # shutil wont work with these special icon files
    subprocess.run(["cp", "-p", src_icon_path, dest_folder], check=True)
    subprocess.run(["SetFile", "-a", "C", dest_folder], check=True)
