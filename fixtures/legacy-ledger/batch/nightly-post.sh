#!/usr/bin/env bash
# Cron entrypoint for the nightly ledger batch.
# Schedule: 0 2 * * *   (02:00 daily)
set -euo pipefail

BUILD_DIR="$(dirname "$0")/../build"
"$BUILD_DIR/ledger"
