#!/bin/zsh
# Build both images at 2.5.0, package the ZIP, verify it really contains them.
set -e; export PATH=/opt/homebrew/bin:$PATH
cd "$(cd "$(dirname "$0")/.." && pwd)"
echo "[$(date '+%H:%M')] arm64"; docker buildx build --platform linux/arm64 -t timesheet-app:2.5.0-arm64 --load -f Dockerfile . > data/build_arm64_v33.log 2>&1
echo "[$(date '+%H:%M')] amd64"; docker buildx build --platform linux/amd64 -t timesheet-app:2.5.0-amd64 --load -f Dockerfile . > data/build_amd64_v33.log 2>&1
for a in arm64 amd64; do n=$(docker run --rm --platform linux/$a timesheet-app:2.5.0-$a sh -c 'find / -name "PP-OCRv6*.onnx" 2>/dev/null | wc -l'); echo "  $a: $n OCR models baked"; [ "$n" -ge 2 ] || { echo "  $a image missing models"; exit 1; }; done
echo "[$(date '+%H:%M')] package"; ./.venv/bin/python tools/package_release.py 2.5.0 | tail -4
Z=dist/timesheet-app-v2.5.0-deployment.zip; S=$(stat -f %z $Z); echo "  zip $((S/1048576)) MB"; [ $S -gt 400000000 ] || { echo "  ZIP too small -- images missing"; exit 1; }
unzip -l $Z | grep -E "tar.gz" ; echo "[$(date '+%H:%M')] release ok"
