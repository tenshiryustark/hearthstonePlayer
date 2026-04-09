"""Decision engine – determines the best action to take on each turn.

The engine considers **inner values** (loaded from :class:`CardValueStore`)
when ranking choices.  Two decisions are made each turn:

1. **Which card to play from hand?**  – highest ``inner_value`` among
   affordable cards.
2. **Which target to attack?**  – compares an *attack-action value* for
   striking each enemy minion versus striking the enemy hero directly.

Attack-action value formula
---------------------------
* Attacking a minion:

  ``action_value = kill_factor * threat_factor``

  where ``kill_factor = 1.0`` if our attacker can one-shot the minion,
  else ``0.5``; and ``threat_factor = minion.inner_value * minion.attack``
  (high-value, high-attack minions are prioritised).

* Attacking the hero:

  ``action_value = attacker.attack / enemy_hero_health``

The target with the highest action value is chosen.
"""
from typing import List, Optional, Tuple

from .card import Card


class DecisionEngine:
    """Stateless engine that selects actions given the current game state."""

    # ------------------------------------------------------------------ #
    # Card-play decision                                                   #
    # ------------------------------------------------------------------ #

    def select_card_to_play(
        self, hand: List[Card], available_mana: int
    ) -> Optional[Card]:
        """Return the best card to play from *hand* given *available_mana*.

        Selects the affordable card with the highest ``inner_value``.
        Returns ``None`` when no card can be played.
        """
        playable = [c for c in hand if c.mana_cost <= available_mana]
        if not playable:
            return None
        return max(playable, key=lambda c: c.inner_value)

    # ------------------------------------------------------------------ #
    # Attack-target decision                                               #
    # ------------------------------------------------------------------ #

    def compute_minion_action_value(self, attacker: Card, target: Card) -> float:
        """Return the action value for *attacker* striking *target* minion.

        A higher value means the attack is more desirable.
        """
        kill_factor = 1.0 if attacker.attack >= target.health else 0.5
        threat_factor = target.inner_value * max(target.attack, 1)
        return kill_factor * threat_factor

    def compute_hero_action_value(
        self, attacker: Card, enemy_hero_health: int
    ) -> float:
        """Return the action value for *attacker* striking the enemy hero."""
        return attacker.attack / max(enemy_hero_health, 1)

    def select_attack_target(
        self,
        attacker: Card,
        enemy_minions: List[Card],
        enemy_hero_health: int,
    ) -> Tuple[Optional[str], str]:
        """Decide the best attack target for *attacker*.

        Parameters
        ----------
        attacker:
            The minion performing the attack.
        enemy_minions:
            List of enemy minions currently on the board.
        enemy_hero_health:
            Current health of the enemy hero.

        Returns
        -------
        (target_card_id, target_type)
            *target_card_id* is the ``card_id`` of the chosen enemy minion,
            or ``None`` when targeting the hero.
            *target_type* is ``"minion"`` or ``"hero"``.
        """
        hero_value = self.compute_hero_action_value(attacker, enemy_hero_health)

        best_minion: Optional[Card] = None
        best_minion_value: float = -1.0

        for minion in enemy_minions:
            value = self.compute_minion_action_value(attacker, minion)
            if value > best_minion_value:
                best_minion_value = value
                best_minion = minion

        if best_minion is not None and best_minion_value > hero_value:
            return (best_minion.card_id, "minion")

        return (None, "hero")

    # ------------------------------------------------------------------ #
    # Full-turn plan                                                       #
    # ------------------------------------------------------------------ #

    def plan_turn(
        self,
        hand: List[Card],
        available_mana: int,
        board_minions: List[Card],
        enemy_minions: List[Card],
        enemy_hero_health: int,
    ) -> List[dict]:
        """Return an ordered list of actions to execute this turn.

        Each action is a dict with a ``"type"`` key:

        * ``{"type": "play", "card": Card}``
        * ``{"type": "attack", "attacker": Card, "target_id": str|None,
             "target_type": str}``

        Parameters
        ----------
        hand:
            Cards in the player's hand (with ``inner_value`` already applied).
        available_mana:
            Current mana available to spend.
        board_minions:
            Player's minions currently on the board.
        enemy_minions:
            Enemy minions currently on the board.
        enemy_hero_health:
            Current health of the enemy hero.
        """
        actions: List[dict] = []
        remaining_mana = available_mana
        remaining_hand = list(hand)

        # Phase 1 – play cards from hand
        while True:
            card = self.select_card_to_play(remaining_hand, remaining_mana)
            if card is None:
                break
            actions.append({"type": "play", "card": card})
            remaining_mana -= card.mana_cost
            remaining_hand.remove(card)

        # Phase 2 – attack with board minions
        for minion in board_minions:
            if minion.attack <= 0:
                continue
            target_id, target_type = self.select_attack_target(
                minion, enemy_minions, enemy_hero_health
            )
            actions.append(
                {
                    "type": "attack",
                    "attacker": minion,
                    "target_id": target_id,
                    "target_type": target_type,
                }
            )

        return actions
