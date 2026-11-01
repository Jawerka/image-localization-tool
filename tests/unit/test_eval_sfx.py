"""Повторная очистка пересчитывает автоматический стиль, сохраняя ручной."""
import pytest

from scripts.eval_sfx import restore_regions
from src.models import TextRegion


def test_restore_recalculates_automatic_style_and_preserves_ocr():
    region = TextRegion(id=1, bbox=(10, 20, 80, 40), block_type='sfx',
                        text='Squeeze', translation='Сжать', skip=True)
    region.style.rotation = 25
    region.auto_layout = {'kind': 'sfx'}
    restored = restore_regions({'regions': [region.to_dict()]})[0]
    assert restored.style.rotation == 0
    assert restored.auto_layout is None
    assert (restored.text, restored.translation, restored.block_type, restored.skip) == ('Squeeze', 'Сжать', 'sfx', True)


@pytest.mark.parametrize('field', ['manual', 'edited', 'layout_snapshot'])
def test_restore_keeps_user_geometry(field):
    region = TextRegion(id=1, bbox=(1, 2, 30, 40))
    setattr(region, field, {'version': 1} if field == 'layout_snapshot' else True)
    region.style.rotation = 25
    restored = restore_regions({'regions': [region.to_dict()]})[0]
    assert restored.style.rotation == 25
