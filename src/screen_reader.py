"""Screen reader – captures the Hearthstone game window and extracts state.

This module provides a framework for reading the game state from the screen.
It uses ``mss`` for fast multi-platform screenshot capture and ``Pillow``
for image processing.  Actual card/UI recognition (OCR, template matching,
or a neural model) is plugged in via the ``_detect_*`` helper stubs.

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
from typing import Callable, List, Optional

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
# Screen region definitions (fractions of screen width/height)
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
# ScreenReader
# ---------------------------------------------------------------------------


class ScreenReader:
    """Reads the Hearthstone game state from the primary monitor.

    Parameters
    ----------
    card_detector:
        Optional callable ``(image: PIL.Image) -> List[dict]`` that detects
        cards in a cropped screen region.  When not provided the built-in
        stub is used (returns an empty list).
    monitor_index:
        Index of the monitor to capture (1-based, ``1`` = primary).
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

    def capture_screen(self) -> "Image.Image":
        """Return a full-screen PIL Image of the primary monitor."""
        with mss.mss() as sct:
            monitor = sct.monitors[self._monitor_index]
            screenshot = sct.grab(monitor)
            return Image.frombytes(
                "RGB", screenshot.size, screenshot.bgra, "raw", "BGRX"
            )

    def crop_region(
        self, screen: "Image.Image", region_name: str
    ) -> "Image.Image":
        """Crop a named region from *screen*."""
        reg = REGIONS[region_name]
        w, h = screen.size
        left = int(reg["left_f"] * w)
        top = int(reg["top_f"] * h)
        right = left + int(reg["width_f"] * w)
        bottom = top + int(reg["height_f"] * h)
        return screen.crop((left, top, right, bottom))

    def read_game_state(self) -> GameState:
        """Capture the screen and return the current :class:`GameState`.

        This is the main entry point for the agent loop.
        """
        screen = self.capture_screen()
        state = GameState()

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
