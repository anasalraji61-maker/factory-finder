# Secrets / PII scan

Tool: `scripts/scan_secrets.py` (`make secrets-scan`), pure-regex over `git ls-files`, offline.
Checks: private keys, AWS/GitHub/Google/Slack/LLM keys, JWTs, hardcoded password/secret/token literals,
emails, phone numbers, `/home/claude` `/root/` `/Users/x/` paths, stray `.env*` files, files > 500 KB.
Allowlist: lines with fake markers (test, example, dummy, changeme, mock, ...), emails/phones/secret literals
inside test paths (`tests/`, `test_*.py`, `*_test.dart`, e2e scripts), `.env.example`, bundled Cairo.ttf, one vendored wheel.

## Result (2026-10-15)
- Real findings: **0**. No keys, tokens, private keys, JWTs, local absolute paths or `.env` files tracked (only `.env.example`).
- Raw hits were all synthetic fixtures (`a@b.co`, `secret123`, `tok-internal-ABCDEF`, `Passw0rd!x` in test/e2e code) or
  documentation of `Bob@x.com`; handled by allowlist, no file edits needed.
- Note: 5 vendored `.whl` files are tracked in `packages/py-common/` (largest pygments, 1.2 MB). Public packages, not secrets;
  consider removing from git and pinning in requirements instead (orchestrator decision).
- `Passw0rd!x` in `scripts/serve_stack.py` is a local dev-stack demo password only.
