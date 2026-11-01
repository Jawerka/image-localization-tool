# Совместимость

PagePipeline.clean по-прежнему возвращает (mask, cleaned) исходного размера. Ручные штрихи применяются последними. Пустая маска не запускает очистку. skip/translation и SFX skip проверяет существующий _drawable. LamaInpainter.inpaint сохраняет allow_flat_fill и фолбэки CUDA→CPU→OpenCV. Новых endpoint, полей проекта и настроек нет.
