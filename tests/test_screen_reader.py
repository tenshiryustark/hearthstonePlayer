"""Tests for window_finder and the game_active / window-aware screen reader."""
import sys
from unittest.mock import MagicMock, patch

import pytest

from src.screen_reader import (
    BOARD_MIN_MEAN_BRIGHTNESS,
    BOARD_PROBE_POINTS,
    TEMPLATE_MATCH_THRESHOLD,
    GameState,
    ScreenReader,
)
from src.window_finder import (
    HEARTHSTONE_WINDOW_TITLE,
    _title_matches,
    find_hearthstone_window,
)


# ---------------------------------------------------------------------------
# _title_matches – case-insensitive partial matching
# ---------------------------------------------------------------------------


class TestTitleMatches:
    def test_exact_match(self):
        assert _title_matches("Hearthstone") is True

    def test_case_insensitive(self):
        assert _title_matches("hearthstone") is True
        assert _title_matches("HEARTHSTONE") is True

    def test_partial_match(self):
        assert _title_matches("Hearthstone - Loading") is True

    def test_no_match(self):
        assert _title_matches("World of Warcraft") is False

    def test_empty_string(self):
        assert _title_matches("") is False

    def test_none(self):
        assert _title_matches(None) is False  # type: ignore[arg-type]


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
# ScreenReader._detect_game_active – brightness fallback
# ---------------------------------------------------------------------------


def _make_image(r, g, b, size=(1920, 1080)):
    """Return a solid-colour PIL Image."""
    from PIL import Image

    img = Image.new("RGB", size, color=(r, g, b))
    return img


class TestDetectGameActive:
    def setup_method(self):
        # Patch _CAPTURE_AVAILABLE so ScreenReader.__init__ doesn't fail
        self._cap_patch = patch("src.screen_reader._CAPTURE_AVAILABLE", True)
        self._cap_patch.start()
        # Force brightness fallback by pretending cv2 is unavailable
        self._cv2_patch = patch("src.screen_reader._CV2_AVAILABLE", False)
        self._cv2_patch.start()
        self.reader = ScreenReader.__new__(ScreenReader)
        self.reader._card_detector = ScreenReader._detect_cards_stub

    def teardown_method(self):
        self._cap_patch.stop()
        self._cv2_patch.stop()

    def test_green_board_returns_true(self):
        img = _make_image(70, 110, 65)
        assert self.reader._detect_game_active(img) is True

    def test_brown_board_returns_true(self):
        img = _make_image(120, 90, 60)
        assert self.reader._detect_game_active(img) is True

    def test_purple_board_returns_true(self):
        img = _make_image(80, 70, 110)
        assert self.reader._detect_game_active(img) is True

    def test_red_board_returns_true(self):
        img = _make_image(110, 60, 55)
        assert self.reader._detect_game_active(img) is True

    def test_main_menu_dark_returns_false(self):
        img = _make_image(10, 12, 10)
        assert self.reader._detect_game_active(img) is False

    def test_borderline_at_threshold_returns_true(self):
        v = BOARD_MIN_MEAN_BRIGHTNESS
        img = _make_image(v, v, v)
        assert self.reader._detect_game_active(img) is True

    def test_one_below_threshold_returns_false(self):
        v = BOARD_MIN_MEAN_BRIGHTNESS - 1
        img = _make_image(v, v, v)
        assert self.reader._detect_game_active(img) is False


# ---------------------------------------------------------------------------
# ScreenReader._detect_game_active – OpenCV template-matching path
# ---------------------------------------------------------------------------


class TestDetectGameActiveTemplate:
    """Tests for the OpenCV template-matching code path."""

    def setup_method(self):
        self._cap_patch = patch("src.screen_reader._CAPTURE_AVAILABLE", True)
        self._cap_patch.start()
        self._cv2_patch = patch("src.screen_reader._CV2_AVAILABLE", True)
        self._cv2_patch.start()
        self.reader = ScreenReader.__new__(ScreenReader)
        self.reader._card_detector = ScreenReader._detect_cards_stub

    def teardown_method(self):
        self._cap_patch.stop()
        self._cv2_patch.stop()

    def _mock_cv2_match(self, confidence: float):
        """Return a cv2 module mock where matchTemplate yields *confidence*."""
        import numpy as np

        cv2_mock = MagicMock()
        # imread returns a fake 3-channel array
        cv2_mock.imread.return_value = np.zeros((26, 60, 3), dtype="uint8")
        cv2_mock.cvtColor.return_value = np.zeros((1080, 1440, 3), dtype="uint8")
        cv2_mock.TM_CCOEFF_NORMED = 5
        result_map = np.full((1, 1), confidence, dtype="float32")
        cv2_mock.matchTemplate.return_value = result_map
        cv2_mock.minMaxLoc.return_value = (0.0, float(confidence), None, None)
        return cv2_mock

    def test_high_confidence_returns_true(self):
        """A match score above the threshold → active."""
        img = _make_image(80, 80, 80)
        cv2_mock = self._mock_cv2_match(0.90)
        import numpy as np_real
        np_mock = MagicMock(wraps=np_real)
        with patch("src.screen_reader.cv2", cv2_mock), \
             patch("src.screen_reader.np", np_mock), \
             patch("os.path.isfile", return_value=True):
            assert self.reader._detect_game_active_template(img) is True

    def test_low_confidence_returns_false(self):
        """A match score below the threshold → not active."""
        img = _make_image(80, 80, 80)
        cv2_mock = self._mock_cv2_match(0.30)
        import numpy as np_real
        np_mock = MagicMock(wraps=np_real)
        with patch("src.screen_reader.cv2", cv2_mock), \
             patch("src.screen_reader.np", np_mock), \
             patch("os.path.isfile", return_value=True):
            assert self.reader._detect_game_active_template(img) is False

    def test_missing_template_falls_back_to_brightness(self):
        """When the template file is absent, use brightness probe."""
        img = _make_image(80, 80, 80)  # bright → brightness probe says active
        with patch("src.screen_reader._CV2_AVAILABLE", True), \
             patch("os.path.isfile", return_value=False):
            # _detect_game_active dispatches to brightness probe
            assert self.reader._detect_game_active(img) is True

    def test_none_imread_falls_back_to_brightness(self):
        """When cv2.imread returns None, brightness probe is used."""
        img = _make_image(80, 80, 80)
        cv2_mock = MagicMock()
        cv2_mock.imread.return_value = None
        with patch("src.screen_reader.cv2", cv2_mock), \
             patch("os.path.isfile", return_value=True):
            assert self.reader._detect_game_active_template(img) is True


# ---------------------------------------------------------------------------
# find_hearthstone_window – cross-platform stubs
# ---------------------------------------------------------------------------


class TestFindHearthstoneWindowWin32:
    def test_pygetwindow_found(self):
        mock_win = MagicMock()
        mock_win.title = "Hearthstone"
        mock_win.left = 100
        mock_win.top = 50
        mock_win.width = 1920
        mock_win.height = 1080

        mock_gw = MagicMock()
        mock_gw.getAllWindows.return_value = [mock_win]

        with patch.dict("sys.modules", {"pygetwindow": mock_gw}):
            with patch("sys.platform", "win32"):
                from src import window_finder as wf
                result = wf._find_window_win32()

        assert result == (100, 50, 1920, 1080)

    def test_pygetwindow_no_matching_window_returns_none(self):
        mock_win = MagicMock()
        mock_win.title = "World of Warcraft"

        mock_gw = MagicMock()
        mock_gw.getAllWindows.return_value = [mock_win]

        with patch.dict("sys.modules", {"pygetwindow": mock_gw, "win32gui": None}):
            with patch("sys.platform", "win32"):
                from src import window_finder as wf
                with patch.object(wf, "_find_window_win32", return_value=None):
                    result = wf.find_hearthstone_window()

        assert result is None

    def test_pygetwindow_exception_falls_through(self):
        """When pygetwindow raises, _find_window_win32 returns None gracefully."""
        mock_gw = MagicMock()
        mock_gw.getAllWindows.side_effect = RuntimeError("import error")

        with patch.dict("sys.modules", {"pygetwindow": mock_gw, "win32gui": None}):
            from src import window_finder as wf
            result = wf._find_window_win32()

        assert result is None

    def test_partial_title_match(self):
        """pygetwindow: title 'Hearthstone - Loading' is still matched."""
        mock_win = MagicMock()
        mock_win.title = "Hearthstone - Loading"
        mock_win.left = 0
        mock_win.top = 0
        mock_win.width = 1440
        mock_win.height = 1080

        mock_gw = MagicMock()
        mock_gw.getAllWindows.return_value = [mock_win]

        with patch.dict("sys.modules", {"pygetwindow": mock_gw}):
            from src import window_finder as wf
            result = wf._find_window_win32()

        assert result == (0, 0, 1440, 1080)


class TestFindHearthstoneWindowLinux:
    def test_xdotool_success(self):
        """xdotool fallback still works when python-xlib raises ImportError."""
        search_result = MagicMock()
        search_result.stdout = "12345678\n"

        geo_result = MagicMock()
        geo_result.stdout = "X=0\nY=0\nWIDTH=1920\nHEIGHT=1080\n"

        with patch("subprocess.run", side_effect=[search_result, geo_result]):
            with patch("sys.platform", "linux"):
                from src import window_finder as wf
                # Bypass python-xlib by patching it away
                with patch.dict("sys.modules", {"Xlib": None,
                                                "Xlib.display": None,
                                                "Xlib.X": None,
                                                "Xlib.error": None}):
                    result = wf._find_window_linux_xdotool()

        assert result == (0, 0, 1920, 1080)

    def test_xdotool_no_window_returns_none(self):
        search_result = MagicMock()
        search_result.stdout = ""

        with patch("subprocess.run", return_value=search_result):
            from src import window_finder as wf
            result = wf._find_window_linux_xdotool()

        assert result is None

    def test_xdotool_not_installed_returns_none(self):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            from src import window_finder as wf
            result = wf._find_window_linux_xdotool()

        assert result is None


# ---------------------------------------------------------------------------
# ScreenReader.read_game_state – game_active gate
# ---------------------------------------------------------------------------


class TestReadGameStateGameActiveGate:
    """read_game_state must set game_active=False when the window is absent."""

    def _make_reader(self):
        reader = ScreenReader.__new__(ScreenReader)
        reader._card_detector = ScreenReader._detect_cards_stub
        return reader

    def test_window_not_found_returns_inactive_state(self):
        reader = self._make_reader()

        with patch("src.screen_reader.find_hearthstone_window", return_value=None):
            fake_img = _make_image(10, 10, 10)
            with patch.object(
                reader, "capture_game_window", return_value=(fake_img, False)
            ):
                state = reader.read_game_state()

        assert state.game_active is False

    def test_window_found_board_inactive_returns_false(self):
        reader = self._make_reader()
        dark_img = _make_image(5, 5, 5)

        with patch("src.screen_reader._CV2_AVAILABLE", False), \
             patch.object(
                reader, "capture_game_window", return_value=(dark_img, True)
             ):
            state = reader.read_game_state()

        assert state.game_active is False

    def test_window_found_board_active_returns_true(self):
        reader = self._make_reader()
        board_img = _make_image(120, 90, 60)

        with patch("src.screen_reader._CV2_AVAILABLE", False), \
             patch.object(
                reader, "capture_game_window", return_value=(board_img, True)
             ):
            state = reader.read_game_state()

        assert state.game_active is True
