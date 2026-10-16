#!/usr/bin/env bash
# Opt-in: applies the Google Services Gradle plugin to the generated android/ folder.
# Requires android/app/google-services.json to exist. Idempotent.
# Usage: ci_enable_firebase.sh [project_dir]   (default: apps/mobile)
set -euo pipefail
DIR="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
cd "$DIR/android"
[ -f app/google-services.json ] || { echo "missing android/app/google-services.json" >&2; exit 1; }
python3 - <<'PY'
import os, re
VER = "4.4.2"
def patch(path, fn):
    s = open(path, encoding="utf-8").read()
    if "com.google.gms.google-services" in s:
        return
    n = fn(s)
    if n == s:
        raise SystemExit(f"could not patch {path}; apply the plugin manually (docs/FIREBASE_SETUP.md)")
    open(path, "w", encoding="utf-8").write(n)
kts = os.path.exists("settings.gradle.kts")
if kts:
    patch("settings.gradle.kts", lambda s: re.sub(r"(plugins\s*\{\n)", lambda m: m.group(1) + f'    id("com.google.gms.google-services") version "{VER}" apply false\n', s, count=1))
    patch("app/build.gradle.kts", lambda s: re.sub(r"(plugins\s*\{\n)", lambda m: m.group(1) + '    id("com.google.gms.google-services")\n', s, count=1))
else:
    patch("settings.gradle", lambda s: re.sub(r"(plugins\s*\{\n)", lambda m: m.group(1) + f'    id "com.google.gms.google-services" version "{VER}" apply false\n', s, count=1))
    patch("app/build.gradle", lambda s: re.sub(r"(plugins\s*\{\n)", lambda m: m.group(1) + '    id "com.google.gms.google-services"\n', s, count=1))
print("google-services plugin applied")
PY
