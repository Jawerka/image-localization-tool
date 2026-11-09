# Данные

Нового постоянного состояния нет. image-source helper возвращает imageBase64 и imageMime либо пустой объект. Существующий suppliedBlob задания позволяет использовать эти байты без повторного скачивания. Временный Blob: непустой, читаемый, <=32 МиБ. Читаемые пиксели IMG кодируются в PNG полного naturalWidth×naturalHeight. Источник фиксируется через currentSrc/src до и после чтения.
Лог: image-source (page-fetch/loaded-image), image-source-error (path/name/status), download-error (origin/status/name/cache). Без полных URL и тел.
