#!/usr/bin/env python3
"""
Simulate Sessions Entrypoint Wrapper.
Delegates to backend.simulate_sessions for execution while maintaining backwards compatibility.
"""
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from backend.simulate_sessions import *
from backend.simulate_sessions import main

if __name__ == "__main__":
    main()
