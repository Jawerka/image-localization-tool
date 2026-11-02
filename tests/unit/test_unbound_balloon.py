"""Геометрия непривязанных наклонных реплик без захвата рисунка."""

import cv2
import numpy as np
from PIL import Image

from src.components.adaptive_text import _supported_speech_rows, inferred_balloon_area, joined_speech_ink
from src.models import TextRegion


def test_tilted_rows_keep_letters_and_punctuation_but_drop_distant_art():
    ink = np.zeros((420, 420), np.uint8)
    cv2.putText(ink, 'HELLO-WORD', (30, 120), cv2.FONT_HERSHEY_SIMPLEX, .8, 255, 2)
    cv2.putText(ink, 'OTHER ROW.', (30, 165), cv2.FONT_HERSHEY_SIMPLEX, .8, 255, 2)
    letters = cv2.warpAffine(ink, cv2.getRotationMatrix2D((210, 210), 25, 1), (420, 420))
    artifact = np.zeros_like(ink)
    cv2.ellipse(artifact, (340, 330), (12, 8), 0, 180, 350, 255, 2)
    cv2.line(artifact, (280, 340), (285, 355), 255, 2)
    filtered = _supported_speech_rows(np.maximum(letters, artifact))
    assert np.all(filtered[letters > 0] > 0)
    assert np.count_nonzero(filtered[artifact > 0]) == 0


def test_short_ambiguous_components_are_not_removed():
    ink = np.zeros((90, 120), np.uint8)
    cv2.putText(ink, 'HI.', (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 1, 255, 2)
    assert np.array_equal(_supported_speech_rows(ink), ink)


def test_open_irregular_balloon_hull_excludes_white_notch_outside_border():
    rgb = np.full((220, 270, 3), 255, np.uint8)
    outline = np.array([(30, 30), (110, 30), (110, 80), (150, 80),
                        (150, 30), (240, 30), (240, 190), (150, 190)])
    cv2.polylines(rgb, [outline], False, (0, 0, 0), 2)
    cv2.line(rgb, (120, 190), (30, 190), (0, 0, 0), 2)
    cv2.line(rgb, (30, 190), (30, 30), (0, 0, 0), 2)
    ink = np.zeros(rgb.shape[:2], np.uint8)
    for text, pos in [('HI', (45, 65)), ('OH', (170, 65)), ('WORDS', (60, 150))]:
        cv2.putText(rgb, text, pos, cv2.FONT_HERSHEY_SIMPLEX, .7, (0, 0, 0), 2)
        cv2.putText(ink, text, pos, cv2.FONT_HERSHEY_SIMPLEX, .7, 255, 2)
    region = TextRegion(1, (0, 0, 270, 220), text='HI OH WORDS', class_name='text_bubble')
    area = inferred_balloon_area(Image.fromarray(rgb), region, ink, (0, 0, 270, 220))
    assert area[55, 130] == 0
    assert np.mean(area[ink > 0] > 0) >= .9


def test_joined_thick_letters_are_rescued_without_following_thin_border():
    rgb = np.full((180, 280, 3), 255, np.uint8)
    cv2.rectangle(rgb, (15, 15), (265, 165), (0, 0, 0), 1)
    cv2.putText(rgb, 'STR', (80, 65), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 0), 5)
    cv2.line(rgb, (90, 42), (90, 15), (0, 0, 0), 1)
    region = TextRegion(1, (60, 25, 150, 110), auto_layout={'version': 1, 'kind': 'bubble', 'outline_px': 3})
    mask = joined_speech_ink(Image.fromarray(rgb), region, (0, 0))
    letters = np.zeros((180, 280), np.uint8)
    cv2.putText(letters, 'STR', (80, 65), cv2.FONT_HERSHEY_SIMPLEX, 1, 255, 5)
    assert np.mean(mask[letters > 0] > 0) > .95
    assert not np.any(mask[14:17, 150:240])
    assert not np.any(mask[164:167])
