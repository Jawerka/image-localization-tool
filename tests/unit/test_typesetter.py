"""Вёрстка короткой фразы в прямоугольник и в баллон."""

import cv2
import numpy as np
from PIL import Image, ImageDraw

from src.components import typesetter as typesetter_module
from src.components.typesetter import Typesetter, incremental_dirty_bounds, interior_mask
from src.models import TextRegion, TextStyle
from src.page_pipeline import _layout_scale


def test_document_line_changes_the_image():
    image = Image.new("RGB", (220, 80), "white")
    region = TextRegion(
        id=1,
        bbox=(10, 10, 200, 60),
        class_name="text_free",
        text="Hello",
        translation="Привет",
        block_type="narration",
        style=TextStyle(fill_rgb=(0, 0, 0), alignment="left", font_size=18),
    )
    result, overflow = Typesetter(min_font_size=12, max_font_size=28, lang="ru").render(image, [region])
    assert overflow == []
    dark = int(np.sum(np.any(np.array(result) != 255, axis=2)))
    assert dark > 20


def test_text_position_moves_only_rendered_ink_and_preserves_legacy_pixels():
    image = Image.new("RGB", (260, 100), "white")
    legacy = TextRegion(
        id=1,
        bbox=(20, 20, 80, 50),
        translation="Текст",
        block_type="narration",
        style=TextStyle(font_size_override=22, alignment="left"),
    )
    setter = Typesetter(min_font_size=22, max_font_size=22, lang="ru")
    original, overflow = setter.render(image, [legacy])
    assert overflow == []

    identity = TextRegion.from_dict(legacy.to_dict())
    identity.text_position = (60, 45)
    identity_result, identity_overflow = setter.render(image, [identity])
    assert identity_overflow == []
    assert np.array_equal(np.asarray(original), np.asarray(identity_result))

    moved = TextRegion.from_dict(legacy.to_dict())
    moved.text_position = (190, 45)
    translated, overflow = setter.render(image, [moved])
    assert overflow == []
    assert np.array_equal(np.asarray(original)[:, :, 0] < 128, np.asarray(original)[:, :, 1] < 128)
    legacy_ink = np.asarray(original).min(axis=2) < 200
    moved_ink = np.asarray(translated).min(axis=2) < 200
    ys, xs = np.where(legacy_ink)
    moved_ys, moved_xs = np.where(moved_ink)
    assert xs.mean() < 110
    assert moved_xs.mean() > 150
    assert abs((moved_ys.mean()) - ys.mean()) < 1.0


def test_moved_styled_layer_uses_target_position():
    image = Image.new("RGB", (260, 100), "white")
    region = TextRegion(
        id=1,
        bbox=(20, 20, 80, 50),
        translation="Текст",
        block_type="narration",
        text_position=(190, 45),
        style=TextStyle(font_size_override=22, alignment="left", rotation=5),
    )
    result, overflow = Typesetter(min_font_size=22, max_font_size=22, lang="ru").render(image, [region])
    assert overflow == []
    ys, xs = np.where(np.asarray(result).min(axis=2) < 200)
    assert xs.mean() > 150


def test_render_layer_is_transparent_cropped_and_composes_to_same_pixels():
    image = Image.new("RGB", (180, 90), (245, 240, 230))
    region = TextRegion(
        id=1,
        bbox=(20, 20, 70, 45),
        translation="Кир",
        block_type="narration",
        text_position=(130, 45),
        style=TextStyle(font_size_override=18, stroke_mode="custom", stroke_width=2),
    )
    setter = Typesetter(min_font_size=18, max_font_size=18, lang="ru")
    expected, overflow = setter.render(image.copy(), [TextRegion.from_dict(region.to_dict())], force=True)
    layer, origin, layer_overflow = setter.render_layer(
        image.copy(), [TextRegion.from_dict(region.to_dict())], force=True,
    )
    assert overflow == layer_overflow == []
    assert layer.mode == "RGBA"
    alpha = np.asarray(layer.getchannel("A"))
    assert alpha.max() == 255 and alpha.min() == 0
    assert origin[0] > 80
    composed = image.copy().convert("RGBA")
    composed.alpha_composite(layer, dest=origin)
    assert np.array_equal(np.asarray(composed.convert("RGB")), np.asarray(expected))


def test_base_layer_freezes_layout_without_geometry():
    image = Image.new("RGB", (260, 140), "white")
    raw = TextRegion(
        id=1,
        bbox=(30, 30, 110, 55),
        translation="Повёрнутый текст",
        block_type="narration",
        text_position=(250, 120),
        style=TextStyle(
            font_size_override=18,
            rotation=30,
            warp={
                "version": 2,
                "kind": "mesh",
                "bend": 0.0,
                "quad": None,
                    "mesh": [
                        [col * 110 / 3, row * 55 / 3]
                        for row in range(4)
                        for col in range(4)
                    ],
            },
        ),
    )
    setter = Typesetter(min_font_size=18, max_font_size=18, lang="ru")
    setter.render_layer(image.copy(), [TextRegion.from_dict(raw.to_dict())], force=True)
    layout_on = dict(setter._last_layouts[1])
    layer, origin, _overflow = setter.render_layer(
        image.copy(),
        [TextRegion.from_dict(raw.to_dict())],
        force=True,
        apply_geometry=False,
        trim=False,
    )
    layout_off = dict(setter._last_layouts[1])
    assert layout_on == layout_off
    trimmed, _trimmed_origin, _ = setter.render_layer(
        image.copy(),
        [TextRegion.from_dict(raw.to_dict())],
        force=True,
        apply_geometry=False,
    )
    bounds = setter._last_layer_bounds[1]
    assert abs(origin[0] - bounds[0]) <= 1
    assert abs(origin[1] - bounds[1]) <= 1
    assert layer.size[0] >= trimmed.size[0]
    assert layer.size[1] >= trimmed.size[1]


def test_render_layer_matches_full_render_for_overlapping_regions():
    image = Image.new("RGB", (240, 130), (238, 238, 238))
    regions = [
        TextRegion(id=1, bbox=(25, 30, 100, 48), translation="LEFT", block_type="narration",
                   style=TextStyle(font_size_override=18, fill_rgb=(20, 20, 20))),
        TextRegion(id=2, bbox=(95, 42, 105, 50), translation="RIGHT", block_type="narration",
                   style=TextStyle(font_size_override=18, fill_rgb=(180, 20, 20))),
    ]
    setter = Typesetter(min_font_size=18, max_font_size=18, lang="en")
    expected, overflow = setter.render(image.copy(), [TextRegion.from_dict(r.to_dict()) for r in regions], force=True)
    layer, origin, layer_overflow = setter.render_layer(
        image.copy(), [TextRegion.from_dict(r.to_dict()) for r in regions], force=True,
    )
    composed = image.copy().convert("RGBA")
    composed.alpha_composite(layer, dest=origin)
    assert overflow == layer_overflow
    assert np.array_equal(np.asarray(composed.convert("RGB")), np.asarray(expected))


def test_render_records_per_region_bounds_after_movement_and_warp():
    image = Image.new("RGB", (320, 160), "white")
    regions = [
        TextRegion(
            id=1,
            bbox=(15, 20, 80, 45),
            translation="Первый",
            block_type="narration",
            style=TextStyle(font_size_override=18),
        ),
        TextRegion(
            id=2,
            bbox=(150, 35, 70, 50),
            translation="Mesh",
            block_type="narration",
            text_position=(275, 95),
            style=TextStyle(
                font_size_override=18,
                rotation=12,
                warp={"kind": "mesh", "version": 2, "mesh": [
                    [[0, 0], [23, -2], [46, 2], [69, 0]],
                    [[-1, 16], [22, 14], [47, 18], [70, 16]],
                    [[0, 32], [23, 30], [46, 34], [69, 32]],
                    [[0, 49], [23, 47], [46, 51], [69, 49]],
                ]},
            ),
        ),
    ]
    setter = Typesetter(min_font_size=18, max_font_size=18, lang="en")
    setter.render(image, regions, force=True)
    bounds = setter._last_region_bounds
    assert set(bounds) == {1, 2}
    alpha = np.asarray(setter._last_overlay.getchannel("A"))
    for region_id in (1, 2):
        ys, xs = np.where(alpha > 0)
        left, top, right, bottom = bounds[region_id]
        assert 0 <= left < right <= image.width
        assert 0 <= top < bottom <= image.height
    moved = bounds[2]
    assert moved[0] > 180 and moved[1] > 45


def test_overlay_crop_composition_matches_full_alpha_composition():
    from src.components.typesetter import compose_overlay_crop

    yy, xx = np.mgrid[:72, :144]
    clean_array = np.stack(((xx * 3) % 256, (yy * 5) % 256, ((xx + yy) * 7) % 256), axis=2).astype(np.uint8)
    clean = Image.fromarray(clean_array, "RGB")
    old_overlay = Image.new("RGBA", clean.size, (0, 0, 0, 0))
    ImageDraw.Draw(old_overlay).text((20, 24), "OLD", fill=(20, 40, 80, 255))
    previous = Image.alpha_composite(clean.convert("RGBA"), old_overlay).convert("RGB")
    new_overlay = Image.new("RGBA", clean.size, (0, 0, 0, 0))
    ImageDraw.Draw(new_overlay).text((88, 30), "NEW", fill=(180, 30, 10, 210))
    old_bounds = old_overlay.getchannel("A").getbbox()
    new_bounds = new_overlay.getchannel("A").getbbox()
    dirty = (
        min(old_bounds[0], new_bounds[0]),
        min(old_bounds[1], new_bounds[1]),
        max(old_bounds[2], new_bounds[2]),
        max(old_bounds[3], new_bounds[3]),
    )

    actual = compose_overlay_crop(clean, previous, new_overlay, dirty)
    expected = Image.alpha_composite(clean.convert("RGBA"), new_overlay).convert("RGB")
    assert np.array_equal(np.asarray(actual), np.asarray(expected))


def test_version_two_mesh_uses_exact_forward_mapper(monkeypatch):
    from src.components import text_mesh

    calls = []
    original = text_mesh.warp_mesh_forward

    def spy(image, mesh):
        calls.append(mesh)
        return original(image, mesh)

    monkeypatch.setattr(text_mesh, "warp_mesh_forward", spy)
    region = TextRegion(
        id=1,
        bbox=(10, 10, 180, 60),
        translation="Текст",
        block_type="narration",
        style=TextStyle(warp={"kind": "mesh", "version": 2, "mesh": [
            [0, 0], [60, 0], [120, 0], [180, 0],
            [0, 20], [60, 20], [120, 20], [180, 20],
            [0, 40], [60, 40], [120, 40], [180, 40],
            [0, 60], [60, 60], [120, 60], [180, 60],
        ]}),
    )
    result, overflow = Typesetter(min_font_size=12, max_font_size=20).render(
        Image.new("RGB", (220, 100), "white"), [region],
    )
    assert result.size == (220, 100)
    assert overflow == []
    assert calls


def test_bubble_interior_stays_inside_the_outline():
    image = Image.new("RGB", (160, 100), "white")
    draw = ImageDraw.Draw(image)
    draw.ellipse((10, 10, 150, 90), outline="black", width=3)
    region = TextRegion(
        id=1,
        bbox=(40, 35, 80, 30),
        bubble_bbox=(10, 10, 140, 80),
        translation="Да",
        block_type="dialogue",
        style=TextStyle(fill_rgb=(0, 0, 0)),
    )
    mask = interior_mask(np.array(image), region)
    assert mask[50, 80] == 255
    assert mask[0, 0] == 0
    result, overflow = Typesetter(min_font_size=12, max_font_size=36).render(image, [region])
    assert result.size == image.size
    assert overflow == []


def test_dark_spot_does_not_punch_a_hole_in_interior():
    image = Image.new("RGB", (160, 100), "white")
    draw = ImageDraw.Draw(image)
    draw.ellipse((10, 10, 150, 90), outline="black", width=3)
    draw.rectangle((96, 40, 116, 58), fill="black")
    region = TextRegion(
        id=1,
        bbox=(40, 35, 80, 30),
        bubble_bbox=(10, 10, 140, 80),
        translation="Да",
        block_type="dialogue",
        style=TextStyle(fill_rgb=(0, 0, 0)),
    )
    mask = interior_mask(np.array(image), region)
    assert mask[49, 106] == 255
    assert mask[50, 80] == 255
    assert mask[0, 0] == 0


def test_halo_recolors_pixels_beside_letters():
    background = (250, 250, 250)
    image = Image.new("RGB", (240, 90), background)
    region = TextRegion(
        id=1,
        bbox=(10, 10, 220, 70),
        class_name="text_free",
        text="Hello",
        translation="Привет",
        block_type="narration",
        style=TextStyle(fill_rgb=(0, 0, 0), alignment="center"),
    )
    setter = Typesetter(min_font_size=22, max_font_size=22, lang="ru", stroke_ratio=0.2)
    clean, overflow = setter.render(image, [region])
    assert overflow == []
    clean_arr = np.array(clean)
    dark = np.all(clean_arr < 60, axis=2)
    ring = (cv2.dilate(dark.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0) & ~dark
    assert int(ring.sum()) > 10

    dirty_arr = np.full_like(clean_arr, background)
    dirty_arr[ring] = (180, 180, 180)
    painted, overflow = setter.render(Image.fromarray(dirty_arr), [region])
    assert overflow == []
    painted_arr = np.array(painted)
    still_dirt = np.all(np.abs(painted_arr.astype(np.int16) - 180) <= 2, axis=2) & ring
    recolored = np.all(np.abs(painted_arr.astype(np.int16) - 250) <= 2, axis=2) & ring
    assert int(still_dirt.sum()) * 4 < int(ring.sum())
    assert int(recolored.sum()) > 10


def test_font_size_override_skips_binary_search(monkeypatch):
    calls = []
    real_load = typesetter_module._load_font

    def spy(path, size):
        calls.append(size)
        return real_load(path, size)

    monkeypatch.setattr(typesetter_module, "_load_font", spy)
    image = Image.new("RGB", (220, 80), "white")
    region = TextRegion(
        id=7,
        bbox=(10, 10, 200, 60),
        translation="Привет",
        block_type="narration",
        overflow=True,
        style=TextStyle(fill_rgb=(0, 0, 0), alignment="left", font_size_override=21),
    )
    empty = TextRegion(
        id=8,
        bbox=(10, 10, 40, 20),
        translation="",
        overflow=True,
    )
    _result, overflow = Typesetter(min_font_size=12, max_font_size=40, lang="ru").render(
        image, [region, empty]
    )
    assert calls == [21]
    assert region.overflow is (7 in overflow)
    assert empty.overflow is False


def _speech_bubble(phrase: str):
    image = Image.new("RGB", (360, 220), "white")
    draw = ImageDraw.Draw(image)
    draw.ellipse((16, 16, 344, 204), outline="black", width=4)
    region = TextRegion(
        id=1,
        bbox=(48, 48, 264, 124),
        bubble_bbox=(16, 16, 328, 188),
        translation=phrase,
        block_type="dialogue",
        style=TextStyle(fill_rgb=(0, 0, 0)),
    )
    return image, region


def test_margin_keeps_glyphs_inside_the_inset():
    from src.components.typesetter import inset_layout_mask, layout_inset_px

    phrase = "Это довольно длинная фраза для проверки запаса"
    image, region = _speech_bubble(phrase)
    margin = 0.08
    setter = Typesetter(min_font_size=10, max_font_size=48, lang="ru", margin_ratio=margin)
    result, overflow = setter.render(image, [region])
    assert overflow == []
    inset = layout_inset_px(region, margin)
    assert inset == 3
    interior = interior_mask(np.array(image), region)
    allowed = inset_layout_mask(interior, inset)
    changed = np.any(np.array(result) != np.array(image), axis=2)
    assert int(changed.sum()) > 20
    assert not np.any(changed & (allowed == 0))


def test_stroke_and_margin_pick_a_smaller_size():
    phrase = "Длинная реплика которая занимает почти весь баллон целиком"
    image, plain = _speech_bubble(phrase)
    _image, stroked = _speech_bubble(phrase)
    _image, margined = _speech_bubble(phrase)
    base = Typesetter(min_font_size=10, max_font_size=64, lang="ru")
    with_stroke = Typesetter(min_font_size=10, max_font_size=64, lang="ru", stroke_ratio=0.2)
    with_margin = Typesetter(min_font_size=10, max_font_size=64, lang="ru", margin_ratio=0.12)
    base.render(image, [plain])
    with_stroke.render(image, [stroked])
    with_margin.render(image, [margined])
    assert plain.style.font_size > stroked.style.font_size
    # Новый перенос может сохранить кегль, перераспределив слова по строкам.
    assert plain.style.font_size >= margined.style.font_size


def test_zero_margin_does_not_shrink_the_bubble():
    from src.components.typesetter import layout_inset_px

    phrase = "Короткая"
    image, region = _speech_bubble(phrase)
    other_image, other = _speech_bubble(phrase)
    Typesetter(min_font_size=12, max_font_size=40, lang="ru", margin_ratio=0, stroke_ratio=0).render(
        image, [region]
    )
    Typesetter(min_font_size=12, max_font_size=40, lang="ru").render(other_image, [other])
    assert region.style.font_size == other.style.font_size
    assert layout_inset_px(region, 0) == 0
    narration = TextRegion(
        id=2,
        bbox=(0, 0, 100, 40),
        translation="Текст",
        block_type="narration",
    )
    sfx = TextRegion(id=3, bbox=(0, 0, 80, 40), bubble_bbox=(0, 0, 80, 40), block_type="sfx")
    assert layout_inset_px(narration, 0.08) == 0
    assert layout_inset_px(sfx, 0.08) == 0


def test_sfx_long_text_shrinks_instead_of_overflow():
    image = Image.new("RGB", (180, 56), "white")
    region = TextRegion(
        id=4,
        bbox=(8, 8, 164, 40),
        translation="БАБАХГРОХОТ",
        block_type="sfx",
        style=TextStyle(fill_rgb=(0, 0, 0)),
    )
    _result, overflow = Typesetter(min_font_size=10, max_font_size=48, lang="ru").render(
        image, [region],
    )
    assert overflow == []
    assert region.overflow is False
    assert 10 <= region.style.font_size < 48


def test_black_bubble_is_drawn_in_white():
    image = Image.new("RGB", (180, 120), "white")
    draw = ImageDraw.Draw(image)
    draw.ellipse((10, 10, 170, 110), fill="black")
    region = TextRegion(
        id=1,
        bbox=(50, 45, 80, 30),
        bubble_bbox=(10, 10, 160, 100),
        translation="Да",
        block_type="dialogue",
        style=TextStyle(fill_rgb=(0, 0, 0)),
    )
    result, overflow = Typesetter(min_font_size=16, max_font_size=28, lang="ru").render(image, [region])
    assert overflow == []
    light = np.all(np.array(result) > 200, axis=2)
    assert int(light.sum()) > 10
    assert region.style.fill_rgb == (255, 255, 255)


def test_locked_black_on_black_bubble_stays_black():
    image = Image.new("RGB", (180, 120), "white")
    draw = ImageDraw.Draw(image)
    draw.ellipse((10, 10, 170, 110), fill="black")
    region = TextRegion(
        id=1,
        bbox=(50, 45, 80, 30),
        bubble_bbox=(10, 10, 160, 100),
        translation="Да",
        block_type="dialogue",
        style=TextStyle(fill_rgb=(0, 0, 0), fill_locked=True),
    )
    before = np.array(image)
    result, overflow = Typesetter(min_font_size=16, max_font_size=28, lang="ru").render(image, [region])
    assert overflow == []
    assert region.style.fill_rgb == (0, 0, 0)
    after = np.array(result)
    was_dark = np.all(before < 40, axis=2)
    now_light = np.all(after > 200, axis=2)
    assert int((was_dark & now_light).sum()) == 0


def test_readable_red_on_white_stays_red():
    image = Image.new("RGB", (220, 80), "white")
    region = TextRegion(
        id=1,
        bbox=(10, 10, 200, 60),
        translation="Привет",
        block_type="narration",
        style=TextStyle(fill_rgb=(220, 20, 20), alignment="left"),
    )
    result, overflow = Typesetter(min_font_size=18, max_font_size=18, lang="ru").render(image, [region])
    assert overflow == []
    assert region.style.fill_rgb == (220, 20, 20)
    red = np.array(result)
    assert int(np.sum((red[:, :, 0] > 150) & (red[:, :, 1] < 80))) > 10


def test_override_below_minimum_draws_at_minimum():
    image = Image.new("RGB", (220, 80), "white")
    region = TextRegion(
        id=5,
        bbox=(10, 10, 200, 60),
        translation="Привет",
        block_type="narration",
        style=TextStyle(fill_rgb=(0, 0, 0), alignment="left", font_size_override=5),
    )
    _result, overflow = Typesetter(min_font_size=10, max_font_size=40, lang="ru").render(
        image, [region],
    )
    assert overflow == []
    assert region.style.font_size == 10


def test_steep_sfx_stays_inside_its_box():
    """Вертикальный звук с поворотом 72° не закрашивает баллон сверху."""
    image = Image.new("RGB", (400, 500), "white")
    region = TextRegion(
        id=11,
        bbox=(160, 250, 80, 180),
        translation="СЖАТЬ",
        block_type="sfx",
        style=TextStyle(
            fill_rgb=(0, 0, 0),
            font_size_override=28,
            rotation=72,
            stroke_mode="none",
            warp={"kind": "arc", "bend": 0.34, "quad": None, "mesh": None},
        ),
    )
    result, overflow = Typesetter(min_font_size=10, max_font_size=40, lang="ru").render(
        image, [region],
    )
    assert overflow == []
    ink = np.any(np.array(result) < 40, axis=2)
    ys, xs = np.nonzero(ink)
    assert len(xs) > 10
    x, y, w, h = region.bbox
    assert x <= float(xs.mean()) <= x + w
    assert y <= float(ys.mean()) <= y + h
    assert not np.any(ink[: y])


def test_layout_scale_lifts_small_page_to_2000():
    image = Image.new("RGB", (605, 850), "white")
    work, scale = _layout_scale(image, 2000)
    assert max(work.size) == 2000
    assert abs(scale - 2000 / 850) < 1e-6
    large = Image.new("RGB", (1400, 2100), "white")
    same, one = _layout_scale(large, 2000)
    assert same.size == large.size
    assert one == 1.0


def test_field_center_and_bbox_mesh_mapping():
    from src.components.typesetter import _bbox_local_to_layer, _field_center

    region = TextRegion(id=1, bbox=(100, 50, 80, 40), bubble_bbox=(100, 50, 80, 40))
    assert _field_center(region, (0.0, 0.0)) == (140.0, 70.0)
    mapped = _bbox_local_to_layer([[0, 0], [80, 40]], region, origin_x=90.0, origin_y=40.0, scale=2.0)
    assert mapped == [[20.0, 20.0], [180.0, 100.0]]


def test_rotate_layer_uses_explicit_pivot():
    """Явный pivot даёт другую точку назначения, чем поворот вокруг центра кадра."""
    from src.components.typesetter import _rotate_layer

    layer = Image.new("RGBA", (20, 10), (0, 0, 0, 0))
    point = (19.0, 5.0)
    around_origin, moved_origin = _rotate_layer(layer, 45.0, point, pivot=(0.0, 0.0))
    around_center, moved_center = _rotate_layer(layer, 45.0, point, pivot=None)
    assert around_origin.size[0] >= 10
    assert around_center.size[0] >= 10
    assert moved_origin != moved_center


def test_short_reply_cap_follows_neighbors():
    from src.components.typesetter import _short_reply_cap

    short = TextRegion(
        id=1,
        bbox=(10, 10, 40, 40),
        bubble_bbox=(10, 10, 40, 40),
        translation="Да",
        block_type="dialogue",
        style=TextStyle(font_size=12),
    )
    neighbor = TextRegion(
        id=2,
        bbox=(60, 10, 80, 40),
        bubble_bbox=(60, 10, 80, 40),
        translation="Длинная соседняя реплика",
        block_type="dialogue",
        style=TextStyle(font_size=18),
    )
    capped = _short_reply_cap(48, short, [short, neighbor], min_font=10, interior_h=48)
    assert capped <= int(round(18 * 1.15))
    assert capped >= 10


def test_incremental_render_matches_full_for_moved_styled_text():
    image = Image.new("RGB", (320, 180), (244, 238, 230))
    previous = TextRegion(
        id=1, bbox=(15, 20, 95, 55), translation="Старый текст",
        block_type="narration", style=TextStyle(font_size_override=19, alignment="left"),
    )
    old_setter = Typesetter(min_font_size=19, max_font_size=19, lang="ru")
    previous_result, _ = old_setter.render(image, [TextRegion.from_dict(previous.to_dict())], force=True)
    previous_bounds = dict(old_setter._last_region_bounds)

    current = TextRegion.from_dict(previous.to_dict())
    current.translation = "Новый"
    current.text_position = (220, 100)
    current.style.rotation = 4
    incremental_setter = Typesetter(min_font_size=19, max_font_size=19, lang="ru")
    incremental, overflow, details = incremental_setter.render_incremental(
        image, [TextRegion.from_dict(current.to_dict())], [TextRegion.from_dict(previous.to_dict())],
        previous_result, previous_bounds, [1], force=True,
    )
    full_setter = Typesetter(min_font_size=19, max_font_size=19, lang="ru")
    full, full_overflow = full_setter.render(image, [TextRegion.from_dict(current.to_dict())], force=True)
    assert overflow == full_overflow == []
    assert details["mode"] == "full"  # Старые и новые чернила дальше порога 25%.
    assert np.array_equal(np.asarray(incremental), np.asarray(full))


def test_dirty_bounds_include_dependent_bubbles_and_missing_metadata_falls_back():
    a = TextRegion(id=1, bbox=(0, 0, 40, 30), bubble_bbox=(0, 0, 80, 50), translation="A")
    b = TextRegion(id=2, bbox=(90, 0, 40, 30), bubble_bbox=(85, 0, 80, 50), translation="B")
    bounds = {1: (5, 5, 20, 20), 2: (95, 5, 110, 20)}
    same_a = TextRegion.from_dict(a.to_dict())
    same_b = TextRegion.from_dict(b.to_dict())
    same_a.translation = "Изменено"
    dirty = incremental_dirty_bounds([a, b], [same_a, same_b], bounds, bounds, [1], (200, 100))
    assert dirty == (5, 5, 110, 20)
    assert incremental_dirty_bounds([a], [a], {}, {}, [1], (200, 100)) is None
    assert incremental_dirty_bounds([a], [], bounds, {}, [1], (200, 100)) is None


def test_incremental_render_uses_partial_crop_and_matches_full_pixels():
    image = Image.new("RGB", (320, 180), (244, 238, 230))
    old_region = TextRegion(
        id=1, bbox=(35, 40, 100, 45), translation="ONE",
        block_type="narration", style=TextStyle(font_size_override=20),
    )
    old_renderer = Typesetter(min_font_size=20, max_font_size=20, lang="en")
    previous, _ = old_renderer.render(image, [TextRegion.from_dict(old_region.to_dict())], force=True)
    current = TextRegion.from_dict(old_region.to_dict())
    current.translation = "TWO"
    incremental_renderer = Typesetter(min_font_size=20, max_font_size=20, lang="en")
    partial, _, details = incremental_renderer.render_incremental(
        image, [TextRegion.from_dict(current.to_dict())], [TextRegion.from_dict(old_region.to_dict())],
        previous, old_renderer._last_region_bounds, [1], force=True,
    )
    full, _ = Typesetter(min_font_size=20, max_font_size=20, lang="en").render(
        image, [TextRegion.from_dict(current.to_dict())], force=True,
    )
    assert details["mode"] == "partial"
    assert details["dirty_pixels"] / (320 * 180) <= 0.25
    assert np.array_equal(np.asarray(partial), np.asarray(full))


def test_incremental_composition_matches_full_for_rotated_mesh_text():
    image = Image.new("RGB", (320, 180), (240, 240, 240))
    previous = TextRegion(
        id=4, bbox=(70, 50, 90, 45), translation="MESH",
        block_type="narration",
        style=TextStyle(font_size_override=18, rotation=3, warp={
            "kind": "mesh", "version": 2, "mesh": [
                [0, 0], [29, -1], [59, 1], [89, 0],
                [-1, 14], [29, 13], [60, 15], [90, 14],
                [0, 29], [30, 30], [60, 28], [89, 29],
                [1, 44], [30, 43], [59, 45], [90, 44],
            ],
        }),
    )
    old_renderer = Typesetter(min_font_size=18, max_font_size=18, lang="en")
    old_result, _ = old_renderer.render(image, [TextRegion.from_dict(previous.to_dict())], force=True)
    current = TextRegion.from_dict(previous.to_dict())
    current.translation = "TEXT"
    incremental, _, details = Typesetter(min_font_size=18, max_font_size=18, lang="en").render_incremental(
        image, [TextRegion.from_dict(current.to_dict())], [TextRegion.from_dict(previous.to_dict())],
        old_result, old_renderer._last_region_bounds, [4], force=True,
    )
    full, _ = Typesetter(min_font_size=18, max_font_size=18, lang="en").render(
        image, [TextRegion.from_dict(current.to_dict())], force=True,
    )
    assert details["mode"] == "partial"
    assert np.array_equal(np.asarray(incremental), np.asarray(full))


def test_incremental_composition_matches_full_for_arc_and_perspective():
    image = Image.new("RGB", (320, 180), (242, 242, 242))
    warps = [
        {"kind": "arc", "bend": 0.18, "quad": None, "mesh": None},
        {"kind": "perspective", "bend": 0.0,
         "quad": [[3, 2], [86, 0], [90, 42], [1, 43]], "mesh": None},
    ]
    for index, warp in enumerate(warps, start=1):
        previous = TextRegion(
            id=index, bbox=(70, 50, 90, 45), translation="OLD",
            block_type="narration", style=TextStyle(font_size_override=18, warp=warp),
        )
        old_renderer = Typesetter(min_font_size=18, max_font_size=18, lang="en")
        old_result, _ = old_renderer.render(image, [TextRegion.from_dict(previous.to_dict())], force=True)
        current = TextRegion.from_dict(previous.to_dict())
        current.translation = "NEW"
        incremental, _, details = Typesetter(min_font_size=18, max_font_size=18, lang="en").render_incremental(
            image, [TextRegion.from_dict(current.to_dict())], [TextRegion.from_dict(previous.to_dict())],
            old_result, old_renderer._last_region_bounds, [index], force=True,
        )
        full, _ = Typesetter(min_font_size=18, max_font_size=18, lang="en").render(
            image, [TextRegion.from_dict(current.to_dict())], force=True,
        )
        assert details["mode"] == "partial"
        assert np.array_equal(np.asarray(incremental), np.asarray(full))

def test_frozen_layout_survives_rotation_change():
    image = Image.new("RGB", (400, 300), "white")
    region = TextRegion(
        id=1,
        bbox=(80, 80, 160, 75),
        translation="This is a longer sentence for a rotation layout comparison",
        block_type="dialogue",
        style=TextStyle(),
    )
    setter = Typesetter(min_font_size=10, max_font_size=28, lang="en")
    setter.render_layer(
        image.copy(), [TextRegion.from_dict(region.to_dict())],
        force=True, apply_geometry=False, trim=False,
    )
    snapshot = dict(setter._last_layouts[1])

    frozen = TextRegion.from_dict(region.to_dict())
    frozen.layout_snapshot = snapshot
    frozen.style.rotation = 35
    setter.render_layer(
        image.copy(), [frozen], force=True, apply_geometry=False, trim=False,
    )
    frozen_layout = dict(setter._last_layouts[1])

    fresh = TextRegion.from_dict(region.to_dict())
    fresh.style.rotation = 35
    setter.render_layer(
        image.copy(), [fresh], force=True, apply_geometry=False, trim=False,
    )
    fresh_layout = dict(setter._last_layouts[1])

    assert frozen_layout["font_size"] == snapshot["font_size"]
    assert frozen_layout["lines"] == snapshot["lines"]
    assert fresh_layout["lines"] != snapshot["lines"]

    setter.render(
        image.copy(), [TextRegion.from_dict(frozen.to_dict())], force=True,
    )
    assert setter._last_layouts[1]["lines"] == snapshot["lines"]


def test_base_layer_extent_is_independent_of_warp_and_rotation():
    image = Image.new("RGB", (600, 500), "white")
    region = TextRegion(
        id=1,
        bbox=(150, 150, 160, 75),
        translation="This is a longer sentence",
        block_type="narration",
        style=TextStyle(font_size_override=18, warp={"kind": "arc", "bend": 0.0}),
    )
    setter = Typesetter(min_font_size=18, max_font_size=18, lang="en")
    base, _origin, _ = setter.render_layer(
        image.copy(), [TextRegion.from_dict(region.to_dict())],
        force=True, apply_geometry=False, trim=False,
    )
    snapshot = dict(setter._last_layouts[1])
    changed = TextRegion.from_dict(region.to_dict())
    changed.layout_snapshot = snapshot
    changed.style.rotation = 30
    changed.style.warp = {"kind": "arc", "bend": 0.4}
    warped, _origin, _ = setter.render_layer(
        image.copy(), [changed], force=True, apply_geometry=False, trim=False,
    )
    assert warped.size == base.size

def test_pre_rotated_base_layer_without_snapshot_uses_stable_extent():
    image = Image.new("RGB", (600, 500), "white")
    for kind in ("arc", "wave", "flag", "ring"):
        region = TextRegion(
            id=1,
            bbox=(150, 150, 160, 75),
            translation="This is a longer sentence",
            block_type="narration",
            style=TextStyle(
                font_size_override=18,
                rotation=35,
                warp={"kind": kind, "bend": 0.4},
            ),
        )
        setter = Typesetter(min_font_size=18, max_font_size=18, lang="en")
        first = TextRegion.from_dict(region.to_dict())
        first.style.warp = {"kind": "none"}
        layer, origin, _ = setter.render_layer(
            image.copy(), [first],
            force=True, apply_geometry=True, trim=False,
            capture=True, stable_pad=True,
        )
        snapshot = dict(setter._last_layouts[1])
        repeated = TextRegion.from_dict(region.to_dict())
        repeated.style.warp = {"kind": "none"}
        repeated.layout_snapshot = snapshot
        next_layer, next_origin, _ = setter.render_layer(
            image.copy(), [repeated],
            force=True, apply_geometry=True, trim=False,
            capture=True, stable_pad=True,
        )
        assert next_layer.size == layer.size, kind
        assert next_origin == origin, kind


def test_base_layer_keeps_padding_outside_page_edges():
    image = Image.new("RGB", (140, 100), "white")
    region = TextRegion(
        id=1,
        bbox=(0, 0, 100, 50),
        translation="EDGE",
        block_type="narration",
        style=TextStyle(font_size_override=18),
    )
    layer, origin, _overflow = Typesetter(
        min_font_size=18, max_font_size=18, lang="en"
    ).render_layer(
        image, [region], force=True, apply_geometry=False, trim=False,
    )
    assert origin[0] < 0 or origin[1] < 0
    assert origin[0] + layer.width > image.width or origin[1] + layer.height > image.height

def test_frozen_layout_survives_missing_font_file():
    image = Image.new("RGB", (240, 120), "white")
    region = TextRegion(
        id=1,
        bbox=(20, 20, 120, 50),
        translation="MISSING FONT",
        block_type="narration",
        style=TextStyle(font_size_override=18, font_id="no-such-font"),
    )
    setter = Typesetter(min_font_size=18, max_font_size=18, lang="en")
    setter.render_layer(
        image, [TextRegion.from_dict(region.to_dict())],
        force=True, apply_geometry=False, trim=False,
    )
    snapshot = dict(setter._last_layouts[1])
    snapshot["font"] = "definitely-missing-font.ttf"

    frozen = TextRegion.from_dict(region.to_dict())
    frozen.layout_snapshot = snapshot
    rendered, overflow = setter.render(image, [frozen], force=True)
    assert overflow == []
    assert setter._last_layouts[1]["lines"] == snapshot["lines"]
    assert rendered.size == image.size
