#!/usr/bin/env python3
"""skillwire dispatcher for the PostToolUse hook. Always exits 0."""
import os
import sys

try:
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
    from skillwire.dispatch import main
except BaseException:  # even a broken install must not block Claude
    sys.exit(0)

sys.exit(main("PostToolUse"))
