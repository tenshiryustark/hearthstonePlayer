# Screen-reader template assets

## `end_turn_button.png`

This image is used by `ScreenReader._detect_game_active` to determine whether
a Hearthstone match is currently in progress via OpenCV template matching.

**The file shipped in this repository is a placeholder.**  Replace it with a
real crop taken from a live Hearthstone screenshot before running the agent.

### How to capture the real template

1. Start Hearthstone and enter a match.
2. Take a screenshot of the full game window (e.g. with the built-in Windows
   Snipping Tool, `scrot` on Linux, or `⌘⇧4` on macOS).
3. Crop a ~60 × 26 px region centred on the **End Turn** button.  In a
   1440 × 1080 window the button sits at roughly:

   ```
   left  ≈ 1220 px   top  ≈ 517 px   right ≈ 1280 px   bottom ≈ 543 px
   ```

4. Save the crop as `end_turn_button.png` and overwrite this file.

The button's stone-grey oval shape does **not** change between patches or board
themes, so one captured template works across all sessions.
