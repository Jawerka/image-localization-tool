# Контракт

Content-script image-source.js публикует iltImageSource.read(choice, log), Promise<{imageBase64?,imageMime?}>. choice содержит url, node, необязательные уже готовые imageBase64/imageMime. Обычные ошибки возвращают {}, позволяя background получить URL. Успех входит в существующий translate-url; background не скачивает suppliedBlob заново. Ни манифест, ни HTTP API не получают новых разрешений или обязательных полей.
Смена src отменяет использование полученных байтов. Запрещено использовать canvas переведённого blob вместо выбранного оригинала. force-cache может сходить в сеть при отсутствии подходящего кэша: журнал page-fetch не объявляет гарантированное попадание в кэш.
