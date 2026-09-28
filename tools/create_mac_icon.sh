#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p build/FreeP2P.iconset
for n in 16 32 128 256 512; do
  sips -z "$n" "$n" assets/icon.png --out "build/FreeP2P.iconset/icon_${n}x${n}.png" >/dev/null
  double=$((n * 2))
  sips -z "$double" "$double" assets/icon.png --out "build/FreeP2P.iconset/icon_${n}x${n}@2x.png" >/dev/null
done
iconutil -c icns build/FreeP2P.iconset -o assets/icon.icns
