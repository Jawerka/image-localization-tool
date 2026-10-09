# Surface Contracts: Baseline Product

## CLI

- Entry: translate one image or a folder of images to destination images.
- Inputs: page image formats PNG, JPG/JPEG, BMP, TIFF; source/target language; optional LLM URL and backend overrides.
- Outputs: result image; optional debug artefacts when requested.
- Fallback: offline recognition and translation with warning when preferred LLM path is unavailable.

## Desktop window / local HTTP

- Local bind: `127.0.0.1` only for UI API and static UI.
- Session: page token exchanged for HttpOnly cookie; protected `/api/*` require cookie except session exchange.
- Capabilities: bootstrap, project/page document edits, translate jobs, export, settings, secret key write, model presence/download, glossary/styles, remote status/pairing controls.
- Single instance: second launch forwards paths to the live instance.

## Remote LAN `/v1`

- Opt-in listener separate from local UI port.
- Public: `GET /v1/health`, `POST /v1/pair`.
- Authenticated: translate, job status, result, delete; bearer token required.
- Limits: body size, pixel count, unfinished jobs, per-device request rate.
- Pairing: six-digit code, single use, short lifetime; raw token not retained in device list.

## Browser extension

- Pair with server URL and code; store token and target language locally.
- Translate qualifying large images; delay hover control two seconds; compact icon without on-image text.
- Poll job until terminal state; substitute image bytes; optional page-batch chime.
- Do not inject content script on excluded Ozon storefront hosts.
