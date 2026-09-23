"""Domain exceptions. API routes map them to HTTP status codes."""


class NotFound(Exception):
    """Entity not found (maps to HTTP 404)."""


class InvalidState(Exception):
    """Operation not allowed in the current state (maps to HTTP 409)."""


class PermissionDenied(Exception):
    """Authenticated but not allowed (maps to HTTP 403)."""
