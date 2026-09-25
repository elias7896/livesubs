#!/usr/bin/env python3
"""
Worker Entrypoint Wrapper.
Delegates to backend.worker for execution while maintaining 100% backward compatibility.
"""
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from backend.worker import *
from backend.worker import main

if __name__ == "__main__":
    main()
