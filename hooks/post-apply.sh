#!/bin/sh
# Runs after all apply steps, before verify.
# Good place to reload anything custom or pick up a newly added deploy key.
echo "[post-apply] baseline replay finished on $(hostname)"
