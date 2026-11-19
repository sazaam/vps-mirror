#!/bin/sh
# Runs before the first apply step. Exit non-zero to abort the apply.
# Add your own preconditions here, e.g. assert you have out-of-band console access.
echo "[pre-apply] baseline replay starting on $(hostname) - $(date -Is)"
