from PIL import Image
import numpy as np

from src.components.flood_fill import fill_preview_png, flood_region, paint_region


def test_flood_is_4_connected():
    image = Image.new("RGB", (3, 3), "white")
    for x in range(3):
        image.putpixel((x, x), (0, 0, 0))
    region = flood_region(image, (0, 0), 0)
    assert int(region.sum()) == 1


def test_flood_stops_at_color_and_separate_island():
    image = Image.new("RGB", (10, 4), "white")
    for y in range(4):
        image.putpixel((4, y), (0, 0, 0))
        image.putpixel((5, y), (0, 0, 0))
    region = flood_region(image, (0, 0), 0)
    assert region[0, 0] and region[0, 3]
    assert not region[0, 4]
    assert not region[0, 9]
    assert flood_region(image, (9, 0), 0)[0, 9]


def test_flood_tolerance_catches_close_colors():
    image = Image.new("RGB", (9, 2), "white")
    for x in range(3, 6):
        for y in range(2):
            image.putpixel((x, y), (235, 235, 235))
    strict = flood_region(image, (0, 0), 0)
    assert not strict[0, 4]
    wide = flood_region(image, (0, 0), 60)
    assert wide[0, 6]


def test_flood_seed_outside_is_empty():
    image = Image.new("RGB", (4, 4), "white")
    assert not flood_region(image, (-1, 0), 50).any()
    assert not flood_region(image, (4, 4), 50).any()


def test_paint_region_sets_and_clears():
    mask = np.zeros((4, 4), dtype=np.uint8)
    region = np.zeros((4, 4), dtype=bool)
    region[1:3, 1:3] = True
    paint_region(mask, region, "flood")
    assert mask[1, 1] == 255 and mask[0, 0] == 0
    paint_region(mask, region, "erase_flood")
    assert mask[1, 1] == 0


def test_fill_preview_crops_region():
    image = Image.new("RGB", (10, 10), "white")
    image.putpixel((3, 3), (0, 0, 0))
    png, x, y = fill_preview_png(image, (0, 0), 0, "flood")
    assert png.startswith(b"\x89PNG")
    assert (x, y) == (0, 0)
