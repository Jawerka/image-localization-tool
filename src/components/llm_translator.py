"""Перевод страницы: сценарий в порядке чтения, говорящий и род."""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from src.components.sfx_dict import as_glossary, lookup
from src.models import TextRegion, should_translate
from src.utils.llm_client import LlmClient
from src.utils.logger import logger

TRANSLATION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "id": {"type": "integer"},
                    "speaker": {"type": "string"},
                    "speaker_gender": {"type": "string", "enum": ["male", "female", "unknown"]},
                    "translation": {"type": "string"},
                },
                "required": ["id", "speaker", "speaker_gender", "translation"],
            },
        }
    },
    "required": ["items"],
}

SHORTEN_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {"translation": {"type": "string"}},
    "required": ["translation"],
}


def load_glossary(path: str | None) -> dict[str, str]:
    """JSON-объект или строки «имя = перевод»."""
    if not path:
        return {}
    file_path = Path(path)
    if not file_path.exists():
        logger.warning(f"Glossary not found: {file_path}")
        return {}
    text = file_path.read_text(encoding="utf-8")
    if file_path.suffix.lower() == ".json":
        data = json.loads(text)
        return {str(key): str(value) for key, value in data.items()}
    glossary = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" in stripped:
            key, value = stripped.split("=", 1)
        elif ":" in stripped:
            key, value = stripped.split(":", 1)
        else:
            continue
        glossary[key.strip()] = value.strip()
    return glossary


def _script(regions: list[TextRegion]) -> str:
    lines = []
    for region in sorted(regions, key=lambda item: item.order):
        lines.append(f"{region.id}. [{region.block_type}] {region.text}")
    return "\n".join(lines)


def _ids_with_translation(items) -> set[int]:
    """Id, для которых ответ принёс непустой перевод."""
    found: set[int] = set()
    for item in items or []:
        if not isinstance(item, dict):
            continue
        try:
            region_id = int(item.get("id"))
        except (TypeError, ValueError):
            continue
        if str(item.get("translation") or "").strip():
            found.add(region_id)
    return found


def _glossary_block(glossary: dict[str, str]) -> str:
    if not glossary:
        return "No glossary."
    rows = "\n".join(f"- {name} = {translation}" for name, translation in glossary.items())
    return f"Glossary, use these translations exactly:\n{rows}"


def _sfx_rule(regions: list[TextRegion]) -> str:
    """Строка промпта для блоков [sfx]. Пустая, если звукоподражаний нет."""
    if not any(region.block_type == "sfx" for region in regions):
        return ""
    return (
        "- Blocks marked [sfx] are sound effects: return a short Russian "
        "onomatopoeia, no explanations, no quotes.\n"
    )


def _with_sfx_glossary(
    glossary: dict[str, str] | None,
    regions: list[TextRegion],
) -> dict[str, str]:
    """Словарь звукоподражаний плюс глоссарий вызывающего. Ключ вызывающего побеждает."""
    merged: dict[str, str] = {}
    if any(region.block_type == "sfx" for region in regions):
        merged.update(as_glossary())
    if glossary:
        merged.update(glossary)
    return merged


_DIALOGUE_RULES = (
    "Rules:\n"
    "- For dialogue, set speaker_gender to male or female from the person drawn "
    "next to the balloon. Do not leave dialogue as unknown.\n"
    "- Agree grammatical gender with speaker_gender. A boy does not use feminine forms.\n"
    "- Translate each numbered block into that same block. Do not move a sentence "
    "into a neighbor or skip a block.\n"
    "- If one sentence is split across consecutive blocks, continue it, "
    "but keep each part in its own block.\n"
    "- Keep the translation about as short as the original so it fits the bubble. "
    "Do not add explanations.\n"
    "- Follow the glossary exactly.\n"
    "- Transliterate Japanese names with the Polivanov system.\n"
)


def build_translation_prompt(
    source_lang: str,
    target_lang: str,
    regions: list[TextRegion],
    glossary: dict[str, str] | None = None,
    *,
    only_ids: list[int] | None = None,
    rule_regions: list[TextRegion] | None = None,
) -> str:
    """Промпт перевода страницы. ``rule_regions`` решает, писать ли правило SFX.

    Сценарий берётся из ``regions``. Глоссарий звукоподражаний подмешивается,
    если среди ``rule_regions`` (или ``regions``) есть блок sfx.
    """
    judged = regions if rule_regions is None else rule_regions
    if only_ids is None:
        intro = (
            f"Translate a comic or illustrated page from {source_lang} to {target_lang}. "
            "The image is the original page. The script is in reading order.\n"
            "For each block return speaker (who is talking, or an empty string for narration "
            "and titles), speaker_gender (male, female, or unknown), and translation.\n"
        )
    else:
        ids = ", ".join(str(region_id) for region_id in only_ids)
        intro = (
            f"Translate a comic or illustrated page from {source_lang} to {target_lang}. "
            "The image is the original page. The script is in reading order.\n"
            f"Return items only for these ids: {ids}. Do not return items for any other id.\n"
            "For each requested block return speaker (who is talking, or an empty string for narration "
            "and titles), speaker_gender (male, female, or unknown), and translation.\n"
        )
    merged = _with_sfx_glossary(glossary, judged)
    return (
        intro
        + _DIALOGUE_RULES
        + _sfx_rule(judged)
        + "\n"
        + f"{_glossary_block(merged)}\n\n"
        + f"Script:\n{_script(regions)}"
    )


def _claim_sfx_dict(regions: list[TextRegion]) -> list[TextRegion]:
    """Подставить словарь для знакомых SFX. Вернуть блоки, которые ещё переводить."""
    pending: list[TextRegion] = []
    for region in regions:
        if region.block_type != "sfx":
            pending.append(region)
            continue
        hit = lookup(region.text)
        if not hit:
            pending.append(region)
            continue
        region.translation = hit
        region.speaker_gender = region.speaker_gender or "unknown"
    return pending


class LlmTranslator:
    """Второй запрос: чистая страница и сценарий."""

    def __init__(self, client: LlmClient):
        self.client = client

    def translate(
        self,
        image: Image.Image,
        regions: list[TextRegion],
        source_lang: str,
        target_lang: str,
        glossary: dict[str, str] | None = None,
        translate_sfx: bool = False,
    ) -> list[TextRegion]:
        selected = [region for region in regions if should_translate(region, translate_sfx)]
        if not selected:
            return regions
        prompt = build_translation_prompt(
            source_lang, target_lang, selected, glossary,
        )
        payload = self.client.chat_json(
            prompt=prompt,
            schema=TRANSLATION_SCHEMA,
            schema_name="page_translation",
            images=[image.convert("RGB")],
        )
        self._apply_items(selected, payload.get("items") or [])
        missing = [region for region in selected if not region.translation.strip()]
        if missing:
            logger.warning(f"LLM skipped {len(missing)} blocks, retrying")
            retry = self.client.chat_json(
                prompt=(
                    f"Translate these remaining blocks from {source_lang} to {target_lang}. "
                    "Return one item per block. Do not skip any id.\n"
                    f"{_sfx_rule(missing)}"
                    f"\nScript:\n{_script(missing)}"
                ),
                schema=TRANSLATION_SCHEMA,
                schema_name="page_translation",
                images=[image.convert("RGB")],
            )
            self._apply_items(missing, retry.get("items") or [])
        logger.info(f"LLM translated {sum(1 for r in selected if r.translation)} blocks")
        return regions

    def translate_subset(
        self,
        image: Image.Image,
        regions: list[TextRegion],
        region_ids: set[int],
        source_lang: str,
        target_lang: str,
        glossary: dict[str, str] | None = None,
        translate_sfx: bool = False,
    ) -> list[TextRegion]:
        """Перевести указанные регионы, держа в промпте сценарий всей страницы."""
        page = [region for region in regions if should_translate(region, translate_sfx)]
        selected = [region for region in page if region.id in region_ids]
        if not selected:
            return regions
        prompt = build_translation_prompt(
            source_lang,
            target_lang,
            page,
            glossary,
            only_ids=[region.id for region in selected],
            rule_regions=selected,
        )
        payload = self.client.chat_json(
            prompt=prompt,
            schema=TRANSLATION_SCHEMA,
            schema_name="page_translation",
            images=[image.convert("RGB")],
        )
        items = payload.get("items") or []
        self._apply_items(selected, items)
        missing = [region for region in selected if region.id not in _ids_with_translation(items)]
        if missing:
            logger.warning(f"LLM skipped {len(missing)} blocks, retrying")
            retry = self.client.chat_json(
                prompt=(
                    f"Translate these remaining blocks from {source_lang} to {target_lang}. "
                    "Return one item per block. Do not skip any id.\n"
                    f"{_sfx_rule(missing)}"
                    f"\nScript:\n{_script(missing)}"
                ),
                schema=TRANSLATION_SCHEMA,
                schema_name="page_translation",
                images=[image.convert("RGB")],
            )
            self._apply_items(missing, retry.get("items") or [])
        logger.info(f"LLM translated {sum(1 for r in selected if r.translation)} blocks")
        return regions

    def _apply_items(self, regions: list[TextRegion], items: list) -> None:
        by_id = {region.id: region for region in regions}
        for item in items:
            try:
                region_id = int(item.get("id"))
            except (TypeError, ValueError):
                continue
            region = by_id.get(region_id)
            if region is None:
                continue
            region.speaker = str(item.get("speaker") or "").strip()
            gender = str(item.get("speaker_gender") or "unknown").strip().lower()
            region.speaker_gender = gender if gender in ("male", "female", "unknown") else "unknown"
            region.translation = str(item.get("translation") or "").strip()

    def shorten(
        self,
        text: str,
        target_lang: str,
        max_chars: int,
        speaker_gender: str = "unknown",
        original: str = "",
    ) -> str:
        """Короче переформулировать фразу, которая не влезла в баллон."""
        if not text.strip():
            return text
        payload = self.client.chat_json(
            prompt=(
                f"Shorten this {target_lang} translation so it fits in about {max_chars} characters. "
                f"Keep the meaning, the tone, and grammatical gender ({speaker_gender or 'unknown'}). "
                "Do not add notes.\n"
                f"Original: {original}\n"
                f"Current translation: {text}"
            ),
            schema=SHORTEN_SCHEMA,
            schema_name="short_translation",
            images=[],
            max_tokens=512,
        )
        shortened = str(payload.get("translation") or "").strip()
        return shortened or text


class ArgosBlockTranslator:
    """Фолбэк: Argos переводит целый блок, не отдельные слова."""

    def __init__(self):
        from src.components.translator import TranslatorService
        self.service = TranslatorService()

    def translate(
        self,
        image: Image.Image,
        regions: list[TextRegion],
        source_lang: str,
        target_lang: str,
        glossary: dict[str, str] | None = None,
        translate_sfx: bool = False,
    ) -> list[TextRegion]:
        del image, glossary
        selected = [region for region in regions if should_translate(region, translate_sfx)]
        pending = _claim_sfx_dict(selected)
        if selected and not pending:
            return regions
        translated = self.service.translate_texts_ordered(
            [region.text for region in pending],
            source_lang,
            target_lang,
        )
        for region, text in zip(pending, translated):
            region.translation = text
            region.speaker_gender = region.speaker_gender or "unknown"
        return regions

    def translate_subset(
        self,
        image: Image.Image,
        regions: list[TextRegion],
        region_ids: set[int],
        source_lang: str,
        target_lang: str,
        glossary: dict[str, str] | None = None,
        translate_sfx: bool = False,
    ) -> list[TextRegion]:
        """Перевести только выбранные регионы, без картинки."""
        del image, glossary
        selected = [
            region for region in regions
            if region.id in region_ids and should_translate(region, translate_sfx)
        ]
        if not selected:
            return regions
        pending = _claim_sfx_dict(selected)
        if not pending:
            return regions
        translated = self.service.translate_texts_ordered(
            [region.text for region in pending],
            source_lang,
            target_lang,
        )
        for region, text in zip(pending, translated):
            region.translation = text
            region.speaker_gender = region.speaker_gender or "unknown"
        return regions

    def shorten(self, text: str, target_lang: str = "", max_chars: int = 0, **kwargs) -> str:
        del target_lang, kwargs
        if max_chars and len(text) > max_chars:
            return text[: max(1, max_chars - 1)].rstrip() + "…"
        return text
