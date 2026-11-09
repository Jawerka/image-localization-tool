"""Свободное пространство не подтверждается одной лишь однородностью цвета."""
import cv2
import numpy as np
from PIL import Image

from src.components.placement_space import placement_space, FREE, UNKNOWN, BLOCKED


def sample():
    image = np.full((180, 240, 3), (210, 220, 240), np.uint8)
    field = np.zeros((180, 240), np.uint8)
    field[65:100, 60:180] = 255
    return image, field


def test_uniform_area_without_trust_remains_unknown():
    image, field = sample()
    state, _ = placement_space(image, field)
    assert np.all(state[field > 0] == FREE)
    assert state[130, 120] == UNKNOWN


def test_trusted_connected_background_can_expand():
    image, field = sample()
    trust = np.zeros(field.shape, np.uint8)
    trust[20:155, 35:205] = 255
    state, meta = placement_space(image, field, trusted_field=trust)
    assert state[130, 120] == FREE
    assert state[165, 120] == UNKNOWN
    assert meta['trusted']


def test_protected_other_text_overrides_uniform_background_and_source():
    image, field = sample()
    protected = np.zeros(field.shape, np.uint8)
    protected[95:115, 100:140] = 255
    state, _ = placement_space(image, field, trusted_field=np.ones(field.shape), protected=protected)
    assert state[100, 120] == BLOCKED
    assert state[94, 120] == BLOCKED


def test_different_colour_is_not_assumed_free():
    image, field = sample()
    image[115:155, 75:165] = (190, 150, 130)
    state, _ = placement_space(image, field, trusted_field=np.ones(field.shape))
    assert state[130, 120] != FREE


def test_own_ink_does_not_break_background_estimation():
    image, field = sample()
    ink = np.zeros(field.shape, np.uint8)
    cv2.putText(ink, 'TEST', (70, 90), cv2.FONT_HERSHEY_SIMPLEX, .65, 255, 2)
    image[ink > 0] = 0
    state, _ = placement_space(Image.fromarray(image), field, source_ink=ink, trusted_field=np.ones(field.shape))
    assert state[130, 120] == FREE


def test_original_field_does_not_override_trusted_boundary():
    image, field = sample()
    trust = np.zeros(field.shape, np.uint8)
    trust[:, :120] = 255
    state, _ = placement_space(image, field, trusted_field=trust)
    assert state[80, 100] == FREE
    assert state[80, 160] == UNKNOWN
