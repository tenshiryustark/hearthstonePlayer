"""Tests for the Card dataclass."""
import pytest

from src.card import (
    Card,
    CARD_TYPE_MINION,
    CARD_TYPE_SPELL,
    CARD_TYPE_WEAPON,
    DEFAULT_INNER_VALUE,
)


class TestCardDefaults:
    def test_default_inner_value(self):
        card = Card(card_id="CS2_008", name="Mage", mana_cost=2, attack=2, health=3)
        assert card.inner_value == DEFAULT_INNER_VALUE

    def test_default_card_type_is_minion(self):
        card = Card(card_id="CS2_008", name="Mage", mana_cost=2, attack=2, health=3)
        assert card.card_type == CARD_TYPE_MINION

    def test_custom_inner_value(self):
        card = Card(
            card_id="CS2_008",
            name="Mage",
            mana_cost=2,
            attack=2,
            health=3,
            inner_value=2.5,
        )
        assert card.inner_value == 2.5


class TestCardPredicates:
    def test_is_minion(self):
        card = Card("id1", "Fighter", 3, 3, 3, card_type=CARD_TYPE_MINION)
        assert card.is_minion()
        assert not card.is_spell()
        assert not card.is_weapon()

    def test_is_spell(self):
        card = Card("id2", "Fireball", 4, 0, 0, card_type=CARD_TYPE_SPELL)
        assert card.is_spell()
        assert not card.is_minion()
        assert not card.is_weapon()

    def test_is_weapon(self):
        card = Card("id3", "Sword", 3, 4, 2, card_type=CARD_TYPE_WEAPON)
        assert card.is_weapon()
        assert not card.is_minion()
        assert not card.is_spell()


class TestCardStringRepresentation:
    def test_str_contains_name(self):
        card = Card("id1", "Wisp", 0, 1, 1)
        assert "Wisp" in str(card)

    def test_str_contains_type(self):
        card = Card("id2", "Fireball", 4, 0, 0, card_type=CARD_TYPE_SPELL)
        assert CARD_TYPE_SPELL in str(card)
