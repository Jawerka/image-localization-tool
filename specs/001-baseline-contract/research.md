# Research: Baseline Product Contract

## Decision: Treat published docs as the source of intent

**Rationale**: README, APP, and EXTENSION already state the user-facing contract. SDD needs that contract written as `spec.md` so analysis and convergence can compare artefacts and code without inventing behaviour from implementation.

**Alternatives considered**: Inferring requirements only from code (hides doc/code drift); copying ROADMAP items into the baseline (turns directions into obligations).

## Decision: Verification plan, not rewrite

**Rationale**: The constitution demands a minimal diff and preserves CLI, window, extension, and LAN. The baseline feature records gaps; it does not redesign engines.

**Alternatives considered**: Full brownfield rewrite from a greenfield constitution (rejected: contradicts project principles and existing-product guide).

## Decision: Keep roadmap outside the baseline

**Rationale**: ROADMAP is explicitly non-binding. Including it would create false failures for unfinished directions.

**Alternatives considered**: Specifying every roadmap item as FR (rejected: invents commitments the product did not make).

## Decision: Reuse existing module boundaries in the plan

**Rationale**: Spec Kit plan needs concrete paths for later tasks. Mapping to `src/main.py`, `src/page_pipeline.py`, `src/app/`, `web/`, and `extension/` is enough for verification without new abstractions.

**Alternatives considered**: Introducing a new library-first packaging for every surface (rejected: Spec Kit sample constitution, not this project's constitution).
