#!/usr/bin/env bash
# Builds the Lambda deployment package: Pulse plus its dependencies, compiled for Lambda's
# Linux arm64 (Amazon Linux 2023, glibc 2.34) / Python 3.14 runtime, zipped to infra/build/pulse.zip.
set -euo pipefail
cd "$(dirname "$0")/.."

out=infra/build
rm -rf "$out" && mkdir -p "$out/package"

uv export --frozen --no-dev --no-hashes --no-emit-project --no-header > "$out/requirements.txt"
uv pip install --quiet -r "$out/requirements.txt" --target "$out/package" \
  --python-platform aarch64-manylinux_2_34 --python-version 3.14 --only-binary :all:
cp -R src/pulse "$out/package/"
find "$out/package" -name "__pycache__" -type d -prune -exec rm -rf {} +

(cd "$out/package" && zip -qr ../pulse.zip .)
echo "Built $out/pulse.zip ($(du -h "$out/pulse.zip" | cut -f1))"
