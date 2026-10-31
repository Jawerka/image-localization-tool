"""Мост удалённого задания к переводу одной страницы.

Сети и моделей здесь нет: вызывающий передаёт ``translate_page``.
"""

from __future__ import annotations


def run_remote_job(job, translate_page) -> None:
    """Перевести страницу задания и закрыть его.

    ``translate_page(project_id, page_id)`` возвращает байты PNG или бросает
    исключение. Успех — ``job.finish(png)``. Любой сбой перевода —
    ``job.fail`` со строкой сообщения. Статус ``done`` пропускается:
    колбэк, ``finish`` и ``fail`` не вызываются.
    """
    if getattr(job, "status", None) == "done":
        return
    try:
        png = translate_page(job.project_id, job.page_id)
    except Exception as exc:
        # Ошибка самого fail не глотаем: это сбой объекта задания.
        job.fail(str(exc))
        return
    job.finish(png)
