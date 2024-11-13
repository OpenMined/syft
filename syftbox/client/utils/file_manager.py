import os
import platform
import subprocess
from typing import Tuple


def open_dir(folder_path) -> Tuple[bool, str]:
    """Open the folder specified by `folder_path` in the default file explorer."""
    if not os.path.exists(folder_path):
        return False, f"Folder does not exist: {folder_path}"

    try:
        if platform.system() == "Darwin":
            subprocess.run(["open", folder_path])
        elif platform.system() == "Windows":
            subprocess.run(["explorer", folder_path])
        elif platform.system() == "Linux":
            # xdg-open is not available on all Linux distros
            distro_explorer = _get_linux_file_explorer()
            subprocess.run([distro_explorer, folder_path])
        else:
            return False, f"Unsupported OS for opening folders: {platform.system()}"
        return True
    except Exception as e:
        return False, str(e)


def _get_linux_file_explorer() -> str:
    """Get the default file explorer for Linux distros."""
    # implement as needed, for now just return xdg-open
    return "xdg-open"
