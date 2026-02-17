# Reliability Rehearsal Report Template

Use this template after each burst-load rehearsal run.

## Run Metadata

- Date/time (UTC):
- Environment (local/VPS/staging/prod-like):
- Base URL:
- Commit SHA:
- Operator:

## Scenario Config

- Register count:
- Login count:
- Idea count:
- Max concurrency:
- Burst window seconds:
- Retry policy (max/base/max delay):

## Aggregate Results

- Success rate (%):
- Hard failure rate (%):
- Transient recovery rate (%):
- Duplicate writes:
- Gate status (`passed`):

## Scenario Breakdown

1. Test A: Connection Limit + Polling Storm
- total/success/transient/hard:
- p50/p95/p99 latency (ms):
- notes:

2. Test B: CPU Lock (Failed Logins)
- total/success/transient/hard:
- p50/p95/p99 latency (ms):
- notes:

3. Test C: Static Asset Drag
- total/success/transient/hard:
- p50/p95/p99 latency (ms):
- dashboard + static asset split:
- notes:

## Required Telemetry

- DB connection saturation signals (`QueuePool limit ... reached`):
- HTTP 504 count:
- Event loop lag ms (max/p95/p99):

## Grafana Cloud Links

- Dashboard URL:
- Explore query URL:
- Alert snapshots:

## Pass/Fail Decision

- Go/No-Go:
- Blocking issues:
- Follow-up actions:
