# Database connection and models
# database.py
import json, threading, os
from typing import Any
from config import CFG

_lock = threading.Lock()

def _ensure(path, default):
    if not os.path.exists(path):
        with open(path, "w") as f:
            json.dump(default, f, indent=2)
        return default.copy()
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        # recover by replacing with default
        with open(path, "w") as f:
            json.dump(default, f, indent=2)
        return default.copy()

def read(name: str, default: Any):
    path = CFG["FILES"][name]
    return _ensure(path, default)

def write(name: str, data: Any):
    path = CFG["FILES"][name]
    with _lock:
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2, default=str)
        os.replace(tmp, path)

def next_id(items: list) -> int:
    return (max((i.get("id",0) for i in items), default=0) + 1) if items else 1