# ARGOS Data Flow

```mermaid
flowchart LR
    ecowitt_lan["Ecowitt GW2000<br/>Customized HTTP upload"] --> ecowitt_endpoint["POST /api/v1/ecowitt/upload/{token}"]
    ecowitt_endpoint --> ecowitt_parse["WS90 parser<br/>normalization + payload hash"]
    ecowitt_parse --> ecowitt_raw_sql[("ecowitt_raw_reports<br/>raw payload JSON/text")]
    ecowitt_parse --> weather_sql[("weather_observations<br/>normalized weather")]
    ecowitt_parse --> quality_sql[("unknown_fields<br/>ingestion_events<br/>data_gaps")]
    weather_sql --> stats_worker["weather_statistics service"]
    stats_worker --> weather_stats[("daily_statistics<br/>weekly_statistics")]

    ecowitt_cloud["Ecowitt Cloud API"] --> cloud_cli["CLI / scheduled sync<br/>ecowitt-cloud backfill"]
    cloud_cli --> cloud_adapter["Cloud history adapter<br/>normalized records + hash"]
    cloud_adapter --> cloud_raw_sql[("ecowitt_cloud_raw_reports<br/>raw provider payload")]
    cloud_adapter --> weather_sql
    cloud_adapter --> quality_sql

    aemet["AEMET OpenData / CSV"] --> aemet_client["AemetClient or import-csv"]
    aemet_client --> aemet_norm["AEMET normalizer"]
    aemet_norm --> aemet_station[("weather_stations")]
    aemet_norm --> aemet_daily[("weather_daily_observations<br/>raw_payload_json + typed columns")]
    aemet_norm --> aemet_runs[("aemet_sync_runs")]
    local_aemet_csv["data/aemet/6127X.csv<br/>local CSV seed"] -. manual input .-> aemet_client

    copernicus["Copernicus CDSE<br/>STAC + Statistics + Process API"] --> sat_service["SatelliteIngestionService<br/>CLI / API / scheduled sync"]
    sat_service --> sat_zones[("satellite_sources<br/>satellite_zones")]
    sat_service --> sat_obs[("satellite_observations<br/>raw_metadata_json")]
    sat_service --> sat_metrics[("satellite_metrics")]
    sat_service --> sat_files["data/satellite/**.png<br/>preview assets"]
    sat_files --> sat_assets[("satellite_assets<br/>path + checksum + size")]
    sat_obs --> sat_metrics
    sat_obs --> sat_assets

    argos_node["argos-node<br/>/status + valve endpoints"] --> node_worker["startup worker or CLI<br/>minute aggregation"]
    node_worker --> flow_minutes[("argos_node_flowmeter_minutes")]
    node_worker --> flow_sessions[("argos_node_flowmeter_sessions")]
    node_worker --> flow_resets[("argos_node_flowmeter_reset_events")]

    operator["Dashboard / API operator"] --> field_api["/api/v1/field-events"]
    field_api --> field_sql[("field_events")]

    db[(("SQLite var/argos.db<br/>or PostgreSQL DATABASE_URL"))]
    ecowitt_raw_sql --> db
    cloud_raw_sql --> db
    weather_sql --> db
    weather_stats --> db
    quality_sql --> db
    aemet_station --> db
    aemet_daily --> db
    aemet_runs --> db
    sat_zones --> db
    sat_obs --> db
    sat_metrics --> db
    sat_assets --> db
    flow_minutes --> db
    flow_sessions --> db
    flow_resets --> db
    field_sql --> db

    db --> fastapi["FastAPI read/admin endpoints"]
    fastapi --> dashboard["Streamlit dashboard"]
    db --> analytics["Analytics services<br/>series, correlations, trends"]
    data_weather["data/weather<br/>legacy raw JSON + CSV"] -. not referenced by current code .-> audit_note["Audit follow-up<br/>classify or migrate"]
```
