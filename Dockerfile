# syntax=docker/dockerfile:1
FROM python:3.10-slim-bookworm@sha256:5be5aaecb962a41567bc8041f1e9e3432cb085b037fe057f9a562630b2e4b370 AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ILT_INSTALL_ROOT=/opt/ilt \
    ILT_COMPONENT_ROOT=/opt/ilt \
    ILT_DATA_DIR=/opt/ilt/data
WORKDIR /opt/ilt

RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 libgomp1 p7zip-full unrar-free \
    && rm -rf /var/lib/apt/lists/*
COPY requirements-base.txt requirements-container.txt requirements-container.lock ./
RUN --mount=type=cache,target=/root/.cache/pip pip install -r requirements-container.txt -c requirements-container.lock

FROM base AS prepared
COPY src/ ./src/
COPY web/ ./web/
COPY LICENSE ./LICENSE
COPY docs/LICENSE_INVENTORY.md ./LICENSE_INVENTORY.md
COPY docs/THIRD_PARTY_NOTICES.md ./THIRD_PARTY_NOTICES.md
COPY docs/FONTS.md ./FONTS.md
COPY assets/README.md ./ARGOS_WHEEL.md
COPY assets/argostranslate-1.11.1-py3-none-any.whl ./assets/argostranslate-1.11.1-py3-none-any.whl
# Проверка выполняется при сборке, до очистки диагностических данных и кэша.
RUN --mount=type=cache,target=/opt/ilt/.downloads python -m src.app.distribution prepare \
    && python -m src.app.distribution functional \
    && rm -rf /opt/ilt/data

FROM base AS app
ARG SOURCE_REVISION=unknown
ARG APP_VERSION=unknown
LABEL org.opencontainers.image.source="https://github.com/Jawerka/image-localization-tool" \
    org.opencontainers.image.revision=$SOURCE_REVISION \
    org.opencontainers.image.version=$APP_VERSION \
    org.opencontainers.image.description="Image Localization Tool: browser editor and prepared offline CPU models"
RUN groupadd --gid 10001 ilt && useradd --uid 10001 --gid ilt --no-create-home ilt \
    && mkdir -p /opt/ilt/data && chown ilt:ilt /opt/ilt/data
COPY --from=prepared --chown=10001:10001 /opt/ilt/ /opt/ilt/
USER 10001:10001
EXPOSE 8080
VOLUME ["/opt/ilt/data"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os,urllib.request,urllib.parse; origin=os.getenv('ILT_WEB_ORIGINS','http://127.0.0.1:8080').split(',')[0]; req=urllib.request.Request('http://127.0.0.1:8080/healthz',headers={'Host':urllib.parse.urlsplit(origin).netloc}); urllib.request.urlopen(req,timeout=3)"
ENTRYPOINT ["python", "-m", "src.app", "--server"]
