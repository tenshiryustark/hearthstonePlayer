"""Tests for HearthstoneAgent (orchestration layer)."""
import json
import pytest

from src.card import Card
from src.agent import HearthstoneAgent
from src.screen_reader import GameState


def make_card_dict(card_id, name, mana, atk, hp, card_type="minion"):
    return {
        "card_id": card_id,
        "name": name,
        "mana_cost": mana,
        "attack": atk,
        "health": hp,
        "card_type": card_type,
    }


class FakeScreenReader:
    """Minimal screen-reader stub that returns a pre-set GameState."""

    def __init__(self, states):
        self._states = iter(states)

    def read_game_state(self):
        return next(self._states)


@pytest.fixture
def agent(tmp_path):
    return HearthstoneAgent(
        value_store_path=str(tmp_path / "cv.json"),
        screen_reader=FakeScreenReader([]),
    )


class TestEnrichCardsWithValues:
    def test_applies_default_value(self, agent):
        cards = [Card("c1", "Card", 2, 2, 2)]
        enriched = agent.enrich_cards_with_values(cards)
        from src.card_value_store import DEFAULT_INNER_VALUE
        assert enriched[0].inner_value == DEFAULT_INNER_VALUE

    def test_applies_persisted_value(self, agent):
        agent.value_store.set_value("c1", 3.5)
        cards = [Card("c1", "Card", 2, 2, 2)]
        enriched = agent.enrich_cards_with_values(cards)
        assert enriched[0].inner_value == 3.5


class TestOnGameEnd:
    def test_win_updates_played_cards(self, agent):
        agent._played_this_game = ["c1", "c2"]
        agent.on_game_end(won=True)
        from src.card_value_store import DEFAULT_INNER_VALUE, WIN_DELTA
        assert agent.value_store.get_value("c1") == pytest.approx(
            DEFAULT_INNER_VALUE + WIN_DELTA
        )
        assert agent.value_store.get_value("c2") == pytest.approx(
            DEFAULT_INNER_VALUE + WIN_DELTA
        )

    def test_loss_updates_played_cards(self, agent):
        agent._played_this_game = ["c1"]
        agent.on_game_end(won=False)
        from src.card_value_store import DEFAULT_INNER_VALUE, LOSE_DELTA
        assert agent.value_store.get_value("c1") == pytest.approx(
            DEFAULT_INNER_VALUE - LOSE_DELTA
        )

    def test_resets_played_list_after_game_end(self, agent):
        agent._played_this_game = ["c1", "c2"]
        agent.on_game_end(won=True)
        assert agent._played_this_game == []


class TestExecuteTurn:
    def test_played_cards_tracked(self, agent):
        state = GameState(
            game_active=True,
            hand_cards=[make_card_dict("c1", "Wisp", 0, 1, 1)],
            board_minions=[],
            enemy_minions=[],
            available_mana=10,
        )
        agent.execute_turn(state)
        assert "c1" in agent._played_this_game

    def test_no_crash_with_empty_state(self, agent):
        state = GameState(game_active=True)
        agent.execute_turn(state)  # should not raise
