"""Общие векторы и ограничения новой 4×4 mesh-геометрии."""

import json
from pathlib import Path

import numpy as np

from src.components.text_mesh import build_inverse_maps, invert_mesh_point, warp_mesh_forward


VECTORS = json.loads((Path(__file__).parents[1] / "fixtures" / "text_mesh_vectors.json").read_text(encoding="utf-8"))


def _destination(mesh, source, width, height):
    gx = source[0] / (width - 1) * 3
    gy = source[1] / (height - 1) * 3
    col = min(2, int(gx))
    row = min(2, int(gy))
    u, v = gx - col, gy - row
    points = np.asarray(mesh, dtype=np.float64).reshape(4, 4, 2)
    p00, p10 = points[row, col], points[row, col + 1]
    p01, p11 = points[row + 1, col], points[row + 1, col + 1]
    return p00 + u * (p10 - p00) + v * (p01 - p00) + u * v * (p11 - p10 - p01 + p00)


def test_shared_identity_affine_and_curved_vectors_invert_at_source_points():
    for case in VECTORS["cases"]:
        source = case["source"]
        target = _destination(case["mesh"], source, VECTORS["width"], VECTORS["height"])
        restored = invert_mesh_point(target, case["mesh"], VECTORS["width"], VECTORS["height"])
        assert restored is not None, case["name"]
        assert np.allclose(restored, source, atol=1e-3), case["name"]


def test_inverse_maps_identity_and_rejects_folded_mesh():
    identity = VECTORS["cases"][0]["mesh"]
    maps = build_inverse_maps(identity, VECTORS["width"], VECTORS["height"])
    assert maps is not None
    map_x, map_y = maps
    assert abs(float(map_x[40, 45]) - 45) < 1e-3
    assert abs(float(map_y[40, 45]) - 40) < 1e-3

    folded = [point[:] for point in identity]
    folded[5], folded[6] = folded[6], folded[5]
    assert build_inverse_maps(folded, VECTORS["width"], VECTORS["height"]) is None


def test_forward_identity_keeps_image_pixels():
    image = np.zeros((80, 100, 4), dtype=np.uint8)
    image[20:40, 30:55] = (255, 20, 10, 255)
    identity = VECTORS["cases"][0]["mesh"]
    result = warp_mesh_forward(image, identity)
    assert result.shape == image.shape
    assert np.max(np.abs(result.astype(np.int16) - image.astype(np.int16))) <= 2


def test_forward_mapping_moves_an_exact_control_node_to_its_target():
    case = VECTORS["cases"][2]
    image = np.zeros((VECTORS["height"], VECTORS["width"], 4), dtype=np.uint8)
    image[24:29, 31:36] = (255, 0, 0, 255)
    warped = warp_mesh_forward(image, case["mesh"])
    ys, xs = np.where(warped[:, :, 3] > 128)
    assert len(xs) > 0
    assert abs(float(xs.mean()) - 36.0) < 1.0
    assert abs(float(ys.mean()) - 28.0) < 1.0
