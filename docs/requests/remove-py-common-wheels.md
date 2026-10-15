# Request: remove vendored wheels from packages/py-common

From: repo-hygiene review. To: orchestrator (git owner). Date: 2026-10-15.

## Finding

Five wheels are tracked in `packages/py-common/` (all added in one commit, `3db260d qa: rfq/tracking page+id bounds, admin static tests`, apparently by accident while installing dev deps offline):

| File | Bytes |
|---|---|
| pygments-2.21.0-py3-none-any.whl | 1,250,147 |
| pytest-9.1.1-py3-none-any.whl | 386,536 |
| packaging-26.3-py3-none-any.whl | 129,956 |
| pluggy-1.7.0-py3-none-any.whl | (small) |
| iniconfig-2.3.1-py3-none-any.whl | (small) |

They are exactly pytest's dependency closure (pytest -> pluggy, iniconfig, packaging, pygments).

## Evidence that nothing consumes them

Searched the whole repo (Makefile, `**/Dockerfile*`, `infra/`, `docker-compose*.yml`, `.github/workflows/*`, `.github/dependabot.yml`, all `pyproject.toml`, `scripts/`, `docs/`) for `.whl`, `wheelhouse`, `find-links`, `--no-index`, `py-common`.

- No install command uses them. CI (`.github/workflows/backend.yml`, job `py-common`, line 88) runs `pip install -e packages/py-common[dev] ...` from PyPI. No `--find-links`/`--no-index`.
- `packages/py-common/pyproject.toml` declares `dev = ["pytest>=8", ...]`; no path/file URLs.
- Dockerfiles / `install_service.py` only handle `services/<name>`; the decision log (`docs/decisions/ops-hardening.md`, 2026-10-15) confirms py-common is not installed into service images.
- Only mentions:
  - `scripts/scan_secrets.py` lines 80-82: `LARGE_OK` size allowlist for the pygments wheel (comment: "vendored public wheels (offline installs)"), plus `.whl` in `BINARY_EXT`. This is an exemption, not a consumer.
  - `docs/fixes/secrets-scan.md` line 13: already suggests removing them and pinning in requirements.

Conclusion: unreferenced; safe to remove. I did not delete anything (agents do not delete tracked files, and git is the orchestrator's job).

## Exact commands for the orchestrator

```
git rm packages/py-common/iniconfig-2.3.1-py3-none-any.whl \
       packages/py-common/packaging-26.3-py3-none-any.whl \
       packages/py-common/pluggy-1.7.0-py3-none-any.whl \
       packages/py-common/pygments-2.21.0-py3-none-any.whl \
       packages/py-common/pytest-9.1.1-py3-none-any.whl
```

Optional follow-ups after the removal (outside my lane, so not done):
1. In `scripts/scan_secrets.py` drop the now-dead `packages/py-common/pygments-...whl` entry from `LARGE_OK` (keep the Cairo.ttf entry) and optionally `.whl` from `BINARY_EXT`.
2. Add `*.whl` to `.gitignore` to prevent recurrence.
3. If offline installs are ever needed, use a pinned requirements file (e.g. `packages/py-common/requirements-dev.txt` with `pytest==9.1.1`, `pluggy==1.7.0`, `iniconfig==2.3.1`, `packaging==26.3`, `pygments==2.21.0`, ideally with `--hash`) and `pip download -r ... -d wheelhouse/` into an untracked directory.
4. Note: history still holds the blobs (~1.8 MB); rewriting history is not worth it at this size.

## Other suspicious / stray files

Top 25 tracked files by size were reviewed (`git ls-files -z | xargs -0 ls -l | sort`). Besides the wheels, everything is legitimate source, data, contracts or docs:
- `apps/mobile/assets/fonts/Cairo.ttf` (600 KB): open-license font, allowlisted in the secrets scan.
- Large JSON under `services/*/src/*/data/` (cities 150 KB, hs_codes 141 KB, compliance 137 KB, catalog 99 KB, hubs 78 KB, hs_keywords 75 KB, duties 58 KB): intentional bundled datasets.
- `services/assistant/tests/fixtures/routing_cases.json` (54 KB): test fixture.
- Large but normal: `contracts/openapi/*.yaml`, `services/freight/src/ff_freight/service.py` (63 KB), `scripts/e2e*.py`, `docs/RUNBOOK.md` (42 KB).

Tracked-file pattern scan for `*.orig *.rej *.log *.bak *.tmp *.swp *.pyc __pycache__ .venv .ruff_cache .DS_Store .env`: no matches. Root contains no stray files; `.venv/` and `.ruff_cache/` exist locally but are untracked and covered by `.gitignore`. `.env.example` is 20 KB (large for a template, but expected; secrets scan reported no real values).

Nothing else suspicious.
