# ARGOS Project Status

Date: 2026-08-02

## Implemented

- SQLite backup/restore tooling and duplicate audits.
- Database natural uniqueness for Ecowitt observations and satellite assets.
- Shared ingestion traceability tables and service.
- Data layout settings and compatibility helpers.
- File inventory, legacy weather reconciliation, satellite orphan reconciliation, layout migration dry-run/apply, retention report and staging audit commands.
- Windows backup scheduling scripts and documentation.

## Validated On Copy

- Traceability migrations through Alembic `20260802_0023`.
- Full `data/` layout apply over `.pytest-tmp/layout-copy/data`.
- Idempotent second dry-run after copy migration with 0 planned moves.
- Satellite asset references after copy migration: 3,067 files present, 0 size mismatches, 0 unlinked assets.

## Deployed In Active Local Database

- Active `var/argos.db` is at Alembic `20260802_0023`.
- SQL integrity check is `ok`.
- Duplicate and Ecowitt nullability audits are clean.
- Real `data/` layout has been migrated.
- Final file count remains 4,727: 1 `raw`, 3,067 `processed`, 1,659 `legacy`.
- `satellite_assets` uses 3,067 `processed/%` paths and 0 old `satellite/%` paths.
- 4,602 `source_artifacts` are present and audit clean.
- Real migration report: `var/migration-reports/data-layout-real/summary-20260802T183446Z.md`.

## Pending Manual Review

- 125 `data/weather` legacy files remain preserved.
- 1,534 unscoped satellite PNGs are preserved under `data/legacy/satellite`; 1,522 are ambiguous legacy previews and 12 are physical duplicates by SHA-256.
- No automatic file deletion is implemented.
- Windows scheduled backup task is documented but must be registered explicitly by an operator.
