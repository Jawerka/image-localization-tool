"""Длинный перевод не уменьшается и не теряет слова при переносах."""
import numpy as np

from src.components.readable_reflow import readable_reflow
from src.components.typesetter import COMIC_FONT


def test_additional_lines_keep_font_and_all_words():
    text = 'Пожалуйста помогите мне перенести эти тяжёлые коробки'
    layer, fit = readable_reflow(text, COMIC_FONT, 28, np.ones((180, 340), np.uint8), 2)
    assert fit['fits'] and layer is not None
    assert len(fit['lines']) > 1
    assert fit['font_size'] == 28
    assert ' '.join(line['text'] for line in fit['lines']) == text


def test_insufficient_space_never_silently_shrinks():
    layer, fit = readable_reflow('Очень длинная фраза для крошечного поля', COMIC_FONT, 32,
                                 np.ones((35, 90), np.uint8), 2)
    assert layer is None and not fit['fits']
    assert fit['font_size'] == 32 and fit['lines'] == []


def test_outline_respects_forbidden_background():
    allowed = np.ones((220, 380), np.uint8)
    allowed[:, :100] = 0
    allowed[90:130, 300:] = 0
    layer, fit = readable_reflow('Перенос сохраняет размер букв', COMIC_FONT, 28, allowed, 3)
    assert fit['fits']
    assert not np.any((np.asarray(layer.getchannel('A')) > 0) & (allowed == 0))


def test_unbreakable_word_requires_more_space():
    text = 'Электроэнцефалографический'
    layer, fit = readable_reflow(text, COMIC_FONT, 32, np.ones((160, 100), np.uint8))
    assert layer is None and not fit['fits']


def test_explicit_newlines_can_be_rebalanced_without_changing_words():
    text = 'Пожалуйста\nпомогите мне'
    layer, fit = readable_reflow(text, COMIC_FONT, 28, np.ones((130, 260), np.uint8))
    assert layer is not None
    assert ' '.join(line['text'] for line in fit['lines']) == ' '.join(text.split())


def test_vertical_growth_prefers_down_and_keeps_width():
    from src.components.readable_reflow import vertical_reflow
    text = 'Пожалуйста помогите мне перенести эти тяжёлые коробки'
    _, fit = vertical_reflow(text, COMIC_FONT, 28, np.ones((400, 360), np.uint8), [20, 160, 320, 38])
    assert fit['fits'] and fit['direction'] == 'down'
    assert fit['growth_up'] == 0 and fit['growth_down'] > 0
    assert fit['frame'][:3] == [20, 160, 320]
    assert fit['font_size'] == 28
    assert ' '.join(line['text'] for line in fit['lines']) == text


def test_blocked_bottom_grows_up_without_crossing_obstacle():
    from src.components.readable_reflow import vertical_reflow
    allowed = np.ones((360, 360), np.uint8)
    allowed[200:] = 0
    layer, fit = vertical_reflow('Пожалуйста помогите мне перенести тяжёлые коробки', COMIC_FONT,
                                28, allowed, [20, 160, 320, 40])
    assert fit['fits'] and fit['direction'] == 'up'
    assert not np.any((np.asarray(layer.getchannel('A')) > 0) & (allowed == 0))


def test_growth_uses_both_sides_when_neither_is_enough():
    from src.components.readable_reflow import vertical_reflow
    allowed = np.ones((130, 280), np.uint8)
    _, fit = vertical_reflow('Помогите перенести коробки', COMIC_FONT,
                             28, allowed, [0, 45, 280, 40])
    assert fit['fits'] and fit['direction'] == 'both'


def test_vertical_growth_does_not_use_horizontal_free_space():
    from src.components.readable_reflow import vertical_reflow
    layer, fit = vertical_reflow('Электроэнцефалографический', COMIC_FONT, 32,
                                 np.ones((300, 600), np.uint8), [200, 100, 100, 40])
    assert layer is None and not fit['fits']
    assert fit['font_size'] == 32 and fit['frame'][2] == 100


def test_reflow_can_shift_up_inside_a_narrowing_balloon():
    allowed = np.ones((200, 350), np.uint8)
    allowed[100:, :135] = 0
    allowed[100:, 215:] = 0
    text = 'ДА ПОМОГИТЕ ПОЖАЛУЙСТА'
    layer, fit = readable_reflow(text, COMIC_FONT, 28, allowed, 2)
    assert fit['fits'] and fit['font_size'] == 28
    assert fit['lines'][0]['y'] < 40
    assert ' '.join(row['text'] for row in fit['lines']) == text
    assert not np.any((np.asarray(layer.getchannel('A')) > 0) & (allowed == 0))
