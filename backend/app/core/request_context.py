"""Per-request id, shared by logs, error bodies and the X-Request-ID response header."""

import contextvars
import re
import uuid

_request_id = contextvars.ContextVar("request_id", default="-")
_VALID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


def new_request_id(incoming=None):
    """Reuse a well-formed incoming id (from a proxy), otherwise make one."""
    rid = incoming if incoming and _VALID.match(incoming) else uuid.uuid4().hex
    _request_id.set(rid)
    return rid


def request_id():
    return _request_id.get()
