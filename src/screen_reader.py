"""Screen reader – captures the Hearthstone game window and extracts state.

This module provides a framework for reading the game state from the screen.

Capture backends
----------------
The reader tries the following backends in order and uses the first that is
available:

1. **pyautogui** – DPI-aware, cross-platform, pure-pip (no system packages).
   Installed via ``pip install pyautogui``.
2. **mss** – fast multi-platform screenshot library (original backend, kept
   as fallback).  Installed via ``pip install mss``.

Board detection
---------------
The reader offers two strategies for deciding whether a Hearthstone match is
currently on screen, tried in order:

1. **OpenCV template matching** (preferred) – matches a small reference image
   of the End Turn button (``src/assets/end_turn_button.png``) against the
   captured game window using ``cv2.matchTemplate`` with the
   ``TM_CCOEFF_NORMED`` metric.  A match is declared when the peak
   normalised correlation coefficient exceeds
   :data:`TEMPLATE_MATCH_THRESHOLD` (default 0.75).  This method is
   theme-agnostic, resolution-robust, and unaffected by HUD or loading
   screens.
2. **Brightness probe** (fallback) – samples :data:`BOARD_PROBE_POINTS`
   across the board area and checks mean brightness against
   :data:`BOARD_MIN_MEAN_BRIGHTNESS`.  Used automatically when OpenCV is
   not installed or the template file is missing.

Window-aware capture (1440 × 1080 windowed mode)
-------------------------------------------------
The reader first tries to locate the Hearthstone window via
:mod:`src.window_finder`.  When found, it captures only the game window
region so that all region coordinates are relative to the game content
rather than the full desktop.  This is essential for windowed mode where
the game window does not fill the entire screen.

If the Hearthstone window cannot be found, :meth:`read_game_state` returns
a :class:`GameState` with ``game_active=False`` immediately, and the agent
loop waits before retrying.

Replacing the stubs
-------------------
Override :class:`ScreenReader` and fill in the ``_detect_*`` methods, or
inject a ``card_detector`` callable that accepts a PIL ``Image`` and returns
a list of card dicts (``card_id``, ``name``, ``mana_cost``, ``attack``,
``health``, ``card_type``).
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Tuple

from .window_finder import find_hearthstone_window

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional dependency flags
# ---------------------------------------------------------------------------

try:
    import pyautogui  # type: ignore

    _PYAUTOGUI_AVAILABLE = True
except Exception:  # pragma: no cover – ImportError or KeyError('DISPLAY') on headless
    _PYAUTOGUI_AVAILABLE = False

try:
    import mss  # type: ignore
    import mss.tools  # type: ignore

    _MSS_AVAILABLE = True
except ImportError:  # pragma: no cover
    _MSS_AVAILABLE = False

try:
    from PIL import Image  # type: ignore

    _PIL_AVAILABLE = True
except ImportError:  # pragma: no cover
    _PIL_AVAILABLE = False

try:
    import cv2  # type: ignore
    import numpy as np  # type: ignore

    _CV2_AVAILABLE = True
except ImportError:  # pragma: no cover
    _CV2_AVAILABLE = False

# At least one capture backend must be available.
_CAPTURE_AVAILABLE = (_PYAUTOGUI_AVAILABLE or _MSS_AVAILABLE) and _PIL_AVAILABLE

# ---------------------------------------------------------------------------
# Template asset path
# ---------------------------------------------------------------------------

_ASSETS_DIR = os.path.join(os.path.dirname(__file__), "assets")
_END_TURN_TEMPLATE_PATH = os.path.join(_ASSETS_DIR, "end_turn_button.png")


# ---------------------------------------------------------------------------
# Game-state data class
# ---------------------------------------------------------------------------


@dataclass
class GameState:
    """Snapshot of the Hearthstone game as read from the screen."""

    # True only when a match is currently in progress (board is visible).
    # When False the agent should wait instead of trying to act.
    game_active: bool = False

    # Cards currently in the player's hand (list of raw dicts so they can be
    # instantiated as :class:`~src.card.Card` objects by the agent).
    hand_cards: List[dict] = field(default_factory=list)

    # Player's minions on the board.
    board_minions: List[dict] = field(default_factory=list)

    # Enemy minions on the board.
    enemy_minions: List[dict] = field(default_factory=list)

    # Mana available to the player this turn.
    available_mana: int = 0

    # Hero health values.
    enemy_hero_health: int = 30
    my_hero_health: int = 30

    # Game-over flag and outcome.
    game_over: bool = False
    player_won: Optional[bool] = None


# ---------------------------------------------------------------------------
# Screen region definitions (fractions of the *game window* width/height)
#
# These fractions are calibrated against a 1440 × 1080 Hearthstone window.
# Because the reader crops to the game window first, they remain valid even
# when the desktop resolution differs from 1440 × 1080.
# ---------------------------------------------------------------------------

REGIONS = {
    "hand": {"top_f": 0.80, "left_f": 0.20, "width_f": 0.60, "height_f": 0.18},
    "board_player": {
        "top_f": 0.55,
        "left_f": 0.15,
        "width_f": 0.70,
        "height_f": 0.20,
    },
    "board_enemy": {
        "top_f": 0.25,
        "left_f": 0.15,
        "width_f": 0.70,
        "height_f": 0.20,
    },
    "mana": {"top_f": 0.85, "left_f": 0.85, "width_f": 0.12, "height_f": 0.08},
    "player_hero": {
        "top_f": 0.68,
        "left_f": 0.43,
        "width_f": 0.14,
        "height_f": 0.18,
    },
    "enemy_hero": {
        "top_f": 0.05,
        "left_f": 0.43,
        "width_f": 0.14,
        "height_f": 0.18,
    },
}

# ---------------------------------------------------------------------------
# In-game pixel probe
#
# To distinguish "in a match" from "main menu / deck selection", we sample
# several pixels spread across the board area.  During an active match the
# board is always lit regardless of the board theme (Stormwind, Witchwood,
# Naxxramas, …).  The main-menu background is near-black at these positions.
#
# All coordinates are fractions of the *game window* size.  The six probe
# points are placed in the enemy-board half and the player-board half,
# avoiding the horizontal center where UI elements (End Turn button, hero
# power) may occlude the board texture.
# ---------------------------------------------------------------------------

# Six (x_fraction, y_fraction) probe positions that cover the board area
# while avoiding central UI elements.
BOARD_PROBE_POINTS: list = [
    (0.20, 0.35),  # enemy board – left
    (0.50, 0.30),  # enemy board – center-top (above hero power)
    (0.80, 0.35),  # enemy board – right
    (0.20, 0.65),  # player board – left
    (0.50, 0.60),  # player board – center-top (above hand area)
    (0.80, 0.65),  # player board – right
]

# Mean per-channel brightness (0–255) that must be reached across all probe
# points for the screen to be considered an active match.  The game board is
# always significantly brighter than the near-black main-menu background.
BOARD_MIN_MEAN_BRIGHTNESS: int = 35

# ---------------------------------------------------------------------------
# OpenCV template-matching threshold
#
# Peak normalised cross-correlation coefficient (0–1) that the End Turn button
# template must achieve for the screen to be considered an active match.
# A value of 0.75 gives a good balance between false-positives and misses.
# ---------------------------------------------------------------------------

TEMPLATE_MATCH_THRESHOLD: float = 0.75


# ---------------------------------------------------------------------------
# ScreenReader
# ---------------------------------------------------------------------------


class ScreenReader:
    """Reads the Hearthstone game state from the game window.

    The reader locates the Hearthstone window each frame via
    :func:`~src.window_finder.find_hearthstone_window` and captures only
    that region, so region coordinates are always relative to the game
    content regardless of where the window sits on the desktop.

    Parameters
    ----------
    card_detector:
        Optional callable ``(image: PIL.Image) -> List[dict]`` that detects
        cards in a cropped screen region.  When not provided the built-in
        stub is used (returns an empty list).
    monitor_index:
        Fallback monitor index (1-based, ``1`` = primary) used when the
        Hearthstone window cannot be located by title.
    """

    # Class-level defaults so that objects created with __new__ (e.g. in
    # tests) work without calling __init__.
    _monitor_index: int = 1
    _template_match_threshold: float = TEMPLATE_MATCH_THRESHOLD

    def __init__(
        self,
        card_detector: Optional[Callable] = None,
        monitor_index: int = 1,
        template_match_threshold: float = TEMPLATE_MATCH_THRESHOLD,
    ) -> None:
        if not _CAPTURE_AVAILABLE:
            raise RuntimeError(
                "A screen-capture backend (pyautogui or mss) and Pillow are "
                "required.  Install dependencies with: pip install -r requirements.txt"
            )
        self._card_detector = card_detector or self._detect_cards_stub
        self._monitor_index = monitor_index
        self._template_match_threshold = template_match_threshold

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def capture_game_window(self) -> Tuple[Optional["Image.Image"], bool]:
        """Capture the Hearthstone game window and return ``(image, found)``.

        Tries **pyautogui** first (DPI-aware, no system packages), then falls
        back to **mss** when pyautogui is unavailable.

        * If the window is found its content is returned and ``found=True``.
        * If the window cannot be located, falls back to the full monitor and
          returns ``found=False`` so the caller can mark the state as inactive.
        """
        bbox = find_hearthstone_window()

        if _PYAUTOGUI_AVAILABLE:
            return self._capture_pyautogui(bbox)
        return self._capture_mss(bbox)

    def _capture_pyautogui(
        self, bbox: Optional[Tuple[int, int, int, int]]
    ) -> Tuple["Image.Image", bool]:
        """Capture using pyautogui (DPI-aware, primary backend)."""
        if bbox is not None:
            left, top, width, height = bbox
            logger.debug(
                "Capturing game window via pyautogui: "
                "left=%d top=%d width=%d height=%d",
                left, top, width, height,
            )
            image = pyautogui.screenshot(region=(left, top, width, height))
            return image, True

        logger.debug(
            "Hearthstone window not found – capturing full screen via pyautogui."
        )
        image = pyautogui.screenshot()
        return image, False

    def _capture_mss(
        self, bbox: Optional[Tuple[int, int, int, int]]
    ) -> Tuple["Image.Image", bool]:
        """Capture using mss (fallback backend)."""
        with mss.mss() as sct:
            if bbox is not None:
                left, top, width, height = bbox
                logger.debug(
                    "Capturing game window via mss: "
                    "left=%d top=%d width=%d height=%d",
                    left, top, width, height,
                )
                region = {"left": left, "top": top, "width": width, "height": height}
                screenshot = sct.grab(region)
                image = Image.frombytes(
                    "RGB", screenshot.size, screenshot.bgra, "raw", "BGRX"
                )
                return image, True

            logger.debug(
                "Hearthstone window not found – falling back to full monitor %d.",
                self._monitor_index,
            )
            monitor = sct.monitors[self._monitor_index]
            screenshot = sct.grab(monitor)
            image = Image.frombytes(
                "RGB", screenshot.size, screenshot.bgra, "raw", "BGRX"
            )
            return image, False

    def capture_screen(self) -> "Image.Image":
        """Return a PIL Image of the Hearthstone window (or full monitor).

        Deprecated alias kept for backwards compatibility; prefer
        :meth:`capture_game_window`.
        """
        image, _ = self.capture_game_window()
        return image  # type: ignore[return-value]

    def crop_region(
        self, screen: "Image.Image", region_name: str
    ) -> "Image.Image":
        """Crop a named region from *screen* (which must be the game window)."""
        reg = REGIONS[region_name]
        w, h = screen.size
        left = int(reg["left_f"] * w)
        top = int(reg["top_f"] * h)
        right = left + int(reg["width_f"] * w)
        bottom = top + int(reg["height_f"] * h)
        return screen.crop((left, top, right, bottom))

    def read_game_state(self) -> GameState:
        """Capture the game window and return the current :class:`GameState`.

        Returns a :class:`GameState` with ``game_active=False`` immediately
        when the Hearthstone window cannot be found, so the agent loop can
        wait without performing any actions.
        """
        logger.debug("read_game_state: capturing game window…")
        screen, window_found = self.capture_game_window()
        state = GameState()

        if not window_found:
            logger.debug("Hearthstone window not found.")
            return state  # game_active stays False

        w, h = screen.size
        logger.debug("Game window captured: %d × %d px.", w, h)

        if not self._detect_game_active(screen):
            logger.debug("Hearthstone window found but game board not detected.")
            return state  # game_active stays False

        state.game_active = True
        state.available_mana = self._read_mana(screen)
        state.my_hero_health = self._read_hero_health(screen, enemy=False)
        state.enemy_hero_health = self._read_hero_health(screen, enemy=True)

        logger.debug(
            "Game active – mana=%d  my_hp=%d  enemy_hp=%d",
            state.available_mana,
            state.my_hero_health,
            state.enemy_hero_health,
        )

        hand_image = self.crop_region(screen, "hand")
        board_image = self.crop_region(screen, "board_player")
        enemy_image = self.crop_region(screen, "board_enemy")

        state.hand_cards = self._card_detector(hand_image)
        state.board_minions = self._card_detector(board_image)
        state.enemy_minions = self._card_detector(enemy_image)

        logger.debug(
            "Detected cards – hand=%d  own_board=%d  enemy_board=%d",
            len(state.hand_cards),
            len(state.board_minions),
            len(state.enemy_minions),
        )

        state.game_over = self._detect_game_over(screen)
        if state.game_over:
            state.player_won = self._detect_winner(screen)
            logger.debug(
                "Game-over screen detected. player_won=%s", state.player_won
            )

        return state

    # ------------------------------------------------------------------ #
    # Detection stubs – replace with real implementations                 #
    # ------------------------------------------------------------------ #

    def _detect_game_active(self, screen: "Image.Image") -> bool:
        """Determine whether an active match is currently on screen.

        **Strategy 1 – OpenCV template matching (preferred)**
        Loads the End Turn button reference image from
        ``src/assets/end_turn_button.png`` and searches for it in *screen*
        using ``cv2.matchTemplate`` with the ``TM_CCOEFF_NORMED`` metric.
        Returns ``True`` when the peak correlation coefficient reaches
        :data:`TEMPLATE_MATCH_THRESHOLD`.  This method is board-theme
        agnostic, DPI-robust, and unaffected by splash screens or the lobby
        (neither of which shows the End Turn button).

        **Strategy 2 – Brightness probe (fallback)**
        Used when ``opencv-python`` is not installed or the template file is
        missing.  Samples :data:`BOARD_PROBE_POINTS` across the board area
        and returns ``True`` when mean per-channel brightness exceeds
        :data:`BOARD_MIN_MEAN_BRIGHTNESS`.

        Parameters
        ----------
        screen:
            A PIL Image already cropped to the game window.
        """
        if _CV2_AVAILABLE and os.path.isfile(_END_TURN_TEMPLATE_PATH):
            return self._detect_game_active_template(screen)
        return self._detect_game_active_brightness(screen)

    def _detect_game_active_template(self, screen: "Image.Image") -> bool:
        """Template-matching implementation of :meth:`_detect_game_active`."""
        template_bgr = cv2.imread(_END_TURN_TEMPLATE_PATH)
        if template_bgr is None:
            logger.debug(
                "_detect_game_active: could not load template %s – "
                "falling back to brightness probe.",
                _END_TURN_TEMPLATE_PATH,
            )
            return self._detect_game_active_brightness(screen)

        screen_np = np.array(screen)
        screen_bgr = cv2.cvtColor(screen_np, cv2.COLOR_RGB2BGR)

        # Scale the template down proportionally when it is larger than the
        # game window (shouldn't happen in practice, but guards against it).
        th, tw = template_bgr.shape[:2]
        sh, sw = screen_bgr.shape[:2]
        if tw > sw or th > sh:
            scale = min(sw / tw, sh / th) * 0.9
            template_bgr = cv2.resize(
                template_bgr,
                (max(1, int(tw * scale)), max(1, int(th * scale))),
                interpolation=cv2.INTER_AREA,
            )

        result = cv2.matchTemplate(screen_bgr, template_bgr, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, _ = cv2.minMaxLoc(result)
        active = bool(max_val >= self._template_match_threshold)
        logger.debug(
            "_detect_game_active (template): confidence=%.3f  threshold=%.2f  "
            "active=%s",
            max_val,
            self._template_match_threshold,
            active,
        )
        return active

    def _detect_game_active_brightness(self, screen: "Image.Image") -> bool:
        """Brightness-probe fallback for :meth:`_detect_game_active`."""
        w, h = screen.size
        total_brightness: float = 0.0
        n = len(BOARD_PROBE_POINTS)
        for x_f, y_f in BOARD_PROBE_POINTS:
            px = int(x_f * w)
            py = int(y_f * h)
            try:
                r, g, b = screen.getpixel((px, py))
            except Exception:
                n -= 1
                continue
            total_brightness += (r + g + b) / 3

        if n == 0:
            logger.debug("_detect_game_active: no probe points could be sampled.")
            return False
        mean_brightness = total_brightness / n
        active = mean_brightness >= BOARD_MIN_MEAN_BRIGHTNESS
        logger.debug(
            "_detect_game_active (brightness): mean_brightness=%.1f  "
            "threshold=%d  active=%s",
            mean_brightness,
            BOARD_MIN_MEAN_BRIGHTNESS,
            active,
        )
        return active

    def _read_mana(self, screen: "Image.Image") -> int:
        """Extract current mana from *screen*.

        Stub returns 10 (full mana); replace with OCR on the mana crystal
        region.
        """
        return 10

    def _read_hero_health(
        self, screen: "Image.Image", enemy: bool = False
    ) -> int:
        """Extract a hero's current health from *screen*.

        Stub returns 30; replace with OCR on the hero portrait region.
        """
        return 30

    def _detect_game_over(self, screen: "Image.Image") -> bool:
        """Detect whether the game has ended (victory/defeat banner visible).

        Stub returns ``False``; replace with template matching.
        """
        return False

    def _detect_winner(self, screen: "Image.Image") -> Optional[bool]:
        """Detect who won after the game ended.

        Returns ``True`` if the player won, ``False`` if they lost, ``None``
        if unclear.  Stub returns ``None``.
        """
        return None

    @staticmethod
    def _detect_cards_stub(image: "Image.Image") -> List[dict]:
        """Stub card detector – returns an empty list.

        Replace by passing a real ``card_detector`` callable to the
        :class:`ScreenReader` constructor.
        """
        return []
