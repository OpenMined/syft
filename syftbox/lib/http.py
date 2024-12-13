from syftbox import __version__
from syftbox.lib.platform import OS_ARCH, OS_NAME, OS_VERSION, PYTHON_VERSION

# keep these as bytes as otel hooks return headers as bytes
HEADER_SYFTBOX_VERSION = b"x-syftbox-version"
HEADER_SYFTBOX_PYTHON = b"x-syftbox-python"
HEADER_SYFTBOX_USER = b"x-syftbox-user"
HEADER_OS_NAME = b"x-os-name"
HEADER_OS_VERSION = b"x-os-ver"
HEADER_OS_ARCH = b"x-os-arch"

SYFTBOX_HEADERS = {
    "User-Agent": f"SyftBox/{__version__} (Python {PYTHON_VERSION}; {OS_NAME} {OS_VERSION}; {OS_ARCH})",
    HEADER_SYFTBOX_VERSION: __version__,
    HEADER_SYFTBOX_PYTHON: PYTHON_VERSION,
    HEADER_OS_NAME: OS_NAME,
    HEADER_OS_VERSION: OS_VERSION,
    HEADER_OS_ARCH: OS_ARCH,
}