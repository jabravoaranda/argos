# ARGOS Data Layout

Estado: Vigente
Tipo: Arquitectura
Fuente de verdad: `docs/00-estado-del-proyecto.md`
Ultima actualizacion: 2026-08-02
Responsable logico: Arquitectura de datos
Revision: 1

Date: 2026-08-02

ARGOS uses SQL as the source of truth for normalized observations, metrics, run state and manual records. Files under `data/` are source evidence, derived products, exports, cache or unresolved legacy material. New code centralizes filesystem roots through settings and stores new data-relative paths where possible.

## Directory Model

```text
data/
  raw/
    aemet/
    ecowitt/
    satellite/
  staging/
  processed/
    satellite/
  exports/
  cache/
  legacy/
    weather/
  quarantine/
```

| Directory | Role | Writes in this phase |
|---|---|---|
| `raw/` | Immutable source evidence. | AEMET CSVs are planned for `raw/aemet/`. |
| `staging/` | Temporary incomplete ingestion files. | Audited only. |
| `processed/` | Derived products worth preserving. | New satellite previews default to `processed/satellite/`. |
| `exports/` | User-facing downloads. | Retention report only. |
| `cache/` | Fully regenerable non-authoritative files. | Retention report only. |
| `legacy/` | Historical files whose semantics are unresolved. | Current preserved weather and unscoped satellite legacy files. |
| `quarantine/` | Corrupt/conflicting files. | Manual review only. |

## Settings

These settings define the data roots:

```text
ARGOS_DATA_DIR
ARGOS_RAW_DIR
ARGOS_STAGING_DIR
ARGOS_PROCESSED_DIR
ARGOS_EXPORTS_DIR
ARGOS_CACHE_DIR
ARGOS_LEGACY_DIR
ARGOS_QUARANTINE_DIR
```

When category-specific variables are omitted, ARGOS derives them from `ARGOS_DATA_DIR`. Path resolution rejects traversal outside the data root for migration planning. SQL storage paths prefer data-relative strings such as `processed/satellite/...`; legacy absolute or `data/satellite/...` paths remain readable.

## Satellite Decision

Historical satellite PNG previews are classified as `processed`, not `cache`.

Reasoning:

- They are derived from Copernicus products, AOI geometry and processing version.
- The scientific source of truth is SQL metrics and raw STAC/statistics metadata, not the PNG.
- Regeneration is conditional, not guaranteed: it depends on provider availability, credentials, original product availability, AOI geometry and processing code.
- The files are referenced by SQL and useful for visual inspection.

Therefore they should be preserved and migrated to `processed/satellite/`. They may become deletable only after a later policy explicitly proves regeneration and user value tradeoffs.

## Migration Procedure

Use dry-run first:

```powershell
argos data inventory-files
argos data reconcile-legacy-weather
argos data migrate-layout --dry-run
```

Real application requires explicit approval:

```powershell
argos data migrate-layout --apply
```

The command is idempotent and resumable. It writes manifests and logs under `var/manifests`, verifies SHA-256 before and after moves, does not overwrite conflicting destinations and updates SQL paths only after the destination is verified.

## Current State

- Traceability migrations are deployed on active `var/argos.db` at `20260802_0023`.
- Physical migration of the real `data/` tree has been applied.
- Full apply was validated on `.pytest-tmp/layout-copy/data` with a restored DB copy.
- Copy validation result: 4,727 planned/applied moves, 0 conflicts, 0 source artifact audit issues, 0 missing satellite asset files, 0 size mismatches, 3,067 satellite assets linked to artifacts.
- Real post-migration state: 4,727 files total, 1 raw AEMET CSV, 3,067 processed satellite previews referenced by SQL, and 1,659 legacy files.
- The 1,534 unscoped satellite PNG files not referenced by `satellite_assets` were moved to `data/legacy/satellite` after checksum verification and remain preserved for manual review.
- The real migration summary is `var/migration-reports/data-layout-real/summary-20260802T183446Z.md`.

## Phase 5 Orphan Policy

Unscoped legacy satellite previews under `data/legacy/satellite/sentinel-2-l2a/...` are not automatically attached to SQL when the same scene exists for multiple AOIs. The association lacks a zone signal, so these files are classified as `legacy_preview` unless a later manual review supplies stronger evidence.

`argos data reconcile-orphan-satellite-assets` writes a reproducible JSON manifest and markdown report. `--apply-recoverable` creates only unambiguous missing `satellite_assets` rows and corresponding `source_artifacts`; it does not create observations, overwrite existing assets, move files or delete anything.
