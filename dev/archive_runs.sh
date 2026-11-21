#!/usr/bin/env bash
# Archive finished lilguy run directories to the second disk and leave symlinks behind.
# Copies, verifies byte-for-byte, then removes the original and links it. Stops on any error.
set -euo pipefail
cd /home/ivy/Work/lilguy/reports/factory
ARCHIVE=/run/media/ivy/471dc9dc-5f5f-449d-a55b-81be8c470111/home/ivy/lilguy-artifacts/reports-factory
mkdir -p "$ARCHIVE"
for dir in pilot-2u67f8ec pilot-xif8k6a9 pilot-zm8ou4p3 pilot-_jk0eppk pilot-v1-H4n5xk pilot-v1-TqsV2q pilot-v1-k0k3fQ family-screen-yKd2kp; do
    [ -L "$dir" ] && { echo "$dir already archived"; continue; }
    [ -d "$dir" ] || { echo "missing $dir"; exit 1; }
    [ -e "$ARCHIVE/$dir" ] && { echo "refusing: $ARCHIVE/$dir exists"; exit 1; }
    cp -a "$dir" "$ARCHIVE/$dir"
    diff -rq --no-dereference "$dir" "$ARCHIVE/$dir"
    rm -rf "$dir"
    ln -s "$ARCHIVE/$dir" "$dir"
    echo "archived $dir"
done
df -h / | tail -1
