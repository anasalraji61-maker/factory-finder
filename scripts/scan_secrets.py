#!/usr/bin/env python3
"""Offline secrets/PII scan over git-tracked files (pure regex, no network).

Exit 1 if any non-allowlisted finding exists. Usage: python scripts/scan_secrets.py
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAX_BYTES = 2_000_000
BINARY_EXT = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".ttf",
    ".otf",
    ".woff",
    ".woff2",
    ".whl",
    ".ico",
    ".pdf",
    ".zip",
    ".gz",
}
SKIP_FILES = {"scripts/scan_secrets.py", "docs/fixes/secrets-scan.md"}
FAKE = re.compile(
    r"test|example|dummy|changeme|fake|sample|placeholder|xxx|redacted|your[-_ ]|\$\{|<[a-z_ -]+>|localhost|mock|demo|secret-for",
    re.I,
)
FAKE_EMAIL_DOMAINS = (
    "example.com",
    "example.org",
    "example.net",
    "test.com",
    "localhost",
    "invalid",
    "noreply",
    "@x.com",
)

RULES: list[tuple[str, re.Pattern[str]]] = [
    ("private-key", re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY")),
    ("aws-access-key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    (
        "github-token",
        re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b"),
    ),
    ("google-api-key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("slack-token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b")),
    ("llm-api-key", re.compile(r"\b(?:sk-ant-|sk-)[A-Za-z0-9_\-]{24,}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,}\b")),
    (
        "hardcoded-secret",
        re.compile(
            r"""(?ix)\b(?:password|passwd|secret|api[_-]?key|token)\b\s*[:=]\s*["']([^"'\s$\{<]{8,})["']"""
        ),
    ),
    ("local-path", re.compile(r"(?:/home/claude|/root/|/Users/[A-Za-z0-9_.-]+/)")),
    ("email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    (
        "phone",
        re.compile(r"(?<![\w.])\+\d{1,3}[ -]?\(?\d{2,4}\)?[ -]?\d{3,4}[ -]?\d{3,4}(?![\w.])"),
    ),
]


def tracked() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True
    ).stdout
    return [p for p in out.decode().split("\0") if p]


LARGE_OK = {"apps/mobile/assets/fonts/Cairo.ttf"} | {
    f for f in ("packages/py-common/pygments-2.21.0-py3-none-any.whl",)
}  # vendored public wheels (offline installs)  # bundled open-license font
TEST_PATH = re.compile(
    r"(^|/)(tests?|fixtures)/|(^|/)test_[^/]*$|_test\.dart$|^scripts/(e2e|contract_|serve_stack|smoke)"
)


def allowed(rule: str, line: str, match: str, rel: str = "") -> bool:
    if rule in {"email", "phone", "hardcoded-secret"} and TEST_PATH.search(rel):
        return True  # synthetic fixtures in tests/e2e scripts
    if rule == "email":
        return match.lower().endswith(FAKE_EMAIL_DOMAINS) or bool(FAKE.search(match))
    if rule == "phone":
        digits = re.sub(r"\D", "", match)
        return (
            bool(FAKE.search(line)) or len(set(digits)) <= 3 or "1234" in digits or "5550" in digits
        )
    if rule == "local-path":
        return False
    return bool(FAKE.search(line))


def main() -> int:
    findings: list[str] = []
    for rel in tracked():
        p = ROOT / rel
        if rel in SKIP_FILES or p.suffix.lower() in BINARY_EXT or not p.is_file():
            if p.is_file() and p.stat().st_size > 500_000 and rel not in SKIP_FILES | LARGE_OK:
                findings.append(f"{rel}: large-file ({p.stat().st_size // 1024} KiB)")
            continue
        name = p.name
        if name.startswith(".env") and name not in {".env.example", ".env.sample"}:
            findings.append(f"{rel}: env-file")
        if p.stat().st_size > MAX_BYTES:
            findings.append(f"{rel}: large-file")
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for n, line in enumerate(text.splitlines(), 1):
            for rule, rx in RULES:
                for m in rx.finditer(line):
                    if not allowed(rule, line, m.group(0), rel):
                        findings.append(f"{rel}:{n}: {rule}: {line.strip()[:100]}")
    for f in findings:
        print(f)
    print(f"scan_secrets: {len(findings)} finding(s)")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
