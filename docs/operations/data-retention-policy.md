# ARGOS Data Retention Policy

Date: 2026-08-02

This phase defines reporting only. No automatic deletion is enabled.

| Category | Authority | Regenerable | Retention | Automatic deletion |
|---|---|---:|---|---:|
| `raw` | source evidence | variable | prolonged or indefinite | no |
| `staging` | temporary | yes | short | yes, only in a future phase with safeguards |
| `processed` | derived | normally | configurable | no initially |
| `exports` | convenience | yes | short or medium | yes, only in a future phase |
| `cache` | non-authoritative | yes | short | yes, only in a future phase |
| `legacy` | unknown | not confirmed | indefinite until resolved | no |
| `quarantine` | conflicting | not confirmed | until review | no |

## Current Command

```powershell
argos data retention-report
```

The command reports files that would be eligible under future policy, but deletes nothing. Protected categories are `raw`, `legacy` and `quarantine`.

## Future Cleanup Conditions

A future cleanup command may delete only files that are all of:

- regenerable;
- not linked to an active ingestion run;
- older than the configured threshold;
- not immutable;
- not classified as `raw`, `legacy` or `quarantine`;
- represented in a current manifest.

Deletion still requires a separate implementation and operator approval.
