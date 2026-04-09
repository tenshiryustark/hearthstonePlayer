"""Main orchestration module for the Hearthstone automated player agent.

Usage (from the repository root)::

    python -m src.agent

The agent continuously polls the screen, reads the game state, plans and
logs actions, and updates card values when a game ends.
"""
from __future__ import annotations

import logging
import time
from typing import List, Optional

from .card import Card
from .card_value_store import CardValueStore
from .decision_engine import DecisionEngine
from .screen_reader import GameState, ScreenReader

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
)
logger = logging.getLogger(__name__)


class HearthstoneAgent:
    """Automated Hearthstone player agent.

    Parameters
    ----------
    value_store_path:
        Path to the JSON file used to persist card inner values.
    poll_interval:
        Seconds to wait between screen-read cycles.
    screen_reader:
        Optional pre-constructed :class:`~src.screen_reader.ScreenReader`.
        Mainly useful for testing.
    """

    def __init__(
        self,
        value_store_path: str = "card_values.json",
        poll_interval: float = 2.0,
        screen_reader: Optional[ScreenReader] = None,
    ) -> None:
        self.value_store = CardValueStore(value_store_path)
        self.engine = DecisionEngine()
        self._poll_interval = poll_interval
        self._screen_reader = screen_reader  # injected or created lazily
        self._played_this_game: List[str] = []
        logger.debug(
            "HearthstoneAgent initialised – value_store=%s  poll_interval=%.1fs",
            value_store_path,
            poll_interval,
        )

    # ------------------------------------------------------------------ #
    # Screen reader (lazy init so we don't require mss at import time)    #
    # ------------------------------------------------------------------ #

    @property
    def screen_reader(self) -> ScreenReader:
        if self._screen_reader is None:
            self._screen_reader = ScreenReader()
        return self._screen_reader

    # ------------------------------------------------------------------ #
    # Value enrichment                                                     #
    # ------------------------------------------------------------------ #

    def enrich_cards_with_values(self, cards: List[Card]) -> List[Card]:
        """Apply persisted inner values to *cards* in-place and return them."""
        for card in cards:
            card.inner_value = self.value_store.get_value(card.card_id)
        return cards

    # ------------------------------------------------------------------ #
    # Turn execution                                                       #
    # ------------------------------------------------------------------ #

    def execute_turn(self, state: GameState) -> None:
        """Plan and log actions for the current turn.

        In a fully integrated implementation this method would also send
        the mouse/keyboard events to the game window.  Here it logs the
        intended actions so that the framework can be tested headlessly.
        """
        logger.info(
            "Turn start – mana=%d  hand=%d  own_board=%d  enemy_board=%d  "
            "my_hp=%d  enemy_hp=%d",
            state.available_mana,
            len(state.hand_cards),
            len(state.board_minions),
            len(state.enemy_minions),
            state.my_hero_health,
            state.enemy_hero_health,
        )

        hand = self.enrich_cards_with_values(
            [Card(**c) for c in state.hand_cards]
        )
        board = self.enrich_cards_with_values(
            [Card(**c) for c in state.board_minions]
        )
        enemy_minions = self.enrich_cards_with_values(
            [Card(**c) for c in state.enemy_minions]
        )

        actions = self.engine.plan_turn(
            hand=hand,
            available_mana=state.available_mana,
            board_minions=board,
            enemy_minions=enemy_minions,
            enemy_hero_health=state.enemy_hero_health,
        )

        logger.info("Planning complete – %d action(s) to execute.", len(actions))

        for action in actions:
            if action["type"] == "play":
                card: Card = action["card"]
                logger.info(
                    "PLAY  %s  (mana=%d, value=%.3f)",
                    card.name,
                    card.mana_cost,
                    card.inner_value,
                )
                self._played_this_game.append(card.card_id)

            elif action["type"] == "attack":
                attacker: Card = action["attacker"]
                if action["target_type"] == "hero":
                    logger.info(
                        "ATTACK  %s  -> enemy hero",
                        attacker.name,
                    )
                else:
                    logger.info(
                        "ATTACK  %s  -> enemy minion %s",
                        attacker.name,
                        action["target_id"],
                    )

    # ------------------------------------------------------------------ #
    # Game-end handling                                                    #
    # ------------------------------------------------------------------ #

    def on_game_end(self, won: bool) -> None:
        """Update card values based on the game outcome and reset state."""
        self.value_store.apply_game_result(self._played_this_game, won)
        outcome = "WON" if won else "LOST"
        logger.info(
            "Game %s – updated inner values for %d card(s).",
            outcome,
            len(self._played_this_game),
        )
        self._played_this_game = []

    # ------------------------------------------------------------------ #
    # Main loop                                                            #
    # ------------------------------------------------------------------ #

    def run(self) -> None:
        """Start the main agent loop.

        The loop reads the game window every ``poll_interval`` seconds.

        * When the Hearthstone window is not found or the game board is not
          visible, the agent logs a single "waiting" message and keeps
          polling without performing any game actions.
        * When an active match is detected, the agent plans and executes
          the turn.
        * When a game-over screen is detected, card values are updated and
          the agent resets for the next match.

        Press Ctrl-C to exit cleanly.
        """
        logger.info("Hearthstone agent started.  Waiting for a game…")
        _was_waiting = False
        try:
            while True:
                try:
                    logger.debug("Polling screen…")
                    state = self.screen_reader.read_game_state()

                    if not state.game_active:
                        if not _was_waiting:
                            logger.info(
                                "Hearthstone game board not detected – "
                                "waiting for a match to start…"
                            )
                            _was_waiting = True
                    else:
                        if _was_waiting:
                            logger.info("Match detected – resuming game actions.")
                        _was_waiting = False
                        if state.game_over:
                            if state.player_won is not None:
                                self.on_game_end(state.player_won)
                            else:
                                logger.info(
                                    "Game over – outcome unclear, skipping update."
                                )
                        else:
                            self.execute_turn(state)

                except Exception as exc:  # pylint: disable=broad-except
                    logger.error("Error during agent loop: %s", exc, exc_info=True)

                time.sleep(self._poll_interval)

        except KeyboardInterrupt:
            logger.info("Agent stopped by user.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Entry point when running ``python -m src.agent``."""
    agent = HearthstoneAgent()
    agent.run()


if __name__ == "__main__":
    main()
