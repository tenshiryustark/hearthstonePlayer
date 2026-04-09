"""Tests for src.card_inspector – card hover detection and identification."""
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from src.card_inspector import (
    BOARD_MAX_SLOTS,
    HAND_MAX_SLOTS,
    CardInspector,
)
from src.screen_reader import REGIONS, ScreenReader


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_screen(w=1440, h=1080, color=(100, 80, 60)):
    """Return a solid-colour PIL Image representing the game window."""
    return Image.new("RGB", (w, h), color=color)


def _make_inspector(card_detector=None):
    """Build a CardInspector with a stub ScreenReader (no display needed)."""
    reader = ScreenReader.__new__(ScreenReader)
    reader._card_detector = ScreenReader._detect_cards_stub
    reader._monitor_index = 1
    return CardInspector(reader, card_detector=card_detector)


# ---------------------------------------------------------------------------
# get_card_slot – region / slot mapping
# ---------------------------------------------------------------------------


class TestGetCardSlot:
    """Verify that mouse coordinates map to the correct region and slot."""

    WIN_W = 1440
    WIN_H = 1080

    def _center(self, region_name):
        """Return (x, y) at the horizontal and vertical center of a region."""
        reg = REGIONS[region_name]
        x = int((reg["left_f"] + reg["width_f"] / 2) * self.WIN_W)
        y = int((reg["top_f"] + reg["height_f"] / 2) * self.WIN_H)
        return x, y

    def test_hand_center_returns_hand_region(self):
        inspector = _make_inspector()
        x, y = self._center("hand")
        result = inspector.get_card_slot(x, y, self.WIN_W, self.WIN_H)
        assert result is not None
        region_name, _ = result
        assert region_name == "hand"

    def test_board_player_center_returns_board_player(self):
        inspector = _make_inspector()
        x, y = self._center("board_player")
        result = inspector.get_card_slot(x, y, self.WIN_W, self.WIN_H)
        assert result is not None
        region_name, _ = result
        assert region_name == "board_player"

    def test_board_enemy_center_returns_board_enemy(self):
        inspector = _make_inspector()
        x, y = self._center("board_enemy")
        result = inspector.get_card_slot(x, y, self.WIN_W, self.WIN_H)
        assert result is not None
        region_name, _ = result
        assert region_name == "board_enemy"

    def test_outside_regions_returns_none(self):
        inspector = _make_inspector()
        # Top-left corner – not over any card area
        result = inspector.get_card_slot(5, 5, self.WIN_W, self.WIN_H)
        assert result is None

    def test_hand_leftmost_is_slot_zero(self):
        inspector = _make_inspector()
        reg = REGIONS["hand"]
        # One pixel inside the left edge of the hand region
        x = int(reg["left_f"] * self.WIN_W) + 1
        y = int((reg["top_f"] + reg["height_f"] / 2) * self.WIN_H)
        result = inspector.get_card_slot(x, y, self.WIN_W, self.WIN_H)
        assert result is not None
        _, slot = result
        assert slot == 0

    def test_hand_rightmost_is_last_slot(self):
        inspector = _make_inspector()
        reg = REGIONS["hand"]
        # One pixel before the right edge of the hand region
        x = int((reg["left_f"] + reg["width_f"]) * self.WIN_W) - 1
        y = int((reg["top_f"] + reg["height_f"] / 2) * self.WIN_H)
        result = inspector.get_card_slot(x, y, self.WIN_W, self.WIN_H)
        assert result is not None
        _, slot = result
        assert slot == HAND_MAX_SLOTS - 1

    def test_board_player_slot_index_within_bounds(self):
        inspector = _make_inspector()
        reg = REGIONS["board_player"]
        for frac in (0.1, 0.5, 0.9):
            x = int((reg["left_f"] + frac * reg["width_f"]) * self.WIN_W)
            y = int((reg["top_f"] + reg["height_f"] / 2) * self.WIN_H)
            result = inspector.get_card_slot(x, y, self.WIN_W, self.WIN_H)
            assert result is not None
            _, slot = result
            assert 0 <= slot < BOARD_MAX_SLOTS


# ---------------------------------------------------------------------------
# crop_card_slot – image dimensions
# ---------------------------------------------------------------------------


class TestCropCardSlot:
    """crop_card_slot must return an image of the expected size."""

    WIN_W = 1440
    WIN_H = 1080

    def _expected_slot_size(self, region_name):
        reg = REGIONS[region_name]
        max_slots = HAND_MAX_SLOTS if region_name == "hand" else BOARD_MAX_SLOTS
        region_w = int(reg["width_f"] * self.WIN_W)
        region_h = int(reg["height_f"] * self.WIN_H)
        slot_w = region_w // max_slots
        return slot_w, region_h

    def test_hand_crop_dimensions(self):
        inspector = _make_inspector()
        screen = _make_screen(self.WIN_W, self.WIN_H)
        crop = inspector.crop_card_slot(screen, "hand", 0)
        expected_w, expected_h = self._expected_slot_size("hand")
        assert crop.size == (expected_w, expected_h)

    def test_board_player_crop_dimensions(self):
        inspector = _make_inspector()
        screen = _make_screen(self.WIN_W, self.WIN_H)
        crop = inspector.crop_card_slot(screen, "board_player", 3)
        expected_w, expected_h = self._expected_slot_size("board_player")
        assert crop.size == (expected_w, expected_h)

    def test_board_enemy_crop_dimensions(self):
        inspector = _make_inspector()
        screen = _make_screen(self.WIN_W, self.WIN_H)
        crop = inspector.crop_card_slot(screen, "board_enemy", 6)
        expected_w, expected_h = self._expected_slot_size("board_enemy")
        assert crop.size == (expected_w, expected_h)

    def test_different_slots_same_size(self):
        inspector = _make_inspector()
        screen = _make_screen(self.WIN_W, self.WIN_H)
        sizes = [
            inspector.crop_card_slot(screen, "hand", slot).size
            for slot in range(HAND_MAX_SLOTS)
        ]
        assert len(set(sizes)) == 1  # all slots equal width


# ---------------------------------------------------------------------------
# _format_card – output format
# ---------------------------------------------------------------------------


class TestFormatCard:
    def test_full_card_dict(self):
        text = CardInspector._format_card(
            "hand",
            2,
            {
                "name": "Fireball",
                "card_type": "Spell",
                "mana_cost": 4,
                "attack": None,
                "health": None,
            },
        )
        assert "Fireball" in text
        assert "Spell" in text
        assert "Mana:4" in text
        assert "[hand slot 2]" in text

    def test_minion_card_dict(self):
        text = CardInspector._format_card(
            "board_player",
            0,
            {
                "name": "Wisp",
                "card_type": "Minion",
                "mana_cost": 0,
                "attack": 1,
                "health": 1,
            },
        )
        assert "Wisp" in text
        assert "Minion" in text
        assert "ATK:1" in text
        assert "HP:1" in text
        assert "[board_player slot 0]" in text

    def test_missing_keys_show_dashes(self):
        text = CardInspector._format_card("hand", 5, {})
        assert "Unknown" in text
        assert "Mana:-" in text
        assert "ATK:-" in text
        assert "HP:-" in text

    def test_none_name_falls_back_to_unknown(self):
        text = CardInspector._format_card("hand", 0, {"name": None})
        assert "Unknown" in text


# ---------------------------------------------------------------------------
# identify_card_at_mouse – integration (all I/O mocked)
# ---------------------------------------------------------------------------


WIN_BBOX = (100, 50, 1440, 1080)  # left, top, width, height


def _hand_mouse_pos():
    """Absolute screen coords that land inside the hand region."""
    reg = REGIONS["hand"]
    win_left, win_top, win_w, win_h = WIN_BBOX
    x = win_left + int((reg["left_f"] + 0.05) * win_w)
    y = win_top + int((reg["top_f"] + reg["height_f"] / 2) * win_h)
    return x, y


class TestIdentifyCardAtMouse:
    def test_window_not_found_returns_none(self):
        inspector = _make_inspector()
        with patch(
            "src.card_inspector.find_hearthstone_window", return_value=None
        ):
            result = inspector.identify_card_at_mouse(500, 500)
        assert result is None

    def test_mouse_outside_window_returns_none(self):
        inspector = _make_inspector()
        with patch(
            "src.card_inspector.find_hearthstone_window",
            return_value=WIN_BBOX,
        ):
            # Mouse far to the left of the window
            result = inspector.identify_card_at_mouse(0, 0)
        assert result is None

    def test_mouse_over_non_card_area_returns_none(self):
        inspector = _make_inspector()
        screen = _make_screen()
        with patch(
            "src.card_inspector.find_hearthstone_window",
            return_value=WIN_BBOX,
        ):
            with patch.object(
                inspector._screen_reader,
                "capture_game_window",
                return_value=(screen, True),
            ):
                win_left, win_top, _, _ = WIN_BBOX
                # Top-left corner of the window → not a card region
                result = inspector.identify_card_at_mouse(
                    win_left + 5, win_top + 5
                )
        assert result is None

    def test_stub_detector_returns_no_card_found(self):
        inspector = _make_inspector()  # stub detector → []
        screen = _make_screen()
        mouse_x, mouse_y = _hand_mouse_pos()
        with patch(
            "src.card_inspector.find_hearthstone_window",
            return_value=WIN_BBOX,
        ):
            with patch.object(
                inspector._screen_reader,
                "capture_game_window",
                return_value=(screen, True),
            ):
                result = inspector.identify_card_at_mouse(mouse_x, mouse_y)

        assert result is not None
        assert "No card found" in result
        assert "hand" in result

    def test_real_detector_returns_card_info(self):
        fake_card = {
            "name": "Fireball",
            "card_type": "Spell",
            "mana_cost": 4,
            "attack": None,
            "health": None,
        }
        inspector = _make_inspector(card_detector=lambda img: [fake_card])
        screen = _make_screen()
        mouse_x, mouse_y = _hand_mouse_pos()
        with patch(
            "src.card_inspector.find_hearthstone_window",
            return_value=WIN_BBOX,
        ):
            with patch.object(
                inspector._screen_reader,
                "capture_game_window",
                return_value=(screen, True),
            ):
                result = inspector.identify_card_at_mouse(mouse_x, mouse_y)

        assert result is not None
        assert "Fireball" in result
        assert "Spell" in result

    def test_window_not_found_after_capture_returns_none(self):
        """Fallback capture (window=False) returns None gracefully."""
        inspector = _make_inspector()
        screen = _make_screen()
        mouse_x, mouse_y = _hand_mouse_pos()
        with patch(
            "src.card_inspector.find_hearthstone_window",
            return_value=WIN_BBOX,
        ):
            with patch.object(
                inspector._screen_reader,
                "capture_game_window",
                return_value=(screen, False),  # window lost between calls
            ):
                result = inspector.identify_card_at_mouse(mouse_x, mouse_y)

        assert result is None
