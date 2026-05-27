"""Tests for Phase 2: Date Overlay (DO-01..DO-05).

These tests target functions and config keys that Plans 02-02 and 02-03 will create.
They MUST fail (RED) until those plans land — that is the TDD contract.
"""
import pytest
from PIL import Image


# --- DO-01: Date parsing ---------------------------------------------------

def test_parse_exif_date():
    """DO-01: EXIF format 'YYYY:MM:DD HH:MM:SS' -> 'DD.MM.YYYY'."""
    from app import parse_photo_date
    assert parse_photo_date("2022:01:05 14:30:00") == "05.01.2022"


def test_parse_immich_date():
    """DO-01: Immich ISO 8601 'YYYY-MM-DDTHH:MM:SS.sssZ' -> 'DD.MM.YYYY'."""
    from app import parse_photo_date
    assert parse_photo_date("2022-01-05T14:30:00.000Z") == "05.01.2022"


def test_parse_none():
    """DO-01: None or empty input -> None."""
    from app import parse_photo_date
    assert parse_photo_date(None) is None
    assert parse_photo_date("") is None
    assert parse_photo_date("not-a-date") is None


# --- DO-02: Overlay rendering ----------------------------------------------

def test_draw_overlay_renders(blank_rgb_image, dejavu_or_default_font):
    """DO-02: draw_date_overlay modifies the image pixels (renders rect+text)."""
    from app import draw_date_overlay
    # Snapshot: all pixels start white
    before = blank_rgb_image.copy()
    draw_date_overlay(blank_rgb_image, "05.01.2022",
                      dejavu_or_default_font, "bottomRight", padding=6)
    # After overlay, the image must differ (black background rect must be present)
    assert list(blank_rgb_image.getdata()) != list(before.getdata())
    # Bottom-right corner area should contain at least one black pixel (the rect bg)
    found_black = False
    w, h = blank_rgb_image.size
    for x in range(w - 80, w):
        for y in range(h - 40, h):
            if blank_rgb_image.getpixel((x, y)) == (0, 0, 0):
                found_black = True
                break
        if found_black:
            break
    assert found_black, "Expected at least one black pixel in bottom-right region"


# --- DO-03: Overlay disabled / silently hidden -----------------------------

def test_overlay_disabled(monkeypatch, large_rgb_image):
    """DO-03: When date_overlay_enabled=False, scale_img_in_memory does not draw overlay."""
    import app
    monkeypatch.setattr(app, "date_overlay_enabled", False)
    monkeypatch.setattr(app, "date_overlay_position", "bottomRight")
    # Call with an Immich-style date — overlay must STILL not appear
    result_io = app.scale_img_in_memory(
        large_rgb_image, immich_date_raw="2022-01-05T14:30:00.000Z")
    result_io.seek(0)
    result_img = Image.open(result_io).convert("RGB")
    # Any near-black pixel would indicate overlay drew something — must be none
    pixels = list(result_img.getdata())
    black_count = sum(1 for p in pixels if p == (0, 0, 0))
    assert black_count == 0, f"Expected 0 black pixels with overlay disabled, found {black_count}"


def test_overlay_no_date(monkeypatch, large_rgb_image):
    """DO-03: When enabled but date is None and EXIF absent, overlay silently hidden."""
    import app
    monkeypatch.setattr(app, "date_overlay_enabled", True)
    monkeypatch.setattr(app, "date_overlay_position", "bottomRight")
    # Plain white image with no EXIF; immich_date_raw is None
    result_io = app.scale_img_in_memory(large_rgb_image, immich_date_raw=None)
    result_io.seek(0)
    result_img = Image.open(result_io).convert("RGB")
    pixels = list(result_img.getdata())
    black_count = sum(1 for p in pixels if p == (0, 0, 0))
    assert black_count == 0, f"Expected 0 black pixels with no date, found {black_count}"


# --- DO-04: Position mapping -----------------------------------------------

def test_position_topleft(blank_rgb_image, dejavu_or_default_font):
    """DO-04: position='topLeft' places overlay in top-left region."""
    from app import draw_date_overlay
    draw_date_overlay(blank_rgb_image, "05.01.2022",
                      dejavu_or_default_font, "topLeft", padding=6)
    # Top-left 80x40 region must contain at least one black pixel
    found = any(
        blank_rgb_image.getpixel((x, y)) == (0, 0, 0)
        for x in range(0, 80) for y in range(0, 40)
    )
    assert found, "Expected black pixel in top-left region"
    # Bottom-right 80x40 region must NOT contain a black pixel
    w, h = blank_rgb_image.size
    bottom_right_black = any(
        blank_rgb_image.getpixel((x, y)) == (0, 0, 0)
        for x in range(w - 80, w) for y in range(h - 40, h)
    )
    assert not bottom_right_black, "Did not expect overlay in bottom-right"


def test_position_bottomright(blank_rgb_image, dejavu_or_default_font):
    """DO-04: position='bottomRight' places overlay in bottom-right region."""
    from app import draw_date_overlay
    draw_date_overlay(blank_rgb_image, "05.01.2022",
                      dejavu_or_default_font, "bottomRight", padding=6)
    w, h = blank_rgb_image.size
    found = any(
        blank_rgb_image.getpixel((x, y)) == (0, 0, 0)
        for x in range(w - 80, w) for y in range(h - 40, h)
    )
    assert found, "Expected black pixel in bottom-right region"
    # Top-left must NOT contain a black pixel
    top_left_black = any(
        blank_rgb_image.getpixel((x, y)) == (0, 0, 0)
        for x in range(0, 80) for y in range(0, 40)
    )
    assert not top_left_black, "Did not expect overlay in top-left"


# --- DO-05: Config defaults ------------------------------------------------

def test_default_config():
    """DO-05: DEFAULT_CONFIG['immich'] has date_overlay_enabled=False and date_overlay_position='bottomRight'."""
    from app import DEFAULT_CONFIG
    assert DEFAULT_CONFIG["immich"].get("date_overlay_enabled") is False, \
        "date_overlay_enabled must default to False (D-01)"
    assert DEFAULT_CONFIG["immich"].get("date_overlay_position") == "bottomRight", \
        "date_overlay_position must default to 'bottomRight' (D-05)"
