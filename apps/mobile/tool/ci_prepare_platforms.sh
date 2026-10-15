#!/usr/bin/env bash
# Patches the android/ and ios/ folders produced by `flutter create` (they are not checked in).
# Idempotent. Run from anywhere: bash apps/mobile/tool/ci_prepare_platforms.sh
# Usage: ci_prepare_platforms.sh [project_dir]   (default: apps/mobile relative to this script)
set -euo pipefail

DIR="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
cd "$DIR"

if [ ! -d android ] || [ ! -d ios ]; then
  flutter create . --platforms=android,ios --org com.factoryfinder --project-name factory_finder
fi

python3 - "$DIR" <<'PY'
import os, plistlib, re, sys

root = sys.argv[1]
LABEL = "مُوَرِّد / Factory Finder"

# ---------------------------------------------------------------- Android
main = os.path.join(root, "android/app/src/main/AndroidManifest.xml")
with open(main, encoding="utf-8") as f:
    m = f.read()

perms = [
    '<uses-permission android:name="android.permission.INTERNET"/>',
    '<uses-permission android:name="android.permission.CAMERA"/>',
    # Android 13+ photo picker access; older versions use READ_EXTERNAL_STORAGE (capped at SDK 32).
    '<uses-permission android:name="android.permission.READ_MEDIA_IMAGES"/>',
    '<uses-permission android:name="android.permission.READ_EXTERNAL_STORAGE" android:maxSdkVersion="32"/>',
    # Camera is optional so devices without one can still install.
    '<uses-feature android:name="android.hardware.camera" android:required="false"/>',
]
block = ""
for p in perms:
    name = re.search(r'android:name="([^"]+)"', p).group(1)
    if name not in m:
        block += "    " + p + "\n"
if block:
    m = re.sub(r"(<manifest[^>]*>\n?)", lambda x: x.group(1) + block, m, count=1)

# App label (Arabic / English).
m = re.sub(r'(<application[^>]*?android:label=")[^"]*(")', lambda x: x.group(1) + LABEL + x.group(2), m, count=1, flags=re.S)

# Cleartext HTTP must never be enabled in release: drop it from main if present.
m = re.sub(r'\s+android:usesCleartextTraffic="[^"]*"', "", m)
with open(main, "w", encoding="utf-8") as f:
    f.write(m)

# Debug-only cleartext (local gateway at http://10.0.2.2:8000).
dbg = os.path.join(root, "android/app/src/debug/AndroidManifest.xml")
if os.path.exists(dbg):
    with open(dbg, encoding="utf-8") as f:
        d = f.read()
    if "usesCleartextTraffic" not in d:
        if "<application" in d:
            d = d.replace("<application", '<application android:usesCleartextTraffic="true"', 1)
        else:
            d = d.replace("</manifest>", '    <application android:usesCleartextTraffic="true"/>\n</manifest>', 1)
        with open(dbg, "w", encoding="utf-8") as f:
            f.write(d)

# ---------------------------------------------------------------- iOS
plist_path = os.path.join(root, "ios/Runner/Info.plist")
with open(plist_path, "rb") as f:
    pl = plistlib.load(f)

pl["NSPhotoLibraryUsageDescription"] = (
    "يحتاج التطبيق إلى مكتبة الصور لإرفاق صور المنتجات والوثائق. / "
    "Factory Finder needs access to your photo library to attach product photos and documents."
)
pl["NSCameraUsageDescription"] = (
    "يحتاج التطبيق إلى الكاميرا لالتقاط صور المنتجات والوثائق. / "
    "Factory Finder needs the camera to take photos of products and documents."
)
pl["CFBundleDisplayName"] = LABEL
pl["CFBundleLocalizations"] = ["ar", "en"]
# NSAppTransportSecurity is intentionally left untouched (HTTPS only).
ats = pl.get("NSAppTransportSecurity", {})
if ats.get("NSAllowsArbitraryLoads"):
    print("WARNING: NSAllowsArbitraryLoads is set; remove it before release.", file=sys.stderr)

with open(plist_path, "wb") as f:
    plistlib.dump(pl, f)

print("platform folders prepared")
PY
