#!/usr/bin/env bash
# The QML half of the suite.
#
# qmltestrunner ships with qt6-declarative and is not on PATH; it lives in the
# Qt bindir, which is why this project spent a long time believing QML could
# not be tested here at all. It can.
#
# Offscreen so it needs no compositor and can run anywhere.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
runner=/usr/lib/qt6/bin/qmltestrunner
[[ -x "$runner" ]] || { echo "qmltestrunner not found at $runner (pacman -S qt6-declarative)" >&2; exit 1; }
QT_QPA_PLATFORM=offscreen exec "$runner" -input "$here/qml" "$@"
