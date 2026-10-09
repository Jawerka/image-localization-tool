# Data Model: Baseline Product Contract

## Page

Represents one source image under processing.

- **Identity**: page id within a project
- **Source**: absolute source image path
- **Status**: idle, queued, running, done, edited, offline, error
- **Progress**: stage label and progress value while running
- **Warnings / error**: user-visible messages
- **Derived images**: mask, cleaned page, result, thumbnail
- **Document**: editable region set after recognition/translation

## Project

Named collection of pages.

- **Identity**: project id
- **Name**: display name
- **Languages**: source language preference and target language
- **Pages**: ordered list of page references
- **Glossary**: optional speaker/name entries
- **Styles**: optional style library; empty library may expose defaults without writing disk

## Translation job

Unit of queued work.

- **Local job**: tied to project page; kinds include translate, typeset/clean follow-ups, export
- **Remote job**: tied to paired device image bytes; statuses queued, running, done, error
- **Limits**: unfinished remote jobs capped; protected remote routes rate-limited per device

## Paired device

Remote client after successful pairing.

- **Identity**: device id
- **Name**: optional label from pairing
- **Token**: raw token issued once; only hash retained in device list
- **Created**: pairing time

## Glossary entry

- **Original**: source spelling
- **Translation**: preferred rendering
- **Gender / note**: optional guidance for agreement and context

## Settings and secrets

- **Settings file**: non-secret preferences including LLM address, sound-effect mode, export defaults, remote enablement
- **API key**: stored outside settings JSON through the OS secret store when set from the window
