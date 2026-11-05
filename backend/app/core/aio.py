"""Event-loop helpers.

Playwright launches a browser subprocess, which on Windows requires the
Proactor event loop.  It is already the default on modern Python, so we only
switch policy when something else selected a non-Proactor loop, and we do it
without emitting the 3.16 deprecation warning.
"""
from __future__ import annotations

import asyncio
import sys
import warnings


def ensure_proactor_loop() -> None:
    if sys.platform != "win32":
        return
    policy_cls = getattr(asyncio, "WindowsProactorEventLoopPolicy", None)
    if policy_cls is None:
        return
    current = asyncio.get_event_loop_policy()
    if isinstance(current, policy_cls):
        return
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        asyncio.set_event_loop_policy(policy_cls())
