# Plan: Ограниченный кэш рендера

## Approach

1. Создать потокобезопасный byte-bounded LRU для изображений и PNG-ответов.
2. Добавить `render_cache_limit_mb` с консервативным дефолтом в `Config`.
3. Декодировать original/clean image через cache, fingerprint включать resolved path, размер и `mtime_ns`.
4. Кэшировать exact/base-layer preview bytes по хэшу полного входа рендера и версии страницы; revision header оставлять динамическим.
5. Проверить hit/miss, инвалидизацию каждого класса входа, предельный объём и пиксельную идентичность.

## Decisions

- Кэш in-memory и процессный, не переживает перезапуск приложения.
- SHA-256 canonical JSON используется как непрозрачный ключ; секреты и абсолютный путь не записываются в отчёты.
- LRU accounting использует точную длину PNG bytes и `width * height * channels` для RGB/RGBA image.
- Нулевой лимит отключает кэш. Ошибки декодирования/рендера не кэшируются.
