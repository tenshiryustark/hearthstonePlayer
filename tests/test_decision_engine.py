"""Tests for DecisionEngine (card-play and attack-target selection)."""
import pytest

from src.card import Card
from src.decision_engine import DecisionEngine


@pytest.fixture
def engine():
    return DecisionEngine()


def make_card(card_id, name, mana, atk, hp, value=1.0, card_type="minion"):
    return Card(
        card_id=card_id,
        name=name,
        mana_cost=mana,
        attack=atk,
        health=hp,
        inner_value=value,
        card_type=card_type,
    )


# ---------------------------------------------------------------------------
# select_card_to_play
# ---------------------------------------------------------------------------


class TestSelectCardToPlay:
    def test_returns_none_when_hand_is_empty(self, engine):
        assert engine.select_card_to_play([], available_mana=5) is None

    def test_returns_none_when_no_affordable_card(self, engine):
        hand = [make_card("c1", "Expensive", mana=8, atk=5, hp=5)]
        assert engine.select_card_to_play(hand, available_mana=3) is None

    def test_picks_highest_value_affordable_card(self, engine):
        hand = [
            make_card("c1", "Low", mana=2, atk=2, hp=2, value=0.5),
            make_card("c2", "High", mana=2, atk=3, hp=3, value=2.0),
            make_card("c3", "Mid", mana=2, atk=2, hp=3, value=1.0),
        ]
        chosen = engine.select_card_to_play(hand, available_mana=5)
        assert chosen.card_id == "c2"

    def test_respects_mana_constraint(self, engine):
        hand = [
            make_card("cheap", "Cheap", mana=1, atk=1, hp=1, value=0.5),
            make_card("expensive", "Expensive", mana=5, atk=5, hp=5, value=5.0),
        ]
        chosen = engine.select_card_to_play(hand, available_mana=3)
        assert chosen.card_id == "cheap"

    def test_exact_mana_is_playable(self, engine):
        hand = [make_card("exact", "Exact", mana=5, atk=3, hp=3, value=1.0)]
        assert engine.select_card_to_play(hand, available_mana=5) is not None


# ---------------------------------------------------------------------------
# compute_minion_action_value
# ---------------------------------------------------------------------------


class TestComputeMinionActionValue:
    def test_one_shot_gives_higher_value(self, engine):
        attacker = make_card("atk", "Attacker", mana=3, atk=5, hp=3)
        weak = make_card("w1", "Weak", mana=1, atk=2, hp=2, value=1.0)
        strong = make_card("s1", "Strong", mana=1, atk=2, hp=10, value=1.0)
        v_kill = engine.compute_minion_action_value(attacker, weak)
        v_nokill = engine.compute_minion_action_value(attacker, strong)
        assert v_kill > v_nokill

    def test_higher_inner_value_target_preferred(self, engine):
        attacker = make_card("atk", "Attacker", mana=3, atk=5, hp=5)
        low_val = make_card("l", "LowVal", mana=1, atk=3, hp=2, value=0.5)
        high_val = make_card("h", "HighVal", mana=1, atk=3, hp=2, value=3.0)
        v_low = engine.compute_minion_action_value(attacker, low_val)
        v_high = engine.compute_minion_action_value(attacker, high_val)
        assert v_high > v_low


# ---------------------------------------------------------------------------
# select_attack_target
# ---------------------------------------------------------------------------


class TestSelectAttackTarget:
    def test_attacks_hero_when_no_enemy_minions(self, engine):
        attacker = make_card("a", "Warrior", mana=3, atk=4, hp=4)
        target_id, target_type = engine.select_attack_target(
            attacker, enemy_minions=[], enemy_hero_health=10
        )
        assert target_type == "hero"
        assert target_id is None

    def test_attacks_high_value_minion_over_hero(self, engine):
        attacker = make_card("a", "Warrior", mana=3, atk=3, hp=5)
        dangerous = make_card("d", "Dangerous", mana=2, atk=10, hp=2, value=5.0)
        target_id, target_type = engine.select_attack_target(
            attacker, enemy_minions=[dangerous], enemy_hero_health=30
        )
        assert target_type == "minion"
        assert target_id == "d"

    def test_attacks_hero_when_minion_threat_is_low(self, engine):
        attacker = make_card("a", "Warrior", mana=3, atk=10, hp=5)
        weak_minion = make_card("w", "Wisp", mana=0, atk=1, hp=1, value=0.1)
        target_id, target_type = engine.select_attack_target(
            attacker, enemy_minions=[weak_minion], enemy_hero_health=5
        )
        assert target_type == "hero"

    def test_returns_correct_minion_id(self, engine):
        attacker = make_card("a", "Warrior", mana=3, atk=4, hp=4)
        m1 = make_card("minion_1", "Guard1", mana=3, atk=3, hp=3, value=2.0)
        m2 = make_card("minion_2", "Guard2", mana=3, atk=1, hp=1, value=0.5)
        target_id, _ = engine.select_attack_target(
            attacker, enemy_minions=[m1, m2], enemy_hero_health=30
        )
        assert target_id == "minion_1"


# ---------------------------------------------------------------------------
# plan_turn
# ---------------------------------------------------------------------------


class TestPlanTurn:
    def test_empty_hand_and_board_gives_no_actions(self, engine):
        actions = engine.plan_turn(
            hand=[],
            available_mana=10,
            board_minions=[],
            enemy_minions=[],
            enemy_hero_health=30,
        )
        assert actions == []

    def test_plays_all_affordable_cards(self, engine):
        hand = [
            make_card("c1", "A", mana=2, atk=2, hp=2, value=1.0),
            make_card("c2", "B", mana=2, atk=2, hp=2, value=1.5),
            make_card("c3", "C", mana=8, atk=5, hp=5, value=3.0),
        ]
        actions = engine.plan_turn(
            hand=hand,
            available_mana=4,
            board_minions=[],
            enemy_minions=[],
            enemy_hero_health=30,
        )
        play_actions = [a for a in actions if a["type"] == "play"]
        assert len(play_actions) == 2

    def test_attack_actions_included(self, engine):
        board = [make_card("m1", "Knight", mana=3, atk=3, hp=4)]
        actions = engine.plan_turn(
            hand=[],
            available_mana=0,
            board_minions=board,
            enemy_minions=[],
            enemy_hero_health=30,
        )
        attack_actions = [a for a in actions if a["type"] == "attack"]
        assert len(attack_actions) == 1

    def test_zero_attack_minion_does_not_attack(self, engine):
        board = [make_card("m1", "Pacifist", mana=2, atk=0, hp=5)]
        actions = engine.plan_turn(
            hand=[],
            available_mana=0,
            board_minions=board,
            enemy_minions=[],
            enemy_hero_health=30,
        )
        attack_actions = [a for a in actions if a["type"] == "attack"]
        assert len(attack_actions) == 0
