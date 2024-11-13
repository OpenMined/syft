from pathlib import Path

from loguru import logger

from syftbox.lib.constants import PERM_FILE
from syftbox.lib.exceptions import SyftBoxException
from syftbox.lib.ignore import create_default_ignore_file
from syftbox.lib.lib import SyftPermission


def create_datasite(datasite_root: Path, email: str):
    # Create workspace/datasites/.syftignore
    create_default_ignore_file(datasite_root)

    user_root = datasite_root / email
    user_public_dir = user_root / "public"

    # Create perm file for the datasite
    if not user_root.is_dir():
        try:
            logger.info(f"creating datasite at {user_root}")
            user_root.mkdir(parents=True, exist_ok=True)
            perms = SyftPermission.datasite_default(email)
            perms.save(str(user_root / PERM_FILE))
        except Exception as e:
            # this is a problematic scenario - probably because you can't setup the basic
            # datasite structure. So, we should probably just exit here.
            raise SyftBoxException(f"Failed to initialize datasite - {e}") from e

    if not user_public_dir.is_dir():
        try:
            logger.info(f"creating public dir in datasite at {user_public_dir}")
            user_public_dir.mkdir(parents=True, exist_ok=True)
            perms = SyftPermission.mine_with_public_read(email)
            perms.save(str(user_public_dir / PERM_FILE))
        except Exception as e:
            # not a big deal if we can't create the public folder
            # more likely that the above step fails than this
            logger.exception("Failed to create folder with public perms", e)
