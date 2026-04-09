"""Cross-platform utilities for finding the Hearthstone game window.

Supported platforms
-------------------
* **Windows** – tries ``pygetwindow`` first, then ``win32gui`` as a fallback.
* **Linux**   – uses ``xdotool`` (must be installed: ``apt install xdotool``).
* **macOS**   – uses the ``Quartz`` framework (available on macOS by default).

The main public function is :func:`find_hearthstone_window`, which returns
the window bounding box ``(left, top, width, height)`` in screen pixels, or
``None`` when the window cannot be found.
"""
from __future__ import annotations

import logging
import subprocess
import sys
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# Exact window title used by Hearthstone on all platforms
HEARTHSTONE_WINDOW_TITLE = "Hearthstone"

# Default game resolution for windowed mode (used as fallback dimensions)
DEFAULT_GAME_WIDTH = 1440
DEFAULT_GAME_HEIGHT = 1080


def find_hearthstone_window() -> Optional[Tuple[int, int, int, int]]:
    """Return ``(left, top, width, height)`` for the Hearthstone window.

    Returns ``None`` when the window is not found or when the current
    platform is not supported.
    """
    if sys.platform == "win32":
        return _find_window_win32()
    if sys.platform.startswith("linux"):
        return _find_window_linux()
    if sys.platform == "darwin":
        return _find_window_macos()

    logger.warning(
        "Window detection is not supported on platform '%s'. "
        "Falling back to full-monitor capture.",
        sys.platform,
    )
    return None


# ---------------------------------------------------------------------------
# Platform implementations
# ---------------------------------------------------------------------------


def _find_window_win32() -> Optional[Tuple[int, int, int, int]]:
    """Locate the window on Windows using pygetwindow or win32gui."""
    # Primary: pygetwindow (lightweight, pip-installable)
    try:
        import pygetwindow as gw  # type: ignore

        wins = gw.getWindowsWithTitle(HEARTHSTONE_WINDOW_TITLE)
        if wins:
            win = wins[0]
            return (win.left, win.top, win.width, win.height)
    except Exception as exc:
        logger.debug("pygetwindow lookup failed: %s", exc)

    # Fallback: win32gui (ships with pywin32)
    try:
        import win32gui  # type: ignore

        hwnd = win32gui.FindWindow(None, HEARTHSTONE_WINDOW_TITLE)
        if hwnd:
            rect = win32gui.GetWindowRect(hwnd)
            left, top, right, bottom = rect
            return (left, top, right - left, bottom - top)
    except Exception as exc:
        logger.debug("win32gui lookup failed: %s", exc)

    return None


def _find_window_linux() -> Optional[Tuple[int, int, int, int]]:
    """Locate the window on Linux using xdotool."""
    try:
        search = subprocess.run(
            ["xdotool", "search", "--name", HEARTHSTONE_WINDOW_TITLE],
            capture_output=True,
            text=True,
            timeout=5,
        )
        win_ids = search.stdout.strip().splitlines()
        if not win_ids:
            return None

        geo = subprocess.run(
            ["xdotool", "getwindowgeometry", "--shell", win_ids[0]],
            capture_output=True,
            text=True,
            timeout=5,
        )
        params: dict = {}
        for line in geo.stdout.splitlines():
            if "=" in line:
                key, val = line.split("=", 1)
                params[key.strip()] = val.strip()

        return (
            int(params.get("X", 0)),
            int(params.get("Y", 0)),
            int(params.get("WIDTH", DEFAULT_GAME_WIDTH)),
            int(params.get("HEIGHT", DEFAULT_GAME_HEIGHT)),
        )
    except FileNotFoundError:
        logger.debug("xdotool not found – install with: apt install xdotool")
    except Exception as exc:
        logger.debug("xdotool lookup failed: %s", exc)

    return None


def _find_window_macos() -> Optional[Tuple[int, int, int, int]]:
    """Locate the window on macOS using the Quartz framework."""
    try:
        import Quartz  # type: ignore

        window_list = Quartz.CGWindowListCopyWindowInfo(
            Quartz.kCGWindowListOptionOnScreenOnly, Quartz.kCGNullWindowID
        )
        for win in window_list:
            if HEARTHSTONE_WINDOW_TITLE in (win.get("kCGWindowName") or ""):
                bounds = win["kCGWindowBounds"]
                return (
                    int(bounds["X"]),
                    int(bounds["Y"]),
                    int(bounds["Width"]),
                    int(bounds["Height"]),
                )
    except Exception as exc:
        logger.debug("Quartz lookup failed: %s", exc)

    return None
