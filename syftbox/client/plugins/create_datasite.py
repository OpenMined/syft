import logging
import os

from syftbox import Client
from syftbox.lib import SyftPermission, perm_file_path
from syftbox.lib.ignore import create_default_ignore_file

logger = logging.getLogger(__name__)

DEFAULT_SCHEDULE = 10000
DESCRIPTION = "Creates a datasite with a permfile"


def claim_datasite(client: Client):
    # create the directory
    os.makedirs(client.datasite_path, exist_ok=True)

    # create syftignore
    create_default_ignore_file(client)

    # add the first perm file
    file_path = perm_file_path(str(client.datasite_path))
    if os.path.exists(file_path):
        perm_file = SyftPermission.load(file_path)
    else:
        logger.info(f"> {client.email} Creating Datasite + Permfile")
        try:
            perm_file = SyftPermission.datasite_default(client.email)
            perm_file.save(file_path)
        except Exception as e:
            logger.error("Failed to create perm file")
            logger.exception(e)

    public_path = str(client.datasite_path) + "/" + "public"
    os.makedirs(public_path, exist_ok=True)
    public_file_path = perm_file_path(public_path)
    if os.path.exists(public_file_path):
        public_perm_file = SyftPermission.load(public_file_path)
    else:
        logger.info(f"> {client.email} Creating Public Permfile")
        try:
            public_perm_file = SyftPermission.mine_with_public_read(client.email)
            public_perm_file.save(public_file_path)
        except Exception as e:
            logger.error("Failed to create perm file")
            logger.exception(e)


def run(shared_state):
    client = shared_state.client
    claim_datasite(client)
