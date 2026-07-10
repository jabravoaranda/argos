# ARGOS Dashboard Analytics Plan

This document tracks the scientific statistics and charts planned for the dashboard. The dashboard should remain a visualization layer over API and analytics services, not a place for ingestion logic.

## Core descriptive statistics

For numeric weather variables, ARGOS should expose:

- sample count;
- valid count;
- missing count and missing percentage;
- mean;
- median;
- standard deviation;
- minimum and maximum;
- 5th and 95th percentiles;
- interquartile range;
- simple linear trend for selected periods;
- slope per day, estimated period change and R2 for linear trend diagnostics;
- rolling means for configurable windows.

## Temporal products

Daily:

- intraday time series;
- hourly aggregation;
- daily minimum, maximum, mean and median;
- daily rainfall accumulation;
- maximum gust;
- solar radiation maximum and future daily irradiation estimate;
- UV maximum.

Weekly:

- daily evolution within ISO week;
- weekly accumulated rainfall;
- weekly extrema;
- source coverage and gaps.

Monthly:

- daily evolution within month;
- monthly rainfall;
- monthly extrema and percentiles;
- heat/rain event candidates.

Seasonal:

- meteorological seasons: DJF, MAM, JJA and SON;
- seasonal rainfall;
- seasonal temperature and humidity distribution;
- seasonal wind and radiation summaries.

Annual:

- monthly evolution;
- annual rainfall;
- annual extrema and percentiles;
- trend and anomaly views against the selected period.

## Dashboard deployment proposal

Recommended first dashboard layout:

- Home: operational status, current conditions and latest station hardware.
- Observations: high-resolution time series for selected raw/normalized variables.
- Summaries:
  - Daily: persisted daily summaries and daily rainfall/temperature charts.
  - Weekly: persisted weekly summaries for operational review.
  - Monthly: derived monthly statistics from daily summaries.
  - Seasonal: DJF/MAM/JJA/SON summaries for scientific interpretation.
  - Annual: yearly totals and extrema from daily summaries.
- Trends:
  - one selected variable at a time for detailed diagnostics;
  - moving average, anomaly and linear trend in the same chart;
  - descriptive statistics table for all selected variables;
  - CSV export for reproducibility.
- Quality:
  - data gaps;
  - ingestion events;
  - unknown fields;
  - redacted raw-payload inspection.

Avoid putting all products on a single page. The better progression is:

1. Keep Streamlit as the fast local scientific dashboard.
2. Add period-specific chart helpers in `argos.dashboard`.
3. Move expensive or canonical monthly, seasonal and annual calculations into backend services once formulas stabilize.
4. Persist those products only after they are validated against real data.

Charts to prioritize next:

- hourly daily/selected-period profile;
- rainfall accumulation by period;
- monthly climatology bars;
- seasonal distribution plots;
- annual anomaly bars;
- wind rose when wind-direction aggregation rules are defined.

## Implementation status

- Implemented: direct observations, hourly selected-period profile, daily and weekly API summaries, monthly, seasonal and annual dashboard aggregates, descriptive statistics, moving averages, anomaly from period mean and linear trend diagnostics.
- Next: richer period-specific charts for daily, weekly, monthly, seasonal and annual views.
- Later: persisted monthly/seasonal/annual statistics in the backend, wind roses, dry-period detection, rain-event detection and solar irradiation.
