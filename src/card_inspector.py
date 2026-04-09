"""Card inspector – identifies the card under the mouse cursor in real time.

When the user hovers the mouse over a card position in the hand or on the
board, the inspector crops that card's slot from the live game window,
passes it to the configured card detector, and prints human-readable card
information.  If no card is detected at that position it prints
``"No card found"``.

Typical usage::

    from src.screen_reader import ScreenReader
    from src.card_inspector import CardInspector

    inspector = CardInspector(ScreenReader())
    inspector.run()          # blocks; Ctrl-C to stop

The inspector is theme- and resolution-independent because it relies on the
same fractional :data:`~src.screen_reader.REGIONS` definitions used by the
:class:`~src.screen_reader.ScreenReader`.
"""
from __future__ import annotations

import logging
from typing import Callable, List, Optional, Tuple

from .screen_reader import REGIONS, ScreenReader
from .window_finder import find_hearthstone_window

logger = logging.getLogger(__name__)

# Maximum number of card slots assumed for each region.  These are the
# Hearthstone hard limits: 10 cards in hand, 7 minions per board side.
HAND_MAX_SLOTS: int = 10
BOARD_MAX_SLOTS: int = 7

# Ordered list of regions that are checked for card hover detection.
# "hand" and the two board sides are the only interactive card areas.
_CARD_REGIONS: Tuple[str, ...] = ("hand", "board_player", "board_enemy")


class CardInspector:
    """Detects and identifies the card the mouse is hovering over.

    Parameters
    ----------
    screen_reader:
        A :class:`~src.screen_reader.ScreenReader` instance used to capture
        the game window.
    card_detector:
        Optional callable ``(image: PIL.Image) -> List[dict]`` that returns
        card dicts for an image crop.  When omitted the stub that always
        returns an empty list is used, so every hover shows "No card found"
        until a real detector is wired in.
    """

    def __init__(
        self,
        screen_reader: ScreenReader,
        card_detector: Optional[Callable] = None,
    ) -> None:
        self._screen_reader = screen_reader
        self._card_detector: Callable = (
            card_detector or ScreenReader._detect_cards_stub
        )

    # ------------------------------------------------------------------ #
    # Slot geometry helpers                                                #
    # ------------------------------------------------------------------ #

    def get_card_slot(
        self,
        win_x: int,
        win_y: int,
        win_w: int,
        win_h: int,
    ) -> Optional[Tuple[str, int]]:
        """Return ``(region_name, slot_index)`` for a cursor inside the window.

        Parameters
        ----------
        win_x, win_y:
            Mouse position expressed in pixels **relative to the game window**
            top-left corner (not absolute screen coordinates).
        win_w, win_h:
            Dimensions of the game window in pixels.

        Returns
        -------
        tuple or None
            ``(region_name, slot_index)`` where *region_name* is one of
            ``"hand"``, ``"board_player"``, ``"board_enemy"`` and
            *slot_index* is 0-based from the left.  Returns ``None`` when
            the cursor is not over any card area.
        """
        x_f = win_x / win_w
        y_f = win_y / win_h

        for region_name in _CARD_REGIONS:
            reg = REGIONS[region_name]
            r_left = reg["left_f"]
            r_top = reg["top_f"]
            r_right = r_left + reg["width_f"]
            r_bottom = r_top + reg["height_f"]

            if r_left <= x_f <= r_right and r_top <= y_f <= r_bottom:
                max_slots = (
                    HAND_MAX_SLOTS
                    if region_name == "hand"
                    else BOARD_MAX_SLOTS
                )
                rel_x = (x_f - r_left) / reg["width_f"]
                slot = min(int(rel_x * max_slots), max_slots - 1)
                return region_name, slot

        return None

    def crop_card_slot(
        self,
        screen: "Image.Image",  # type: ignore[name-defined]  # PIL available at runtime
        region_name: str,
        slot: int,
    ) -> "Image.Image":  # type: ignore[name-defined]
        """Crop a single card slot from *screen*.

        The region is divided into equal-width columns (one per maximum slot
        count for that region).  The column at *slot* is returned.

        Parameters
        ----------
        screen:
            The full game-window image captured by the screen reader.
        region_name:
            One of ``"hand"``, ``"board_player"``, ``"board_enemy"``.
        slot:
            0-based column index within the region.
        """
        reg = REGIONS[region_name]
        w, h = screen.size
        max_slots = HAND_MAX_SLOTS if region_name == "hand" else BOARD_MAX_SLOTS

        region_left = int(reg["left_f"] * w)
        region_top = int(reg["top_f"] * h)
        region_width = int(reg["width_f"] * w)
        region_height = int(reg["height_f"] * h)

        slot_width = region_width // max_slots
        left = region_left + slot * slot_width
        right = left + slot_width

        return screen.crop((left, region_top, right, region_top + region_height))

    # ------------------------------------------------------------------ #
    # Card identification                                                  #
    # ------------------------------------------------------------------ #

    def identify_card_at_mouse(
        self,
        mouse_x: int,
        mouse_y: int,
    ) -> Optional[str]:
        """Return a human-readable description of the card under the cursor.

        Parameters
        ----------
        mouse_x, mouse_y:
            Absolute screen coordinates of the mouse cursor.

        Returns
        -------
        str or None
            A description string such as::

                [hand slot 2] Fireball | Spell | Mana:4 ATK:- HP:-

            or::

                [hand slot 2] No card found

            Returns ``None`` when the cursor is outside the game window or
            not over any card area, so callers can suppress redundant output.
        """
        window_bbox = find_hearthstone_window()
        if window_bbox is None:
            logger.debug("Hearthstone window not found.")
            return None

        win_left, win_top, win_w, win_h = window_bbox
        win_x = mouse_x - win_left
        win_y = mouse_y - win_top

        if win_x < 0 or win_y < 0 or win_x >= win_w or win_y >= win_h:
            return None  # cursor is outside the game window

        slot_info = self.get_card_slot(win_x, win_y, win_w, win_h)
        if slot_info is None:
            return None  # not over a card area

        region_name, slot = slot_info

        screen, found = self._screen_reader.capture_game_window()
        if not found:
            return None

        card_image = self.crop_card_slot(screen, region_name, slot)
        cards: List[dict] = self._card_detector(card_image)

        if not cards:
            return f"[{region_name} slot {slot}] No card found"

        return self._format_card(region_name, slot, cards[0])

    @staticmethod
    def _format_card(region_name: str, slot: int, card: dict) -> str:
        """Format a card dict as a human-readable one-line description.

        Parameters
        ----------
        region_name:
            Region where the card was found (``"hand"``, ``"board_player"``,
            or ``"board_enemy"``).
        slot:
            0-based slot index within the region.
        card:
            Dict with optional keys ``name``, ``card_type``, ``mana_cost``,
            ``attack``, ``health``.  Missing values are shown as ``-``.
        """
        name = card.get("name") or "Unknown"
        card_type = card.get("card_type") or "-"
        mana = card.get("mana_cost", "-")
        attack = card.get("attack", "-")
        health = card.get("health", "-")
        return (
            f"[{region_name} slot {slot}] {name} | {card_type} "
            f"| Mana:{mana} ATK:{attack} HP:{health}"
        )

    # ------------------------------------------------------------------ #
    # Live-inspection loop                                                 #
    # ------------------------------------------------------------------ #

    def run(self) -> None:
        """Start the mouse-tracking inspector loop.

        Listens for mouse-move events via ``pynput``.  Each time the cursor
        enters a card slot, the card info (or "No card found") is printed to
        the log.  Output is suppressed when the cursor stays within the same
        slot to avoid flooding the log.

        Press Ctrl-C to stop.
        """
        try:
            from pynput import mouse  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "pynput is required for the card inspector. "
                "Install it with: pip install pynput"
            ) from exc

        logger.info(
            "Card Inspector started – hover over cards in your hand or on "
            "the board.  Press Ctrl-C to stop."
        )

        _last_description: list = [None]

        def _on_move(x: int, y: int) -> None:
            description = self.identify_card_at_mouse(x, y)
            if description is not None and description != _last_description[0]:
                _last_description[0] = description
                logger.info("Card Inspector: %s", description)
            elif description is None:
                # Reset so the next card area entry is always logged
                _last_description[0] = None

        try:
            with mouse.Listener(on_move=_on_move) as listener:
                listener.join()
        except KeyboardInterrupt:
            logger.info("Card Inspector stopped by user.")
