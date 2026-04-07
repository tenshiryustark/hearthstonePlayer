"""Persistence layer for card inner values.

Card inner values are stored in a JSON file so that they survive across
multiple game sessions.  After every game the played-card values are
adjusted:

* **Win**  – each played card's value is increased by ``WIN_DELTA``.
* **Loss** – each played card's value is decreased by ``LOSE_DELTA``
  (clamped to ``MIN_VALUE`` so values never go negative).
"""
import json
import os
from typing import Dict, List

DEFAULT_INNER_VALUE: float = 1.0
WIN_DELTA: float = 0.1
LOSE_DELTA: float = 0.05
MIN_VALUE: float = 0.0


class CardValueStore:
    """Loads, updates, and persists inner values for every card.

    Parameters
    ----------
    store_path:
        Path to the JSON file used to persist card values.  It is
        created automatically if it does not yet exist.
    """

    def __init__(self, store_path: str = "card_values.json") -> None:
        self.store_path = store_path
        self._values: Dict[str, float] = {}
        self._load()

    # ------------------------------------------------------------------ #
    # Internal I/O                                                         #
    # ------------------------------------------------------------------ #

    def _load(self) -> None:
        """Load values from disk (silently succeeds when file is absent)."""
        if os.path.exists(self.store_path):
            with open(self.store_path, "r", encoding="utf-8") as fh:
                self._values = json.load(fh)

    def save(self) -> None:
        """Persist all current values to disk."""
        with open(self.store_path, "w", encoding="utf-8") as fh:
            json.dump(self._values, fh, indent=2)

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def get_value(self, card_id: str) -> float:
        """Return the inner value for *card_id* (default if not yet seen)."""
        return self._values.get(card_id, DEFAULT_INNER_VALUE)

    def set_value(self, card_id: str, value: float) -> None:
        """Overwrite the inner value for *card_id* and persist."""
        self._values[card_id] = max(MIN_VALUE, value)
        self.save()

    def update_value(self, card_id: str, won: bool) -> None:
        """Adjust the inner value of a single card after a game.

        Parameters
        ----------
        card_id:
            Identifier of the card to update.
        won:
            ``True`` if the game was won, ``False`` otherwise.
        """
        current = self.get_value(card_id)
        if won:
            self._values[card_id] = current + WIN_DELTA
        else:
            self._values[card_id] = max(MIN_VALUE, current - LOSE_DELTA)
        self.save()

    def apply_game_result(self, played_card_ids: List[str], won: bool) -> None:
        """Batch-update values for all cards played during a game.

        Parameters
        ----------
        played_card_ids:
            List of ``card_id`` strings for every card played this game.
        won:
            ``True`` if the game was won, ``False`` otherwise.
        """
        for card_id in played_card_ids:
            current = self.get_value(card_id)
            if won:
                self._values[card_id] = current + WIN_DELTA
            else:
                self._values[card_id] = max(MIN_VALUE, current - LOSE_DELTA)
        self.save()

    def all_values(self) -> Dict[str, float]:
        """Return a copy of the entire value mapping."""
        return dict(self._values)
