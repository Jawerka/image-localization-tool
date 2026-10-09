# Feature Specification: Baseline Product Contract

**Feature Branch**: `001-baseline-contract`

**Created**: 2026-10-09

**Status**: Draft

**Input**: User description: "Зафиксировать обещанный контракт CLI, окна, расширения и LAN без направлений из roadmap."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Translate a page from the command line (Priority: P1)

A user points the tool at an image page and a destination path. The tool finds speech balloons and text areas, reads the text, translates it into the chosen target language, removes the original lettering from translated regions, and lays the translation into the balloon shapes. The result image is written to the destination.

**Why this priority**: Command-line translation is the core product promise and the shared processing path used by every surface.

**Independent Test**: Feed one PNG or JPEG page with known balloons and a target language; confirm a result image appears and translated regions no longer show the original lettering in those areas.

**Acceptance Scenarios**:

1. **Given** a page image and a destination path with source and target languages set, **When** the user runs the command-line entry, **Then** a result image is written and balloon text that should be translated is replaced by the translation.
2. **Given** the vision language model server is unavailable, **When** the user runs the same command, **Then** the run still finishes using the offline recognition and translation fallbacks and surfaces a warning that the preferred path was unavailable.
3. **Given** sound-effect regions and object labels are present and sound-effect translation is left at the default, **When** the page is translated, **Then** those regions stay untranslated while dialogue balloons are translated.

---

### User Story 2 - Review and translate pages in the desktop window (Priority: P1)

A user opens the desktop window, adds page images or a folder, starts translation for one page or the whole project, watches progress, and exports finished pages. Settings such as target language and the language-model address are editable in the window. The API key, when used, is entered as a secret and is not stored in the settings file.

**Why this priority**: The window is the primary interactive surface for chapter-scale work and must expose the same translation contract as the command line.

**Independent Test**: Launch the window, drop a small set of pages, translate one page, confirm a result view appears, then export to a chosen folder.

**Acceptance Scenarios**:

1. **Given** the window is running, **When** the user adds image files or a top-level folder of images, **Then** a project is created or updated and the pages appear in the page list.
2. **Given** a project with idle pages, **When** the user starts translation for the current page or for all pages, **Then** each selected page moves through queued and running states and ends as done, offline, or error with a visible status.
3. **Given** the user enters a language-model API key through the secret control, **When** settings are saved, **Then** the key is available for requests and does not appear in the settings JSON on disk.
4. **Given** translation finished for one or more pages, **When** the user exports results, **Then** PNG or JPG files are written to the chosen folder according to the selected conflict rule.

---

### User Story 3 - Translate images from the browser extension over the local network (Priority: P2)

A user runs the app with remote access enabled, pairs the browser extension with a six-digit code, and translates large images on ordinary web pages. The extension shows a small translate control after the pointer stays on a qualifying image, replaces the image with the translated result when ready, and can play a completion chime for a full-page batch.

**Why this priority**: The extension depends on the remote contract but is optional relative to CLI and the window.

**Independent Test**: Enable remote access, pair the extension, translate one qualifying image on a test page, and confirm the image source switches to the translated result.

**Acceptance Scenarios**:

1. **Given** remote access is enabled and a fresh six-digit pairing code exists, **When** the extension submits that code, **Then** it receives a bearer token once and subsequent translate calls with that token are accepted.
2. **Given** a paired extension and a qualifying large image on a page, **When** the pointer stays on the image for two seconds, **Then** a compact translate control appears without covering the image in text.
3. **Given** a translate request was accepted, **When** the job reaches done, **Then** the extension fetches the result image and substitutes it for the original image display while keeping a way to show the original again.

---

### User Story 4 - Keep local UI local and remote access explicit (Priority: P2)

A user who only opens the desktop or browser UI keeps all local interface traffic on the loopback address. Remote listening stays off until the user turns it on. When remote access is on, traffic on the LAN uses ordinary HTTP without encryption, and the product warns that a firewall rule may be required on a private network.

**Why this priority**: The security boundary between local UI and LAN access is an explicit product promise.

**Independent Test**: Start the window without remote flags and confirm the UI binds only to loopback; start with remote enabled and confirm the separate remote listener accepts health and pairing on the configured bind address.

**Acceptance Scenarios**:

1. **Given** the window or browser UI mode without remote access, **When** the local interface starts, **Then** it listens only on `127.0.0.1` and rejects hosts or origins outside that loopback pair for local API routes.
2. **Given** remote access is disabled in settings and no remote launch flag is used, **When** the app starts, **Then** the remote listener is not accepting device traffic.
3. **Given** remote access is enabled for a run, **When** an unpaired client calls protected remote routes without a bearer token, **Then** those routes refuse the request.

---

### Edge Cases

- What happens when the language-model server is down or returns no vision model? The run must fall back to offline recognition and translation and warn the user.
- What happens when an archive contains no images? Import must fail without creating an empty project, with a clear message that there is nothing to translate.
- What happens when PNG transparency is present? Transparency is not preserved in the output.
- What happens when text sits on screentone rather than a flat balloon fill? Cleaning is allowed to be worse than on a flat fill; the run still completes.
- What happens when a second launch occurs while the window is already open? Paths from the second launch are handed to the first instance instead of opening a second window.
- What happens when remote rate limits or queue limits are exceeded? The remote API refuses with a busy response rather than accepting unbounded work.
- What happens when Ozon storefront pages are open with the extension installed? The content script must not inject on those hosts so product photos keep loading.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST accept page images in PNG, JPG/JPEG, BMP, and TIFF and produce a translated page image for each accepted input.
- **FR-002**: System MUST locate speech balloons and text regions on a page before recognition and translation.
- **FR-003**: System MUST recognize page text using a vision-capable language-model path when that server is available, and MUST fall back to the offline recognizer with a warning when it is not.
- **FR-004**: System MUST translate dialogue using the language-model path when available, including speaker and glossary context when provided, and MUST fall back to offline whole-block translation when the language-model path is unavailable.
- **FR-005**: System MUST remove original lettering only for regions that are being translated, then place the translation into the balloon shape.
- **FR-006**: System MUST leave sound-effect regions and object labels untranslated by default.
- **FR-007**: System MUST provide a command-line entry that translates a single page or a folder of pages into destination images.
- **FR-008**: System MUST provide a desktop window that manages projects, page statuses, translation jobs, settings, and export without requiring the command line for ordinary use.
- **FR-009**: System MUST keep the local window interface bound to loopback and MUST keep remote LAN listening off until the user enables it.
- **FR-010**: System MUST store the language-model API key outside settings JSON when the window secret control is used.
- **FR-011**: System MUST provide a remote pairing flow with a six-digit code that issues a bearer token once and authenticates later device calls with that token.
- **FR-012**: System MUST provide a browser extension that can pair to the remote listener, translate qualifying large images on ordinary web pages, and substitute the translated image when the job completes.
- **FR-013**: System MUST treat measurable mask quality on local reference pages as reference-only evidence and MUST NOT present that figure as guaranteed quality on arbitrary pages.
- **FR-014**: System MUST keep processing of a page on the single shared page-processing path used by command line, window, and remote jobs.
- **FR-015**: System MUST warn that remote LAN traffic is ordinary HTTP without encryption and that a private-network firewall rule may be required.
- **FR-016**: Browser extension MUST delay the translate control until the pointer has stayed on a qualifying image for two seconds and MUST present that control as a compact icon without on-image text label.
- **FR-017**: System MUST refuse empty archives during import rather than creating a project with nothing to translate.
- **FR-018**: Desktop window MUST hand paths from a second launch to the already running instance when that instance is alive.

### Key Entities

- **Page**: A single source image plus processing status, warnings, errors, and derived images for mask, cleaned page, and result.
- **Project**: A named collection of pages with source and target language choices and optional glossary and style library.
- **Translation job**: Queued work for one page or remote image, with progress stage and terminal state done, error, or cancelled.
- **Paired device**: A remote client identified after pairing, authorized by bearer token hash without storing the raw token in the device list.
- **Glossary entry**: Original name, translation, gender note, and optional remark used during scenario translation.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A user can translate one ordinary dialogue page from the command line to a result image without opening the window.
- **SC-002**: When the preferred language-model server is unavailable, a page run still completes with a visible fallback warning instead of failing silently.
- **SC-003**: With default sound-effect settings, dialogue balloons are translated and sound-effect or object-label regions remain in the source language on a page that contains both.
- **SC-004**: A user can create a project from files or a folder in the window, translate at least one page, and export a result image to a chosen folder in one session.
- **SC-005**: An API key entered through the window secret control never appears in the settings file on disk after save.
- **SC-006**: With remote access disabled, no unpaired device can submit a remote translate job to the local UI port.
- **SC-007**: After a successful pairing, the extension can complete one image translation and display the translated image in place of the original.
- **SC-008**: Product-facing statements about ink-recall figures always point to local reference evidence and state that arbitrary pages are not guaranteed.

## Assumptions

- Users run the tool on a local machine; internet exposure of the remote listener is out of scope for the promised contract.
- A vision-capable OpenAI-compatible server is optional; offline fallbacks are part of the contract when that server is absent.
- Roadmap items such as vertical Japanese columns, webtoon strip slicing, series-wide memory, EPUB/PDF export, and Flutter shell migration are directions only and are outside this baseline contract.
- Supported interactive target languages in the window and extension are Russian, English, and Ukrainian unless a user supplies another code through command-line configuration.
- Archive import supports common comic containers described in the product docs; formats outside that set are out of scope for this baseline.
