#!/usr/bin/env python3
"""Install a Factory Finder service, or only its declared dependencies, from its pyproject.toml.

The Dockerfile, CI and `make venv` all use this script, so dependencies resolve the same way
everywhere. It installs into the interpreter that runs it (``sys.executable -m pip``).

    python scripts/install_service.py services/geo                        # pip install services/geo
    python scripts/install_service.py services/geo --editable --extras dev,test
    python scripts/install_service.py services/geo --deps-only --extras dev,test
    python scripts/install_service.py /app --no-deps --best-effort        # Docker, step 2
    python scripts/install_service.py services/geo --dry-run              # print the pip commands

Strategy: try ``pip install [-e] <dir>[extras]``. If that fails (no [build-system], a broken
package config, ...), fall back to installing the requirement lists declared in [project]
(dependencies + optional-dependencies) and [dependency-groups]. The package itself is optional:
pytest runs the code from <dir>/src (``pythonpath = ["src"]``) and the Docker image sets
PYTHONPATH=/app/src.

Exit codes: 0 = ok, 1 = pip failed, 2 = bad usage (e.g. no pyproject.toml).
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tomllib
from pathlib import Path

_NAME_RE = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*(?:\[([^\]]*)\])?")


def _normalize(name: str) -> str:
    """PEP 503 normalized project name."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _expand_group(groups: dict, name: str, seen: set[str]) -> list[str]:
    """Flatten a PEP 735 dependency group (supports {include-group = "..."})."""
    if name in seen or name not in groups:
        return []
    seen.add(name)
    out: list[str] = []
    for item in groups[name]:
        if isinstance(item, str):
            out.append(item)
        elif isinstance(item, dict) and "include-group" in item:
            out.extend(_expand_group(groups, item["include-group"], seen))
    return out


def declared_requirements(pyproject: dict, extras: list[str]) -> list[str] | None:
    """Static requirements of the project plus the requested extras / dependency groups.

    Returns None when they cannot be determined statically (no [project] table, or
    dependencies declared as dynamic).
    """
    project = pyproject.get("project")
    if not isinstance(project, dict) or "dependencies" in project.get("dynamic", []):
        return None
    own_name = _normalize(str(project.get("name", "")))
    optional = project.get("optional-dependencies", {}) or {}
    groups = pyproject.get("dependency-groups", {}) or {}

    reqs: list[str] = []
    pending = list(project.get("dependencies", []) or [])
    wanted_extras = list(extras)
    done_extras: set[str] = set()
    while wanted_extras:
        extra = wanted_extras.pop(0)
        if extra in done_extras:
            continue
        done_extras.add(extra)
        pending += optional.get(extra, []) or []
        pending += _expand_group(groups, extra, set())
        # self-references such as `dev = ["ff-geo[test]"]` pull in more extras, not PyPI
        for req in list(pending):
            match = _NAME_RE.match(req)
            if match and own_name and _normalize(match.group(1)) == own_name:
                pending.remove(req)
                wanted_extras += [e.strip() for e in (match.group(2) or "").split(",") if e.strip()]
        reqs += pending
        pending = []
    reqs += [r for r in pending if r not in reqs]

    seen: set[str] = set()
    unique = []
    for req in reqs:
        key = req.strip()
        if key and key not in seen:
            seen.add(key)
            unique.append(key)
    return unique


def pip(args: list[str], dry_run: bool) -> int:
    cmd = [sys.executable, "-m", "pip", "install", *args]
    print("+ " + " ".join(cmd), flush=True)
    if dry_run:
        return 0
    return subprocess.call(cmd)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("service_dir", type=Path, help="directory containing pyproject.toml")
    parser.add_argument("--editable", "-e", action="store_true", help="pip install -e")
    parser.add_argument(
        "--extras",
        default="",
        help="comma-separated extras / dependency groups to include, e.g. dev,test",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--deps-only", action="store_true", help="install only the declared requirements"
    )
    mode.add_argument(
        "--no-deps",
        action="store_true",
        help="install only the package (deps are installed anyway if not declared statically)",
    )
    parser.add_argument(
        "--best-effort",
        action="store_true",
        help="never fail: a broken package install is reported and ignored",
    )
    parser.add_argument(
        "--extra-packages",
        default="",
        help="whitespace-separated extra requirements to install alongside",
    )
    parser.add_argument("--dry-run", action="store_true", help="print pip commands only")
    args = parser.parse_args(argv)

    service_dir: Path = args.service_dir
    pyproject_file = service_dir / "pyproject.toml"
    if not pyproject_file.is_file():
        print(f"error: {pyproject_file} not found", file=sys.stderr)
        return 2
    try:
        with pyproject_file.open("rb") as fh:
            pyproject = tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        print(f"error: {pyproject_file} is not valid TOML: {exc}", file=sys.stderr)
        return 2

    extras = [e.strip() for e in args.extras.split(",") if e.strip()]
    extra_packages = args.extra_packages.split()
    requirements = declared_requirements(pyproject, extras)

    if args.deps_only:
        if requirements is None:
            print(
                f"note: {pyproject_file} has no static [project].dependencies; "
                "they will be installed together with the package",
                flush=True,
            )
            requirements = []
        to_install = requirements + extra_packages
        if not to_install:
            print("nothing to install", flush=True)
            return 0
        return 1 if pip(to_install, args.dry_run) else 0

    # Install the package itself.
    target = str(service_dir)
    known_extras = [
        e for e in extras if e in (pyproject.get("project", {}).get("optional-dependencies") or {})
    ]
    if known_extras:
        target += "[" + ",".join(known_extras) + "]"
    package_args = (["-e"] if args.editable else []) + [target]
    if args.no_deps and requirements is not None:
        package_args = ["--no-deps", *package_args]
    if pip(package_args + extra_packages, args.dry_run) == 0:
        # Dependency groups (PEP 735) are not installed by `pip install <dir>`; add them.
        groups = pyproject.get("dependency-groups", {}) or {}
        group_reqs = [r for e in extras for r in _expand_group(groups, e, set())]
        if group_reqs and not args.no_deps:
            return 1 if pip(group_reqs, args.dry_run) else 0
        return 0

    if args.best_effort:
        print(
            f"warning: could not install {service_dir} as a package; "
            "continuing (the code runs from src/ via PYTHONPATH)",
            file=sys.stderr,
        )
        return 0
    if requirements is None:
        print(
            "error: package install failed and the dependencies are not declared statically",
            file=sys.stderr,
        )
        return 1
    print(
        f"warning: package install of {service_dir} failed; "
        "falling back to the dependencies listed in pyproject.toml",
        file=sys.stderr,
        flush=True,
    )
    to_install = requirements + extra_packages
    if not to_install:
        return 0
    return 1 if pip(to_install, args.dry_run) else 0


if __name__ == "__main__":
    sys.exit(main())
