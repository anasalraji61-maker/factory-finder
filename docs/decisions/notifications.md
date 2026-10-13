2026-10-13 | First evaluation of a watch only sets the baseline price (no alert) | drops are measured from the last price the owner was told about
2026-10-13 | One push summary per owner per evaluation run, in each device's locale | avoid push spam
2026-10-13 | Storage = JSON documents with indexed columns; unique (watch, rule, fingerprint) | simple, portable SQLite/Postgres
2026-10-13 | Watches/alerts/devices of other users answer 403; evaluate is internal-token protected when FF_INTERNAL_TOKEN is set | ownership rule
