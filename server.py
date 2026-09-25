#!/usr/bin/env python3
"""
Server Entrypoint Wrapper.
Delegates to backend.server for execution while maintaining 100% backward compatibility.
"""
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from backend.server import *
from backend.server import app

if __name__ == "__main__":
    import uvicorn
    reload_dirs = [os.path.join(BASE_DIR, "backend"), os.path.join(BASE_DIR, "static")]
    uvicorn.run("backend.server:app", host="0.0.0.0", port=8000, reload=True, reload_dirs=reload_dirs, timeout_graceful_shutdown=5)
