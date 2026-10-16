# infra

- `docker/Dockerfile.service` - shared service image.
- `prometheus/prometheus.example.yml` - example scrape config (no secrets).

## Scraping `/metrics` (guarded by `X-Internal-Token`)

Enable per service with `FF_<SVC>_METRICS=1` (compose forwards it, default off). The endpoint
requires the header `X-Internal-Token: $FF_INTERNAL_TOKEN` (see docs/RUNBOOK.md, Metrics).

Prometheus cannot set arbitrary request headers. Its `authorization:` block only sends
`Authorization: <type> <credentials>`, which is NOT equivalent: the service ignores
`Authorization` and would answer 401. Do not try `authorization.credentials` as a workaround, and
do not put the token in `params`/query strings (it would leak into logs).

Sidecar-free option: run ONE small collector on the internal network (OpenTelemetry Collector
`prometheus` receiver with a header-adding exporter/extension, Grafana Agent, Vector, or an
nginx `proxy_set_header X-Internal-Token ...` in front of the services) that holds the token from
its own environment and re-exposes the series. Point Prometheus at that collector (see example
file). Keep it off public networks and never publish service `/metrics`.
