"""Адреса не переводятся, а остаток обычного слова из исходника проверяется."""
from src.components.lang_guard import foreign_leak, unchanged_foreign_words


def test_credit_address_is_not_a_language_failure():
    assert not foreign_leak('patreon.com/shepherd0821', 'ru')
    assert not foreign_leak('Источник: https://example.org/hello', 'ru')
    assert foreign_leak('Это совершенно wrong translation', 'ru')


def test_uppercase_source_word_cannot_hide_in_russian_translation():
    assert unchanged_foreign_words('spread like WILDFIRE', 'Разлетелись как WILDFIRE', 'ru')
    assert unchanged_foreign_words('SLAM!', 'SLAM!', 'ru')
    assert not unchanged_foreign_words('spread like WILDFIRE', 'Разлетелись как лесной пожар', 'ru')
    assert not unchanged_foreign_words('ERIKA', 'ERIKA', 'ru', ['ERIKA'])
    assert not unchanged_foreign_words('Luna', 'Luna', 'ru')
