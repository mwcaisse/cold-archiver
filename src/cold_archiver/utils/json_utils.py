import uuid
from datetime import datetime
from pathlib import PosixPath


def json_default_handler(val):
    if hasattr(val, "__json__"):
        return val.__json__()

    if isinstance(val, datetime):
        return val.isoformat()

    if isinstance(val, uuid.UUID):
        return str(val)

    if isinstance(val, PosixPath):
        return str(val)

    raise TypeError(f"Cannot serialize {type(val).__name__}")
