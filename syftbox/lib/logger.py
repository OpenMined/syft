from pathlib import Path
from shutil import make_archive

from loguru import logger


def zip_logs(output_path: Path, logs_dir: Path):
    # Configure Loguru to write logs to a file with rotation
    logs_path = logs_dir / output_path
    logger.add(
        logs_path,
        rotation="100 MB",  # Rotate after the log file reaches 100 MB
        retention=2,  # Keep only the last 1 log files
        compression="zip",  # Usually, 10x reduction in file size
    )

    logger.info("Compressing logs folder")
    return make_archive(output_path, "zip", logs_dir)
