"""Cross-platform utilities for finding the Hearthstone game window.

Supported platforms
-------------------
* **Windows** – tries ``pygetwindow`` first, then ``win32gui`` as a fallback.
* **Linux**   – uses ``python-xlib`` (pure Python, pip-installable; no system
  package required).  Falls back to ``xdotool`` when python-xlib is absent.
* **macOS**   – uses the ``Quartz`` framework (available on macOS by default).

Title matching
--------------
All platform backends perform a **case-insensitive substring match** against
:data:`HEARTHSTONE_WINDOW_TITLE`.  This means window titles such as
``"Hearthstone - Loading"`` or ``"HEARTHSTONE"`` are recognised correctly.

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

# Substring used for window title matching (case-insensitive).
# Any window whose title contains this string (ignoring case) is considered
# the Hearthstone window, so loading-screen variants are also matched.
HEARTHSTONE_WINDOW_TITLE = "Hearthstone"

# Default game resolution for windowed mode (used as fallback dimensions)
DEFAULT_GAME_WIDTH = 1440
DEFAULT_GAME_HEIGHT = 1080


def _title_matches(title: str) -> bool:
    """Return ``True`` when *title* contains :data:`HEARTHSTONE_WINDOW_TITLE`."""
    return HEARTHSTONE_WINDOW_TITLE.lower() in (title or "").lower()


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

        for win in gw.getAllWindows():
            if _title_matches(win.title):
                bbox = (win.left, win.top, win.width, win.height)
                logger.debug(
                    "Window found via pygetwindow: left=%d top=%d width=%d height=%d",
                    *bbox,
                )
                return bbox
    except Exception as exc:
        logger.debug("pygetwindow lookup failed: %s", exc)

    # Fallback: win32gui (ships with pywin32)
    try:
        import win32gui  # type: ignore

        found: list = []

        def _cb(hwnd: int, _: object) -> None:
            title = win32gui.GetWindowText(hwnd)
            if _title_matches(title):
                found.append(hwnd)

        win32gui.EnumWindows(_cb, None)
        if found:
            rect = win32gui.GetWindowRect(found[0])
            left, top, right, bottom = rect
            bbox = (left, top, right - left, bottom - top)
            logger.debug(
                "Window found via win32gui: left=%d top=%d width=%d height=%d",
                *bbox,
            )
            return bbox
    except Exception as exc:
        logger.debug("win32gui lookup failed: %s", exc)

    return None


def _find_window_linux() -> Optional[Tuple[int, int, int, int]]:
    """Locate the window on Linux using python-xlib (falls back to xdotool)."""
    # Primary: python-xlib – pure Python, pip-installable
    try:
        from Xlib import display as xdisplay  # type: ignore
        from Xlib import X  # type: ignore
        from Xlib import error as xerror  # type: ignore

        dpy = xdisplay.Display()
        root = dpy.screen().root

        def _search(window) -> Optional[Tuple[int, int, int, int]]:
            try:
                name = window.get_wm_name() or ""
            except xerror.XError:
                name = ""
            if _title_matches(name):
                try:
                    geo = window.get_geometry()
                    # Translate coordinates to root (absolute screen position)
                    translated = root.translate_coords(window, 0, 0)
                    bbox = (translated.x, translated.y, geo.width, geo.height)
                    logger.debug(
                        "Window found via python-xlib: left=%d top=%d "
                        "width=%d height=%d",
                        *bbox,
                    )
                    return bbox
                except xerror.XError:
                    pass

            try:
                children = window.query_tree().children
            except xerror.XError:
                children = []
            for child in children:
                result = _search(child)
                if result is not None:
                    return result
            return None

        result = _search(root)
        dpy.close()
        if result is not None:
            return result
    except ImportError:
        logger.debug("python-xlib not available – falling back to xdotool")
    except Exception as exc:
        logger.debug("python-xlib lookup failed: %s", exc)

    # Fallback: xdotool subprocess
    return _find_window_linux_xdotool()


def _find_window_linux_xdotool() -> Optional[Tuple[int, int, int, int]]:
    """Locate the window on Linux using the xdotool command-line tool."""
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

        bbox = (
            int(params.get("X", 0)),
            int(params.get("Y", 0)),
            int(params.get("WIDTH", DEFAULT_GAME_WIDTH)),
            int(params.get("HEIGHT", DEFAULT_GAME_HEIGHT)),
        )
        logger.debug(
            "Window found via xdotool: left=%d top=%d width=%d height=%d",
            *bbox,
        )
        return bbox
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
            if _title_matches(win.get("kCGWindowName") or ""):
                bounds = win["kCGWindowBounds"]
                bbox = (
                    int(bounds["X"]),
                    int(bounds["Y"]),
                    int(bounds["Width"]),
                    int(bounds["Height"]),
                )
                logger.debug(
                    "Window found via Quartz: left=%d top=%d width=%d height=%d",
                    *bbox,
                )
                return bbox
    except Exception as exc:
        logger.debug("Quartz lookup failed: %s", exc)

    return None
