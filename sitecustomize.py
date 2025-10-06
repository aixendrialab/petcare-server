# sitecustomize.py
# Auto-imported by Python at startup (via the 'site' module).
# Windows-only tweak for psycopg3 async; gated by env so prod/Linux is untouched.

import os
import sys
import asyncio

if sys.platform.startswith("win") and os.getenv("PC_FORCE_SELECTOR_LOOP") == "1":
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    except AttributeError:
        # Not Windows / older Python — ignore
        pass
