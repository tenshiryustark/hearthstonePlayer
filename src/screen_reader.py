"""Screen reader – captures the Hearthstone game window and extracts state.

This module provides a framework for reading the game state from the screen.
It uses ``mss`` for fast multi-platform screenshot capture and ``Pillow``
for image processing.  Actual card/UI recognition (OCR, template matching,
or a neural model) is plugged in via the ``_detect_*`` helper stubs.

Window-aware capture (1920 × 1080 windowed mode)
-------------------------------------------------
The reader first tries to locate the Hearthstone window via
:mod:`src.window_finder`.  When found, it captures only the game window
region so that all region coordinates are relative to the game content
rather than the full desktop.  This is essential for windowed mode where
the game window does not fill the entire screen.

If the Hearthstone window cannot be found, :meth:`read_game_state` returns
a :class:`GameState` with ``game_active=False`` immediately, and the agent
loop waits before retrying.

Active-match detection
----------------------
Once the window is captured, :meth:`ScreenReader._detect_game_active` checks
whether the board is visible by sampling several probe pixels across both
halves of the board and measuring their average brightness.  This check is
board-theme agnostic — it does not require a specific color — so it works
with all Hearthstone board themes (Stormwind, Witchwood, Naxxramas, etc.).

Replacing the stubs
-------------------
Override :class:`ScreenReader` and fill in the ``_detect_*`` methods, or
inject a ``card_detector`` callable that accepts a PIL ``Image`` and returns
a list of card dicts (``card_id``, ``name``, ``mana_cost``, ``attack``,
``health``, ``card_type``).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Tuple

from .window_finder import find_hearthstone_window

logger = logging.getLogger(__name__)

try:
    import mss  # type: ignore
    import mss.tools  # type: ignore
    from PIL import Image  # type: ignore

    _CAPTURE_AVAILABLE = True
except ImportError:  # pragma: no cover
    _CAPTURE_AVAILABLE = False


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
# These fractions are calibrated against a 1920 × 1080 Hearthstone window.
# Because the reader crops to the game window first, they remain valid even
# when the desktop resolution differs from 1920 × 1080.
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

    def __init__(
        self,
        card_detector: Optional[Callable] = None,
        monitor_index: int = 1,
    ) -> None:
        if not _CAPTURE_AVAILABLE:
            raise RuntimeError(
                "mss and Pillow are required for screen capture. "
                "Install dependencies with: pip install -r requirements.txt"
            )
        self._card_detector = card_detector or self._detect_cards_stub
        self._monitor_index = monitor_index

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def capture_game_window(self) -> Tuple[Optional["Image.Image"], bool]:
        """Capture the Hearthstone game window and return ``(image, found)``.

        * If the window is found its content is returned and ``found=True``.
        * If the window cannot be located, falls back to the full monitor and
          returns ``found=False`` so the caller can mark the state as inactive.
        """
        bbox = find_hearthstone_window()
        with mss.mss() as sct:
            if bbox is not None:
                left, top, width, height = bbox
                region = {
                    "left": left,
                    "top": top,
                    "width": width,
                    "height": height,
                }
                screenshot = sct.grab(region)
                image = Image.frombytes(
                    "RGB", screenshot.size, screenshot.bgra, "raw", "BGRX"
                )
                return image, True

            # Fallback: full monitor capture
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
        screen, window_found = self.capture_game_window()
        state = GameState()

        if not window_found:
            logger.debug("Hearthstone window not found.")
            return state  # game_active stays False

        if not self._detect_game_active(screen):
            logger.debug("Hearthstone window found but game board not detected.")
            return state  # game_active stays False

        state.game_active = True
        state.available_mana = self._read_mana(screen)
        state.my_hero_health = self._read_hero_health(screen, enemy=False)
        state.enemy_hero_health = self._read_hero_health(screen, enemy=True)

        hand_image = self.crop_region(screen, "hand")
        board_image = self.crop_region(screen, "board_player")
        enemy_image = self.crop_region(screen, "board_enemy")

        state.hand_cards = self._card_detector(hand_image)
        state.board_minions = self._card_detector(board_image)
        state.enemy_minions = self._card_detector(enemy_image)

        state.game_over = self._detect_game_over(screen)
        if state.game_over:
            state.player_won = self._detect_winner(screen)

        return state

    # ------------------------------------------------------------------ #
    # Detection stubs – replace with real implementations                 #
    # ------------------------------------------------------------------ #

    def _detect_game_active(self, screen: "Image.Image") -> bool:
        """Determine whether an active match is currently on screen.

        Samples :data:`BOARD_PROBE_POINTS` — six positions spread across the
        board area — and computes the mean per-channel brightness.  An active
        match always has a lit board regardless of the board theme (Stormwind,
        Witchwood, Naxxramas, …), while the main menu and lobby screens are
        near-black at those positions.

        The check is theme-agnostic: it does **not** require a specific color
        (e.g. green).  Only overall brightness matters.

        Override this method (or subclass :class:`ScreenReader`) to use a
        more precise detection method such as template matching against the
        end-turn button or the mana crystal bar.

        Parameters
        ----------
        screen:
            A PIL Image already cropped to the game window.
        """
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
            return False
        mean_brightness = total_brightness / n
        return mean_brightness >= BOARD_MIN_MEAN_BRIGHTNESS

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
