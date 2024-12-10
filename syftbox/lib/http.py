import platform

from syftbox import __version__

# keep these as bytes
HEADER_SYFTBOX_VERSION = b"x-syftbox-version"
HEADER_SYFTBOX_PYTHON = b"x-syftbox-python"
HEADER_SYFTBOX_USER = b"x-syftbox-user"
HEADER_OS_NAME = b"x-os-name"
HEADER_OS_VERSION = b"x-os-ver"
HEADER_OS_ARCH = b"x-os-arch"

_PYTHON_VERSION = platform.python_version()

SYFTBOX_HEADERS = {
    HEADER_SYFTBOX_VERSION: __version__,
    HEADER_SYFTBOX_PYTHON: _PYTHON_VERSION,
    # todo - os
}
