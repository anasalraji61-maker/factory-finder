#!/usr/bin/env python3
"""Offline static checks for docker-compose.yml / docker-compose.prod.yml / .env.example / Makefile / workflows.

Pure python (pyyaml only), no network, no docker. Exit code 1 on any violated invariant.
Run: make compose-check
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
PORT_RANGE = range(8101, 8115)
errors: list[str] = []


def err(msg: str) -> None:
    errors.append(msg)


def load(name: str) -> dict:
    return yaml.safe_load((ROOT / name).read_text(encoding="utf-8"))


def env_of(svc: dict) -> dict[str, str]:
    e = svc.get("environment") or {}
    if isinstance(e, list):
        return {k: v for k, _, v in (i.partition("=") for i in e)}
    return {k: "" if v is None else str(v) for k, v in e.items()}


def main() -> int:
    base = load("docker-compose.yml")
    prod = load("docker-compose.prod.yml")
    services = {n: s for n, s in base["services"].items() if (ROOT / "services" / n).is_dir()}
    dirs = {p.name for p in (ROOT / "services").iterdir() if (p / "src").is_dir()}

    # 1. every service dir is in compose, with a build arg, PORT, matching healthcheck, no published backend ports
    for d in sorted(dirs - set(services)):
        err(f"services/{d} has no entry in docker-compose.yml")
    ports: dict[int, str] = {}
    for name, svc in services.items():
        env = env_of(svc)
        build = svc.get("build") or {}
        if (build.get("args") or {}).get("SERVICE") != name:
            err(f"{name}: build.args.SERVICE must be '{name}'")
        if not (ROOT / build.get("dockerfile", "-")).is_file():
            err(f"{name}: dockerfile {build.get('dockerfile')} missing")
        port = env.get("PORT")
        if not port or not port.isdigit():
            err(f"{name}: environment PORT missing")
            continue
        port_i = int(port)
        if port_i in ports:
            err(f"{name}: PORT {port} also used by {ports[port_i]}")
        ports[port_i] = name
        if name != "gateway" and port_i not in PORT_RANGE:
            err(f"{name}: PORT {port} outside 8101-8114")
        if name == "gateway" and port_i != 8000:
            err("gateway: PORT must be 8000")
        hc = " ".join(map(str, (svc.get("healthcheck") or {}).get("test") or []))
        if f"localhost:{port}/health" not in hc:
            err(f"{name}: healthcheck does not probe localhost:{port}/health")
        if name != "gateway":
            if svc.get("ports"):
                err(f"{name}: backend service must not publish ports (only the gateway does)")
            if str(port) not in [str(x) for x in svc.get("expose") or []]:
                err(f"{name}: expose should list {port}")
        if "FF_ENV" not in env:
            err(f"{name}: FF_ENV not passed through")
        if "FF_INTERNAL_TOKEN" not in env:
            err(f"{name}: FF_INTERNAL_TOKEN not passed through")
        mvar = f"FF_{name.upper()}_METRICS"
        if mvar not in env:
            err(f"{name}: {mvar} not passed through (obs.py reads it dynamically)")
        elif env[mvar] != "${" + mvar + ":-}":
            err(f"{name}: {mvar} must default to empty/off, expected ${{{mvar}:-}}, got {env[mvar]!r}")
        main_py = ROOT / "services" / name / "src" / f"ff_{name}" / "main.py"
        if not main_py.is_file():
            err(f"{name}: {main_py.relative_to(ROOT)} missing (Dockerfile runs ff_{name}.main:app)")

    # gateway upstreams point at the right host:port and every depends_on is a service
    gw = services.get("gateway")
    if gw:
        import json

        ups = json.loads(env_of(gw)["FF_GATEWAY_UPSTREAMS"])
        for n, url in ups.items():
            m = re.fullmatch(rf"http://{n}:(\d+)", url)
            if not m or n not in ports.values() or ports.get(int(m.group(1))) != n:
                err(f"gateway upstream {n}={url} does not match the service host/PORT")
        for n in set(ports.values()) - {"gateway"} - set(ups):
            err(f"gateway FF_GATEWAY_UPSTREAMS lacks {n}")
        for n in set(gw.get("depends_on") or {}) - set(services):
            err(f"gateway depends_on unknown service {n}")

    # inter-service URLs inside any env value must reference a real host:port
    for name, svc in services.items():
        for k, v in env_of(svc).items():
            if k == "FF_GATEWAY_UPSTREAMS":
                continue
            for host, p in re.findall(r"http://([a-z]+):(\d+)", v):
                if ports.get(int(p)) != host:
                    err(f"{name}: {k} -> {host}:{p} is not a known service/port")

    # 2. env var names must be known to the service (literal in its source, or a config field of its prefix)
    for name, svc in services.items():
        src = "\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in (ROOT / "services" / name / "src").rglob("*.py"))
        cfg_prefix = None
        m = re.search(r'env_prefix="(FF_[A-Z_]+_)"', src)
        if m:
            cfg_prefix = m.group(1)
        for k in env_of(svc):
            if k in ("PORT", "FF_ENV", "FF_INTERNAL_TOKEN", f"FF_{name.upper()}_METRICS") or k in src:
                continue
            if cfg_prefix and k.startswith(cfg_prefix) and re.search(rf"\b{k[len(cfg_prefix):].lower()}\b", src):
                continue
            err(f"{name}: env {k} is not read by services/{name} (typo or stale)")

    # 3. prod override covers each guard
    guards: dict[str, set[str]] = {}
    for name in dirs:
        text = "\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in (ROOT / "services" / name / "src").rglob("main.py"))
        need = set(re.findall(r"FF_ENV=production requires (FF_[A-Z0-9_]*[A-Z0-9])\b(?!\{)", text))
        if "FF_PAYMENTS_WEBHOOK_SECRET_{" in text:
            need |= {"FF_PAYMENTS_WEBHOOK_SECRET_USDT_TRON"}
        if name == "gateway":
            need |= {"FF_GATEWAY_JWT_SECRET", "FF_GATEWAY_ADMIN_TOKEN", "FF_INTERNAL_TOKEN", "FF_GATEWAY_CORS_ORIGINS"}
        guards[name] = need
    pservices = prod.get("services") or {}
    for name in services:
        penv = env_of(pservices.get(name) or {})
        if penv.get("FF_ENV") != "production":
            err(f"prod: {name} lacks FF_ENV: production")
        for var in sorted(guards.get(name, set())):
            val = penv.get(var, "")
            if not val.startswith("${" + var + ":?"):
                err(f"prod: {name} must set {var}: ${{{var}:?...}} (fail-closed guard)")
    for n in set(pservices) - set(services):
        err(f"prod: unknown service {n}")

    # 4. .env.example lists every required prod var (uncommented, empty) and every ${VAR} used by compose
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    defined = {m.group(1): m.group(2).split("#")[0].strip() for m in re.finditer(r"^([A-Z][A-Z0-9_]*)=(.*)$", example, re.M)}
    mentioned = set(re.findall(r"^#?\s*([A-Z][A-Z0-9_]*)=", example, re.M))
    required = {v for s in guards.values() for v in s}
    for v in sorted(required):
        if v not in defined:
            err(f".env.example: required prod var {v} missing as an uncommented line")
        elif defined[v] not in ("", "[]"):
            err(f".env.example: {v} must have an empty value (repo is public), got {defined[v]!r}")
    raw = (ROOT / "docker-compose.yml").read_text(encoding="utf-8") + (ROOT / "docker-compose.prod.yml").read_text(encoding="utf-8")
    for v in sorted(set(re.findall(r"\$\{([A-Z][A-Z0-9_]*)[:}-]", re.sub(r"\$\{VAR[^}]*\}", "", raw)))):
        if v not in mentioned:
            err(f".env.example: compose uses ${{{v}}} but it is not listed")
    for v, val in defined.items():
        if re.search(r"(SECRET|TOKEN|PASSWORD|KEY|CREDENTIALS)", v) and val not in ("", "mock"):
            err(f".env.example: {v} looks like a secret with a non-empty value")

    # 5. Makefile targets + scripts exist
    mk = (ROOT / "Makefile").read_text(encoding="utf-8")
    for s in sorted(set(re.findall(r"(?:scripts|infra)/[\w./-]+\.(?:py|sh|yml)", mk))):
        if not (ROOT / s).is_file():
            err(f"Makefile references missing {s}")
    phony = set(" ".join(re.findall(r"^\.PHONY:(.*)$", mk, re.M)).split())
    for t in re.findall(r"^([a-z][\w-]*):", mk, re.M):
        if t not in phony:
            err(f"Makefile target {t} not in .PHONY")
    m = re.search(r"^SERVICES :=(.*)$", mk, re.M)
    if m and set(m.group(1).split()) != dirs:
        err(f"Makefile SERVICES {sorted(m.group(1).split())} != services/ dirs {sorted(dirs)}")

    # 6. workflows: parse, referenced paths exist, matrix covers all services
    for wf in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        text = wf.read_text(encoding="utf-8")
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as e:
            err(f"{wf.name}: invalid YAML ({e})")
            continue
        if not data:
            err(f"{wf.name}: empty")
            continue
        for p in set(re.findall(r"(?<![\w/.-])((?:scripts|contracts|infra|packages)/[\w./-]+\.(?:py|sh|yml|yaml|json))", text)):
            if "${{" not in p and not (ROOT / p).exists():
                err(f"{wf.name}: references missing {p}")
        for wd in re.findall(r"working-directory:\s*([\w./-]+)", text):
            # apps/mobile/android and ios are generated in CI, not checked in
            generated = wd.rstrip("/") in ("apps/mobile/android", "apps/mobile/ios")
            if not generated and not (ROOT / wd).is_dir():
                err(f"{wf.name}: working-directory {wd} missing")
    be = (ROOT / ".github" / "workflows" / "backend.yml").read_text(encoding="utf-8")
    for d in sorted(dirs):
        if not re.search(rf"\b{d}\b", be):
            err(f"backend.yml matrix does not mention service {d}")

    if errors:
        print(f"compose-check: {len(errors)} problem(s)")
        for e in errors:
            print(" -", e)
        return 1
    print(f"compose-check: OK ({len(services)} services, ports {min(ports)}-{max(ports)}, {len(required)} prod-required vars)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
