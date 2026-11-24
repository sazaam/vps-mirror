#!/bin/sh
# vpsclone bootstrap - run on a FRESH Ubuntu box as root.
#
#   ./bootstrap.sh                    # uses the extracted bundle in $PWD
#   VPS_MIRROR_REPO=git@... ./bootstrap.sh   # clones the private repo instead
#
# No external image/transfer service. Needs only apt + network (or a scp'd bundle).
set -eu

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
log() { printf '[bootstrap] %s\n' "$*"; }
backup_existing() {
  target=$1
  if [ -e "$target" ]; then
    bak="${target}.bak.$(date +%Y%m%d-%H%M%S)"
    mv -- "$target" "$bak"
    log "moved existing $target -> $bak"
  fi
}

if [ "$(id -u)" -ne 0 ]; then
  echo "run as root: sudo ./bootstrap.sh" >&2
  exit 1
fi

log "installing minimal prerequisites"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 git rsync ca-certificates curl openssh-server >/dev/null

TARGET=/opt/vps-mirror
if [ -n "${VPS_MIRROR_REPO:-}" ]; then
  safe_repo=$(printf '%s' "$VPS_MIRROR_REPO" | sed -E 's#(://)[^/@]+@#\1<redacted>@#')
  log "cloning $safe_repo -> $TARGET"
  if [ "$HERE" = "$TARGET" ]; then
    echo "refusing to replace the checkout bootstrap.sh is running from" >&2
    exit 1
  fi
  if [ -d "$TARGET/.git" ]; then
    log "updating existing checkout with git pull --ff-only"
    git -C "$TARGET" pull --ff-only
  else
    backup_existing "$TARGET"
    mkdir -p "$(dirname "$TARGET")"
    git clone -- "$VPS_MIRROR_REPO" "$TARGET"
  fi
else
  log "using bundle at $HERE"
  if [ "$HERE" != "$TARGET" ]; then
    backup_existing "$TARGET"
    mkdir -p "$(dirname "$TARGET")"
    cp -a -- "$HERE" "$TARGET"
  else
    log "already running from $TARGET; keeping the existing checkout"
  fi
fi

cd "$TARGET"
chmod +x vpsclone hooks/*.sh 2>/dev/null || true

# Machine-specific data lives outside the repo, owned by the human who ran
# sudo (or by root when there is no SUDO_USER).
DATA_USER=${SUDO_USER:-$(id -un)}
DATA_HOME=$(getent passwd "$DATA_USER" | cut -d: -f6)
[ -n "$DATA_HOME" ] || DATA_HOME="$HOME"
DATA_DIR="$DATA_HOME/.vps-data"
BUNDLE_DATA=$(CDPATH= cd -- "$(dirname -- "$HERE")" && pwd)/vps-mirror-data
if [ -d "$BUNDLE_DATA" ]; then
  log "installing data -> $DATA_DIR (owner $DATA_USER)"
  mkdir -p -- "$DATA_DIR"
  cp -a -- "$BUNDLE_DATA/." "$DATA_DIR/"
  chown -R "$DATA_USER:" "$DATA_DIR" || true
else
  log "no bundled data; using existing $DATA_DIR"
fi

log "running preflight"
python3 vpsclone doctor

log "applying baseline"
python3 vpsclone apply "$@"

log "done. On your LOCAL machine run:"
log "  python3 vpsclone keygen --target <user>@<this-host>"
log "then add the printed pubkey to GitHub and run:"
log "  python3 vpsclone apply --only=repos"
