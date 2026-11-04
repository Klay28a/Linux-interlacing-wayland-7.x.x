#!/usr/bin/env bash
# One-Click Installer Wrapper for Linux CRT Interlacing Suite
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "$SCRIPT_DIR/install-interlace-suite.sh" "$@"
