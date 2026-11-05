class SetupError(Exception):
    """Configuration, permissions or requested operation cannot be satisfied."""


class RuntimeBusyError(SetupError):
    """Another runtime owns this database or developer app on this host/user."""
