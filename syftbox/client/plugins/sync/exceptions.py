class FatalSyncError(Exception):
    """Base exception to signal sync should be interrupted."""

    pass


class SyncEnvironmentError(FatalSyncError):
    """the sync environment is corrupted (e.g. sync folder deleted), syncing cannot continue."""

    pass
