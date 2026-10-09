# Tasks: Deploy Scripts + Unit CI

**Input**: `/specs/006-deploy-ci/`

## Phase 1: Spec

- [x] T001 Spec/plan/research/data-model/quickstart/checklist

## Phase 2: Deploy scripts

- [x] T002 `scripts/deploy-windows.ps1` — mirror dist to apps; optional build; skip models by default
- [x] T003 `scripts/deploy-lan.ps1` — host fallback, sync src/web, restart service, DryRun
- [x] T004 Unit static checks in `tests/unit/test_deploy_scripts.py`

## Phase 3: CI

- [x] T005 `.github/workflows/ci.yml` unit job with marker filter
- [x] T006 Document in quickstart; progress + converge
