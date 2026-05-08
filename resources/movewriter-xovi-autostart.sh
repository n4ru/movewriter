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

# Stop xochitl before calling xovi/start.  If xochitl is already running when
# xovi/start is called, its internal "systemctl start xochitl" is a no-op and
# xochitl keeps running without XOVI — AppLoad never appears in the menu.
# Stopping first ensures xovi/start does a fresh xochitl launch with XOVI loaded.
log "autostart: stopping xochitl for XOVI reload"
systemctl stop xochitl 2>/dev/null || true
sleep 2
kill $(pidof xochitl) 2>/dev/null || true

# Activate XOVI — creates tmpfs overlays in /etc/systemd/system/xochitl.service.d/
# and starts xochitl with LD_PRELOAD=xovi.so.
#
# IMPORTANT: do NOT export XOVI_ROOT here.  xovi/start sets it internally to the
# correct per-service exthome path.  If we pre-set XOVI_ROOT to the XOVI install
# root (/home/root/xovi), xovi/start skips its own assignment and xochitl inherits
# the wrong path — qt-resource-rebuilder can't find the hashtable, AppLoad can't
# inject its menu entry, and the hamburger menu is empty after reboot.
log "autostart: running xovi/start"
bash /home/root/xovi/start >> "$LOGFILE" 2>&1 || log "autostart: xovi/start exited non-zero"
sleep 5

# Remount /opt so entware is available for the native app backend.
mount -a 2>/dev/null && log "autostart: remounted filesystems"

log "autostart: done"
exit 0
