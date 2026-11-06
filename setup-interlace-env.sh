#!/usr/bin/env bash
# Thin wrapper: all logic lives in interlace_setup.py (unit-tested, supports --dry-run).
# Usage: ./setup-interlace-env.sh [--dry-run] [--gpu-profile P] [--adapter-mode M]
#        [--edid FILE] [--connector NAME|auto] [--live-only] [--no-desktop-env]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$SCRIPT_DIR/interlace_setup.py" "$@"
