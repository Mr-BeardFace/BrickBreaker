#!/usr/bin/env python3
"""BrickBreaker — Databricks red team enumeration tool"""

import sys

try:
    from bb.dispatch import dispatch
except ImportError as e:
    print(f"Import error: {e}\nRun: pip install -r requirements.txt")
    sys.exit(1)

if __name__ == "__main__":
    dispatch(sys.argv[1:])
