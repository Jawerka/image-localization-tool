"""Переносимая поставка готового Docker-образа, Compose и инструкции без исходников/данных."""

import argparse
import sys
import zipfile
from pathlib import Path

import yaml

from scripts.pack_notices import NOTICE_FILES, ROOT as REPO_ROOT

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    from src.app import __version__

    parser = argparse.ArgumentParser()
    parser.add_argument("--image-archive", required=True)
    parser.add_argument("--out", default="dist")
    args = parser.parse_args()
    image = Path(args.image_archive).resolve()
    if not image.is_file():
        raise FileNotFoundError(image)
    output = Path(args.out)
    output.mkdir(parents=True, exist_ok=True)
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
    compose["services"]["ilt"].pop("build", None)
    name = f"ImageLocalizationTool-{__version__}-docker-cpu-full.zip"
    readme = f"""Image Localization Tool — готовый CPU-контейнер

Профиль: Linux amd64, OCR + LaMa + перевод en↔ru. Все модели внутри образа.
Нужен Docker с Compose. На Windows требуется среда Linux-контейнеров.

В этой папке выполните:
  docker load -i {image.name}
  docker compose up -d --no-build

Откройте http://localhost:8080. По умолчанию вход не требуется.
Включить защиту: Настройки → Доступ → задайте логин и пароль владельца,
отметьте «Требовать вход» и нажмите «Сохранить доступ».
Пароль должен содержать не менее 10 символов. Учётная запись хранится
в data/web-access.json внутри постоянного volume; пароль сохраняется как хеш.
Для изменения и отключения настроенной защиты нужен текущий пароль.
Старые ILT_WEB_TOKEN и web.token больше не включают вход автоматически.
Порт по умолчанию доступен только с этого компьютера.
Для LAN задайте ILT_PUBLISH_HOST=0.0.0.0 и ILT_WEB_ORIGINS с точным адресом и портом.
Один оператор и общий проект на экземпляр; для внешней сети используйте HTTPS proxy.

Проекты, настройки и ключи находятся в постоянном Docker volume.
docker compose down сохраняет данные. Команда down -v удаляет volume.
Пользовательские данные и тестовый ключ входа в эту поставку не включены.
"""
    with zipfile.ZipFile(output / name, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
        archive.write(image, image.name)
        archive.writestr("compose.yaml", yaml.safe_dump(compose, allow_unicode=True, sort_keys=False))
        archive.writestr("README.txt", readme)
        for source_name, target_name in NOTICE_FILES:
            archive.write(REPO_ROOT / source_name, target_name)
    print(output / name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
