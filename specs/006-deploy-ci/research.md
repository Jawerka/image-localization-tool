# Research: Deploy + CI

## Decision: Separate Windows and LAN scripts

**Rationale**: Different artifacts (onedir vs sources) and platforms. One mega-script would hide failures.

## Decision: Ordered host list, not DNS-only

**Rationale**: DHCP moved CT113 between `.168` and `.41`; try both.

## Decision: CI on Ubuntu with full requirements

**Rationale**: Most unit tests import opencv/torch; splitting a tiny subset under-covers. Cache pip. Exclude e2e/Playwright from required CI for this feature.
