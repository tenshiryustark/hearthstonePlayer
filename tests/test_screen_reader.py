"""Tests for window_finder and the game_active / window-aware screen reader."""
import sys
from unittest.mock import MagicMock, patch

import pytest

from src.screen_reader import (
    BOARD_MIN_BRIGHTNESS,
    BOARD_MIN_GREEN,
    BOARD_PROBE_X_F,
    BOARD_PROBE_Y_F,
    GameState,
    ScreenReader,
)
from src.window_finder import (
    HEARTHSTONE_WINDOW_TITLE,
    find_hearthstone_window,
)


# ---------------------------------------------------------------------------
# GameState – game_active field
# ---------------------------------------------------------------------------


class TestGameStateGameActive:
    def test_defaults_to_false(self):
        state = GameState()
        assert state.game_active is False

    def test_can_be_set_true(self):
        state = GameState(game_active=True)
        assert state.game_active is True


# ---------------------------------------------------------------------------
# ScreenReader._detect_game_active – pixel heuristic
# ---------------------------------------------------------------------------


def _make_image(r, g, b, size=(1920, 1080)):
    """Return a solid-colour PIL Image."""
    from PIL import Image

    img = Image.new("RGB", size, color=(r, g, b))
    return img


class TestDetectGameActive:
    def setup_method(self):
        # Patch mss so ScreenReader.__init__ doesn't fail without a display
        self._mss_patch = patch("src.screen_reader._CAPTURE_AVAILABLE", True)
        self._mss_patch.start()
        self.reader = ScreenReader.__new__(ScreenReader)
        self.reader._card_detector = ScreenReader._detect_cards_stub
        self.reader._monitor_index = 1

    def teardown_method(self):
        self._mss_patch.stop()

    def test_board_colour_returns_true(self):
        # Approximate board green: R=70, G=110, B=65
        img = _make_image(70, 110, 65)
        assert self.reader._detect_game_active(img) is True

    def test_main_menu_dark_returns_false(self):
        # Dark/near-black background typical of main menu
        img = _make_image(10, 15, 12)
        assert self.reader._detect_game_active(img) is False

    def test_bright_non_green_returns_false(self):
        # Very bright but no green dominance (e.g. white UI)
        img = _make_image(220, 200, 210)
        assert self.reader._detect_game_active(img) is False

    def test_borderline_green_below_threshold_returns_false(self):
        # Green channel just below BOARD_MIN_GREEN
        img = _make_image(30, BOARD_MIN_GREEN - 1, 25)
        assert self.reader._detect_game_active(img) is False


# ---------------------------------------------------------------------------
# find_hearthstone_window – cross-platform stubs
# ---------------------------------------------------------------------------


class TestFindHearthstoneWindowWin32:
    def test_pygetwindow_found(self):
        mock_win = MagicMock()
        mock_win.left = 100
        mock_win.top = 50
        mock_win.width = 1920
        mock_win.height = 1080

        mock_gw = MagicMock()
        mock_gw.getWindowsWithTitle.return_value = [mock_win]

        with patch.dict("sys.modules", {"pygetwindow": mock_gw}):
            with patch("sys.platform", "win32"):
                from src import window_finder as wf
                result = wf._find_window_win32()

        assert result == (100, 50, 1920, 1080)

    def test_pygetwindow_no_window_returns_none(self):
        mock_gw = MagicMock()
        mock_gw.getWindowsWithTitle.return_value = []

        with patch.dict("sys.modules", {"pygetwindow": mock_gw, "win32gui": None}):
            with patch("sys.platform", "win32"):
                from src import window_finder as wf
                with patch.object(wf, "_find_window_win32", return_value=None):
                    result = wf.find_hearthstone_window()

        assert result is None

    def test_pygetwindow_exception_falls_through(self):
        """When pygetwindow raises, _find_window_win32 returns None gracefully."""
        mock_gw = MagicMock()
        mock_gw.getWindowsWithTitle.side_effect = RuntimeError("import error")

        # Patch both optional backends so both paths fail cleanly
        with patch.dict("sys.modules", {"pygetwindow": mock_gw, "win32gui": None}):
            from src import window_finder as wf
            result = wf._find_window_win32()

        assert result is None


class TestFindHearthstoneWindowLinux:
    def test_xdotool_success(self):
        search_result = MagicMock()
        search_result.stdout = "12345678\n"

        geo_result = MagicMock()
        geo_result.stdout = "X=0\nY=0\nWIDTH=1920\nHEIGHT=1080\n"

        with patch("subprocess.run", side_effect=[search_result, geo_result]):
            with patch("sys.platform", "linux"):
                from src import window_finder as wf
                result = wf._find_window_linux()

        assert result == (0, 0, 1920, 1080)

    def test_xdotool_no_window_returns_none(self):
        search_result = MagicMock()
        search_result.stdout = ""

        with patch("subprocess.run", return_value=search_result):
            from src import window_finder as wf
            result = wf._find_window_linux()

        assert result is None

    def test_xdotool_not_installed_returns_none(self):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            from src import window_finder as wf
            result = wf._find_window_linux()

        assert result is None


# ---------------------------------------------------------------------------
# ScreenReader.read_game_state – game_active gate
# ---------------------------------------------------------------------------


class TestReadGameStateGameActiveGate:
    """read_game_state must set game_active=False when the window is absent."""

    def _make_reader(self):
        reader = ScreenReader.__new__(ScreenReader)
        reader._card_detector = ScreenReader._detect_cards_stub
        reader._monitor_index = 1
        return reader

    def test_window_not_found_returns_inactive_state(self):
        reader = self._make_reader()

        with patch("src.screen_reader.find_hearthstone_window", return_value=None):
            # capture_game_window needs mss – patch it directly
            fake_img = _make_image(10, 10, 10)  # dark → game not active
            with patch.object(
                reader, "capture_game_window", return_value=(fake_img, False)
            ):
                state = reader.read_game_state()

        assert state.game_active is False

    def test_window_found_board_inactive_returns_false(self):
        reader = self._make_reader()
        dark_img = _make_image(5, 5, 5)

        with patch.object(
            reader, "capture_game_window", return_value=(dark_img, True)
        ):
            state = reader.read_game_state()

        assert state.game_active is False

    def test_window_found_board_active_returns_true(self):
        reader = self._make_reader()
        board_img = _make_image(70, 110, 65)  # greenish board colour

        with patch.object(
            reader, "capture_game_window", return_value=(board_img, True)
        ):
            state = reader.read_game_state()

        assert state.game_active is True
