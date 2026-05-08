#!/bin/bash
# MoveWriter XOVI autostart — runs on boot from /usr/lib/systemd/system/movewriter-xovi.service.
#
# Safe by design: no [Unit] deps. If /home never mounts, script exits silently and
# stock xochitl keeps running. Do NOT add Requires=home.mount to the unit file —
# that caused a factory reset on 3.22.

LOGFILE=/home/root/.movewriter/xovi-autostart.log

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOGFILE" 2>/dev/null || true
}

# Poll for /home/root/xovi — /home is an encrypted volume that mounts after xochitl starts.
i=0
while [ $i -lt 20 ]; do
    if [ -d /home/root/xovi ]; then
        break
    fi
    sleep 1
    i=$((i + 1))
done

if [ ! -d /home/root/xovi ]; then
    # /home never mounted — stock xochitl will keep running, exit silently.
    exit 0
fi

mkdir -p /home/root/.movewriter 2>/dev/null || true
log "autostart: found /home/root/xovi"

# Entware's /opt has glibc 2.27 which shadows the system glibc 2.39.
# XOVI's xovi.so preload breaks if /opt is mounted (wrong glibc gets loaded first).
if mountpoint -q /opt 2>/dev/null; then
    umount /opt 2>/dev/null && log "autostart: unmounted /opt"
fi

# Activate XOVI — creates tmpfs overlays in /etc/systemd/system/xochitl.service.d/
# and restarts xochitl with LD_PRELOAD=xovi.so.
#
# Do NOT stop xochitl before this call.  /home mounts right after the user
# enters their PIN, so if we stop xochitl here the screen goes dark the instant
# PIN is accepted — it looks like a freeze.  xovi/start handles the restart
# internally (systemctl restart xochitl), so a pre-stop is not needed.
#
# IMPORTANT: do NOT export XOVI_ROOT here.  xovi/start sets it internally to the
# correct per-service exthome path.  Pre-setting it to the XOVI install root
# (/home/root/xovi) causes xovi/start to skip its own assignment and xochitl
# inherits the wrong path — qt-resource-rebuilder can't find the hashtable,
# AppLoad can't inject its menu entry, and the hamburger menu is empty after reboot.
log "autostart: running xovi/start"
bash /home/root/xovi/start >> "$LOGFILE" 2>&1 || log "autostart: xovi/start exited non-zero"
sleep 5

# Safety net: if xochitl is not running after xovi/start (script failed or
# produced no restart), bring it up unconditionally so the device is never
# left with a dead UI.
if ! pidof xochitl > /dev/null 2>&1; then
    log "autostart: xochitl not running after xovi/start — starting directly"
    systemctl start xochitl 2>/dev/null || true
    sleep 3
fi

# Remount /opt so entware is available for the native app backend.
mount -a 2>/dev/null && log "autostart: remounted filesystems"

log "autostart: done"
exit 0
