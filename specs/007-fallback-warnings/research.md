# Research

## Decision: Capture warnings on LamaInpainter, merge in pipeline

Same pattern as OCR/translator `.warnings` attributes.

## Decision: Do not map OpenCV fallback to status=offline

Offline UI string is «без LLM»; OpenCV cleanup is a different degradation. Banner + document.warnings suffice.
