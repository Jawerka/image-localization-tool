"""Компонент перевода на основе Argos Translate (оффлайн)."""

from functools import lru_cache
import os
from src.utils.logger import logger


class TranslatorService:
    """Сервис перевода текста на основе Argos Translate."""
    
    def __init__(self):
        """Инициализировать сервис перевода."""
        self._translator = None
        self._initialized = False
        self._error: str | None = None
        self._pair = None

    @property
    def last_error(self) -> str:
        """Текст последней ошибки инициализации или пустая строка."""
        return self._error or ""
    
    def _init_translator(self, source_lang: str, target_lang: str) -> bool:
        """Ленивая инициализация переводчика.
        
        Args:
            source_lang: Исходный язык (код ISO 639-1).
            target_lang: Целевой язык (код ISO 639-1).
        
        Returns:
            True если инициализация успешна.
        """
        if self._initialized and self._pair == (source_lang, target_lang):
            return self._error is None
        
        self._initialized = True
        self._pair = (source_lang, target_lang)
        self._error = None
        
        try:
            os.environ["ARGOS_CHUNK_TYPE"] = "MINISBD"
            import argostranslate.package
            import argostranslate.settings
            from src.app.component_catalog import language_dirs

            directories = language_dirs()
            argostranslate.settings.package_dirs = directories
            argostranslate.settings.chunk_type = argostranslate.settings.ChunkType.MINISBD
            import argostranslate.translate
            
            logger.info("Initializing Argos Translate (оффлайн)")
            
            # Проверяем наличие модели
            installed_packages = argostranslate.package.get_installed_packages()
            model_found = False
            
            for pkg in installed_packages:
                if pkg.from_code == source_lang and pkg.to_code == target_lang:
                    model_found = True
                    logger.debug(f"Model {source_lang}->{target_lang} found")
                    break
            
            if not model_found:
                logger.warning(f"Model {source_lang}->{target_lang} not installed")
                self._error = f"Нужно подготовить оффлайн-перевод {source_lang} → {target_lang} в настройках приложения"
                logger.error(self._error)
                return False
            
            self._translator = argostranslate.translate
            return True
            
        except ImportError as e:
            self._error = (
                "Нужен компонент «Argos» (Настройки → Компоненты) "
                f"или сервер LLM: argostranslate не установлен ({e})"
            )
            logger.error(self._error)
            return False
        except Exception as e:
            self._error = f"Translation initialization error: {e}"
            logger.error(self._error)
            return False
    
    def translate_texts(
        self,
        texts: list[str],
        source_lang: str,
        target_lang: str
    ) -> dict[str, str]:
        """Перевести список текстов.
        
        Args:
            texts: Список текстов для перевода.
            source_lang: Исходный язык (например, 'en').
            target_lang: Целевой язык (например, 'ru').
        
        Returns:
            Словарь {оригинал: перевод}.
        """
        if not texts:
            return {}
        
        if not self._init_translator(source_lang, target_lang):
            logger.warning("Translation unavailable, returning originals")
            return {text: text for text in texts}
        
        result = {}
        
        for text in texts:
            translated = self._translate_single(text, source_lang, target_lang)
            result[text] = translated if translated else text
        
        logger.info(f"Translated {len(result)} texts")
        return result

    def translate_texts_ordered(
        self,
        texts: list[str],
        source_lang: str,
        target_lang: str,
    ) -> list[str]:
        """Перевести список текстов, сохраняя порядок (для дубликатов)."""
        if not texts:
            return []

        if not self._init_translator(source_lang, target_lang):
            logger.warning("Translation unavailable, returning originals")
            return list(texts)

        return [
            self._translate_single(text, source_lang, target_lang) or text
            for text in texts
        ]
    
    @lru_cache(maxsize=1000)
    def _translate_single(
        self,
        text: str,
        source_lang: str,
        target_lang: str
    ) -> str:
        """Перевести один текст (с кэшированием).
        
        Args:
            text: Текст для перевода.
            source_lang: Исходный язык.
            target_lang: Целевой язык.
        
        Returns:
            Переведённый текст или пустая строка при ошибке.
        """
        if len(text.strip()) < 2:
            return text
        
        try:
            translated = self._translator.translate(
                text,
                from_code=source_lang,
                to_code=target_lang
            )
            
            logger.debug(f"Translated: '{text}' -> '{translated}'")
            return translated
            
        except Exception as e:
            logger.error(f"Translation error for '{text}': {e}")
            return text
    
    @staticmethod
    def get_available_languages() -> list[str]:
        """Получить список доступных языков перевода.
        
        Returns:
            Список кодов языков.
        """
        try:
            import argostranslate.package
            from src.app.component_catalog import language_dirs
            
            packages = argostranslate.package.get_installed_packages(language_dirs())
            langs = set()
            
            for pkg in packages:
                langs.add(pkg.from_code)
                langs.add(pkg.to_code)
            
            return sorted(list(langs))
            
        except Exception as e:
            logger.error(f"Could not get translation languages: {e}")
            return []
    
    @staticmethod
    def check_installation() -> bool:
        """Проверить наличие Argos Translate.
        
        Returns:
            True если библиотека доступна.
        """
        try:
            import argostranslate.translate  # noqa: F401
            return True
        except ImportError as e:
            logger.error(f"Argos Translate not installed: {e}")
            return False
