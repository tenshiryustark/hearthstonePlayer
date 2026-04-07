"""Card model for the Hearthstone automated player agent."""
from dataclasses import dataclass, field


CARD_TYPE_MINION = "minion"
CARD_TYPE_SPELL = "spell"
CARD_TYPE_WEAPON = "weapon"

DEFAULT_INNER_VALUE = 1.0


@dataclass
class Card:
    """Represents a Hearthstone card with its properties and a persisted inner value.

    The *inner_value* is updated after each game (increased when the card
    contributed to a win, decreased when it contributed to a loss) so that
    the agent progressively learns which cards are more effective.
    """

    card_id: str
    name: str
    mana_cost: int
    attack: int
    health: int
    inner_value: float = DEFAULT_INNER_VALUE
    card_type: str = CARD_TYPE_MINION

    # ------------------------------------------------------------------ #
    # Convenience predicates                                               #
    # ------------------------------------------------------------------ #

    def is_minion(self) -> bool:
        """Return True when the card is a minion."""
        return self.card_type == CARD_TYPE_MINION

    def is_spell(self) -> bool:
        """Return True when the card is a spell."""
        return self.card_type == CARD_TYPE_SPELL

    def is_weapon(self) -> bool:
        """Return True when the card is a weapon."""
        return self.card_type == CARD_TYPE_WEAPON

    # ------------------------------------------------------------------ #
    # String representation                                                #
    # ------------------------------------------------------------------ #

    def __str__(self) -> str:
        return (
            f"{self.name} [{self.card_type}] "
            f"(mana={self.mana_cost}, atk={self.attack}, hp={self.health}, "
            f"value={self.inner_value:.3f})"
        )
