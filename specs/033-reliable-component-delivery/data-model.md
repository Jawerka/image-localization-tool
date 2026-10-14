# Data Model

## Artifact
name, urls[], sha256 (64 hex), size_bytes>0, unpacked_bytes>=0. Кэш <sha>.blob / <sha>.part и metadata ETag. Содержимое определяет идентичность.

## Component
id/title/kind/revision/os/arch/python/files/dependencies/check. Runtime retains schema 2 с необязательными revision/unpacked_bytes/check; ресурсный каталог содержит raw/model/argos-language записи. Revision — SHA состава/ABI.

## Installation
pack.json содержит полный revision, inventory, ABI и результат проверки. .revisions/id/revision[:24]/site-packages сокращает Windows-пути DLL; .active/id.json хранит полный SHA. Legacy root/id и прежняя выбранная папка читаются без копирования. .tmp не активируется. Ресурсы живут в .resources/id/revision[:24], Argos использует package_dirs и ARGOS_PACKAGES_DIR, chunk_type=MINISBD.

## Preparation
schema/state/selection/catalog_sha/items/index/done/total/current/error/error_kind/updated_at. States idle/planning/downloading/checking/installing/paused/error/ready. После прерывания unstable → paused. Resume сохраняет identities и проверяет catalog compatibility.

## ReleaseReport
version/commit/catalog_sha256/assets[{name,sha256,size}]/checks/draft_tag. Publish проверяет неизменность и не rebuild.
