"""Tests for CardValueStore (persistence layer)."""
import json
import os
import tempfile

import pytest

from src.card_value_store import (
    CardValueStore,
    DEFAULT_INNER_VALUE,
    WIN_DELTA,
    LOSE_DELTA,
    MIN_VALUE,
)


@pytest.fixture
def store(tmp_path):
    """Return a CardValueStore backed by a temp file."""
    return CardValueStore(store_path=str(tmp_path / "card_values.json"))


class TestDefaultValues:
    def test_unknown_card_returns_default(self, store):
        assert store.get_value("unknown_card") == DEFAULT_INNER_VALUE

    def test_all_values_empty_initially(self, store):
        assert store.all_values() == {}


class TestSetValue:
    def test_set_and_retrieve(self, store):
        store.set_value("CS2_001", 2.0)
        assert store.get_value("CS2_001") == 2.0

    def test_set_value_clamped_to_min(self, store):
        store.set_value("CS2_001", -5.0)
        assert store.get_value("CS2_001") == MIN_VALUE


class TestUpdateValue:
    def test_win_increases_value(self, store):
        store.set_value("CS2_001", 1.0)
        store.update_value("CS2_001", won=True)
        assert store.get_value("CS2_001") == pytest.approx(1.0 + WIN_DELTA)

    def test_loss_decreases_value(self, store):
        store.set_value("CS2_001", 1.0)
        store.update_value("CS2_001", won=False)
        assert store.get_value("CS2_001") == pytest.approx(1.0 - LOSE_DELTA)

    def test_loss_does_not_go_below_min(self, store):
        store.set_value("CS2_001", 0.02)
        store.update_value("CS2_001", won=False)
        assert store.get_value("CS2_001") >= MIN_VALUE

    def test_new_card_win_starts_from_default(self, store):
        store.update_value("brand_new", won=True)
        assert store.get_value("brand_new") == pytest.approx(
            DEFAULT_INNER_VALUE + WIN_DELTA
        )


class TestApplyGameResult:
    def test_win_updates_all_played_cards(self, store):
        store.apply_game_result(["card_a", "card_b"], won=True)
        assert store.get_value("card_a") == pytest.approx(DEFAULT_INNER_VALUE + WIN_DELTA)
        assert store.get_value("card_b") == pytest.approx(DEFAULT_INNER_VALUE + WIN_DELTA)

    def test_loss_updates_all_played_cards(self, store):
        store.apply_game_result(["card_a", "card_b"], won=False)
        assert store.get_value("card_a") == pytest.approx(DEFAULT_INNER_VALUE - LOSE_DELTA)
        assert store.get_value("card_b") == pytest.approx(DEFAULT_INNER_VALUE - LOSE_DELTA)

    def test_empty_list_is_noop(self, store):
        store.apply_game_result([], won=True)
        assert store.all_values() == {}


class TestPersistence:
    def test_values_survive_reload(self, tmp_path):
        path = str(tmp_path / "cv.json")
        store1 = CardValueStore(store_path=path)
        store1.set_value("CS2_001", 1.5)

        store2 = CardValueStore(store_path=path)
        assert store2.get_value("CS2_001") == 1.5

    def test_file_is_valid_json(self, tmp_path):
        path = str(tmp_path / "cv.json")
        store = CardValueStore(store_path=path)
        store.set_value("CS2_001", 1.0)

        with open(path, "r") as fh:
            data = json.load(fh)
        assert "CS2_001" in data

    def test_multiple_games_accumulate_value(self, tmp_path):
        path = str(tmp_path / "cv.json")
        store = CardValueStore(store_path=path)
        store.apply_game_result(["card_x"], won=True)
        store.apply_game_result(["card_x"], won=True)
        expected = DEFAULT_INNER_VALUE + 2 * WIN_DELTA
        assert store.get_value("card_x") == pytest.approx(expected)
