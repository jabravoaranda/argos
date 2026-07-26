# ARGOS Pending Decisions

This file records decisions that should wait for operator input or real station evidence.

## Ecowitt Cloud Backfill

Current implementation:

- Direct LAN Customized ingestion remains primary.
- Ecowitt Cloud can be queried through the internal client.
- Cloud history payloads can be adapted when fields include explicit units.
- Cloud raw payloads are stored separately in `ecowitt_cloud_raw_reports`.
- Imported Cloud observations are marked as `BACKFILLED`.
- Existing direct observations are not duplicated by Cloud imports.
- Manual CLI entrypoint exists:

```powershell
uv run argos ecowitt-cloud backfill `
  --start 2026-07-10T00:00:00Z `
  --end 2026-07-10T01:00:00Z `
  --gateway-identifier GW2000A `
  --station-type GW2000A_V3.3.2 `
  --cloud-mac AABBCCDDEEFF
```

Decisions needed:

1. Confirm hardware metadata values for the current GW2000.

   Decision made: the canonical station slug is `tomillar`, representing the physical site. Gateway MAC, model, serial number and Ecowitt-specific identifiers are hardware metadata and must not become the station identity.

2. Capture one real Ecowitt Cloud history response.

   The adapter is intentionally conservative and only imports fields whose units are explicit or unambiguous. A real GW2000A + WS90 Cloud payload is needed to confirm field nesting, timestamps and units.

3. Choose the operator interface for backfill.

   Current recommendation: keep CLI as the first operational interface. Add an admin API endpoint only after the real payload shape and gateway identity rules are validated.

4. Decide whether Cloud may enrich direct observations.

   Current behavior: if a direct observation exists at the same timestamp, the Cloud raw payload is preserved but the direct observation is not modified. Later, ARGOS could optionally fill missing direct fields from Cloud, but that should be explicit and auditable.

5. Define maximum backfill windows.

   ARGOS now enforces a conservative configurable window through `ECOWITT_CLOUD_MAX_BACKFILL_HOURS` with a default of 24 hours. Still pending: confirm Ecowitt account-specific history limits and resolution changes using a real Cloud response before exposing backfill as routine operation.
