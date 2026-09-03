"""Puts ../shared on sys.path so `import ai_loop` (shared/ai_loop.py) works under
pytest, exactly as almanac/app.py does at runtime."""

import os
import sys

_SHARED = os.path.join(os.path.dirname(__file__), "..", "shared")
if os.path.isdir(_SHARED) and _SHARED not in sys.path:
    sys.path.insert(0, _SHARED)
