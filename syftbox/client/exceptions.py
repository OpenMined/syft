from syftbox.lib.exceptions import SyftBoxException


class SyftInitializationError(SyftBoxException):
    pass


class SyftBoxAlreadyRunning(SyftBoxException):
    pass
