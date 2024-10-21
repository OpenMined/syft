from pathlib import Path
from shutil import make_archive

from loguru import logger

from syftbox.lib.lib import DEFAULT_LOGS_PATH

# Configure Loguru to write logs to a file with rotation
logger.add(
    DEFAULT_LOGS_PATH,
    rotation="100 MB",  # Rotate after the log file reaches 100 MB
    retention=2,  # Keep only the last 1 log files
    compression="zip",  # Usually, 10x reduction in file size
)


def zip_logs(output_path):
    logger.info("Compressing logs folder")
    logs_folder = Path(DEFAULT_LOGS_PATH).parent
    return make_archive(output_path, "zip", logs_folder)
