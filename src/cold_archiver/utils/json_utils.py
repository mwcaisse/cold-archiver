from datetime import datetime


def json_default_handler(val):
    if hasattr(val, "__json__"):
        return val.__json__()

    if isinstance(val, datetime):
        return val.isoformat()

    return TypeError(f"Cannot serialize {type(val).__name__}")
