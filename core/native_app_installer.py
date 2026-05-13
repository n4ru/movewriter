"""Install/uninstall MoveWriter Native (on-device app) via SSH.

Deploys XOVI + AppLoad + MoveWriter native app to the Move, plus a
persistent systemd drop-in that disables xochitl's watchdog (prevents
reboots during BT operations).

Source files for the native app live in the `nativeapp/` subfolder of
this repo (single source of truth). `native_app_root()` returns either
the in-repo path (running from source) or the PyInstaller bundle path
(running from a built binary).
"""
import os
import sys

# Paths on-device
DEST_DIR = "/home/root/xovi/services/xochitl.service/exthome/appload/movewriter"
XOVI_DIR = "/home/root/xovi"
APPLOAD_DIR = "/home/root/xovi/extensions.d/appload"  # legacy constant
APPLOAD_SO_PATH = "/home/root/xovi/extensions.d/appload.so"
APPLOAD_SHIMS_DIR = "/home/root/shims"
APPLOAD_GITHUB_URL = "https://github.com/asivery/rm-appload/releases/latest/download/appload-aarch64.zip"

# XOVI per-service paths — xovi/start sets XOVI_ROOT to the per-service path.
# The per-service qt-resource-rebuilder dir is symlinked to the global one so
# all qmd patches and the hashtab are visible in both debug and systemd modes.
XOVI_PER_SERVICE_EXT_DIR = "/home/root/xovi/services/xochitl.service/extensions.d"
GLOBAL_HASHTAB = "/home/root/xovi/exthome/qt-resource-rebuilder/hashtab"
WATCHDOG_DROPIN_DIR = "/usr/lib/systemd/system/xochitl.service.d"
WATCHDOG_DROPIN_PATH = f"{WATCHDOG_DROPIN_DIR}/zz-movewriter-overrides.conf"
AUTOSTART_SERVICE_PATH = "/usr/lib/systemd/system/movewriter-xovi.service"
AUTOSTART_SYMLINK_PATH = "/usr/lib/systemd/system/multi-user.target.wants/movewriter-xovi.service"
AUTOSTART_SCRIPT_PATH = "/usr/lib/movewriter-xovi-autostart.sh"
EMERGENCY_DROPIN_DIR = "/usr/lib/systemd/system/rm-emergency.service.d"
EMERGENCY_DROPIN_PATH = f"{EMERGENCY_DROPIN_DIR}/zz-movewriter.conf"

# App layout (mirrors nativeapp/ subfolder structure)
APP_FILES = {
    "": ["manifest.json", "resources.rcc"],
    "backend": [
        "entry", "__init__.py", "main.py", "protocol.py", "bluetooth.py",
        "service.py", "layout_patcher.py", "config.py",
    ],
    "qml": [
        "main.qml", "KeyboardSection.qml", "ServiceSection.qml",
        "PasskeyOverlay.qml", "application.qrc",
    ],
    "qml/components": [
        "ActionButton.qml", "Card.qml", "DeviceList.qml", "StatusDot.qml",
    ],
    "tools": ["__init__.py", "generate_qmap.py"],
    "resources": ["bt-keyboard.sh", "remarkable-bt-keyboard.service"],
}


def native_app_root():
    """Locate the native app source tree."""
    # Source checkout: nativeapp/ subfolder of this repo
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    in_repo = os.path.join(here, "nativeapp")
    if os.path.isdir(in_repo):
        return in_repo

    # PyInstaller bundle: stages the same nativeapp/ directory
    if getattr(sys, "_MEIPASS", None):
        bundled = os.path.join(sys._MEIPASS, "nativeapp")
        if os.path.isdir(bundled):
            return bundled

    raise RuntimeError(
        "Cannot locate MoveWriter native app source. "
        "Expected at nativeapp/ alongside core/."
    )


def _resources_dir():
    return os.path.join(os.path.dirname(os.path.dirname(__file__)), "resources")


def is_installed(ssh):
    """Check whether the native app is installed on the device."""
    try:
        _, _, code = ssh.exec(f"test -d {DEST_DIR}", timeout=5)
        return code == 0
    except Exception:
        return False


def install(ssh, status_cb=None):
    """Install XOVI + AppLoad + MoveWriter native app + watchdog drop-in.

    status_cb(msg) is called with progress messages.
    """
    def say(msg):
        if status_cb:
            status_cb(msg)

    root = native_app_root()

    say("Checking prerequisites...")
    _ensure_entware(ssh, say)
    _ensure_python3(ssh, say)
    _ensure_vellum(ssh, say)
    _vellum_upgrade(ssh, say)
    _ensure_xovi(ssh, say)
    _ensure_appload(ssh, say)

    say("Uploading app files...")
    _upload_app(ssh, root)

    say("Installing crash protection...")
    _install_watchdog_dropin(ssh)
    _install_emergency_override(ssh)

    say("Setting up boot autostart...")
    _install_autostart(ssh)

    # Always rebuild hashtable — needed whenever AppLoad or xochitl changes,
    # and must be at both global and per-service paths since xovi/start sets
    # XOVI_ROOT to the per-service exthome.
    _activate_xovi(ssh, say)

    say("Install complete")


def uninstall(ssh, status_cb=None):
    """Remove MoveWriter native app and its watchdog drop-in.

    Leaves XOVI/AppLoad/Python in place (shared infrastructure).
    """
    def say(msg):
        if status_cb:
            status_cb(msg)

    say("Removing app files...")
    ssh.exec(f"rm -rf {DEST_DIR}", timeout=10)

    say("Removing crash protection...")
    _remove_watchdog_dropin(ssh)
    _remove_emergency_override(ssh)

    say("Removing boot autostart...")
    _remove_autostart(ssh)

    say("Restarting Move interface...")
    ssh.exec("(sleep 1 && systemctl restart xochitl) &", timeout=5)

    say("Uninstall complete")


# ── Prerequisite installers ───────────────────────────────────

def _ensure_entware(ssh, say):
    _, _, code = ssh.exec("command -v opkg || test -x /opt/bin/opkg", timeout=5)
    if code == 0:
        return
    say("Installing entware (package manager)...")
    ssh.exec(
        "wget --no-check-certificate -O- "
        "https://raw.githubusercontent.com/hmenzagh/rmpp-entware/main/rmpp_entware.sh "
        "| bash -s -- --force",
        timeout=180,
    )
    _, _, code = ssh.exec("test -x /opt/bin/opkg", timeout=5)
    if code != 0:
        raise RuntimeError("entware install failed")


def _ensure_python3(ssh, say):
    _, _, code = ssh.exec("test -x /opt/bin/python3", timeout=5)
    if code == 0:
        return
    say("Installing Python 3...")
    ssh.exec(
        "export PATH=/opt/bin:/opt/sbin:$PATH && opkg update && opkg install python3",
        timeout=180,
    )
    _, _, code = ssh.exec("test -x /opt/bin/python3", timeout=5)
    if code != 0:
        raise RuntimeError("Python 3 install failed")


def _ensure_vellum(ssh, say):
    _, _, code = ssh.exec("command -v vellum", timeout=5)
    if code == 0:
        return
    say("Installing Vellum...")
    ssh.exec(
        "wget --no-check-certificate -O /tmp/bootstrap.sh "
        "https://github.com/vellum-dev/vellum-cli/releases/latest/download/bootstrap.sh "
        "&& bash /tmp/bootstrap.sh && rm -f /tmp/bootstrap.sh",
        timeout=120,
    )
    _, _, code = ssh.exec("command -v vellum", timeout=5)
    if code != 0:
        raise RuntimeError("Vellum install failed")


def _vellum_upgrade(ssh, say):
    """Run 'vellum upgrade' to sync packages to the current firmware.

    Required after an OS upgrade — Vellum blocks add/update until packages
    are re-synced. Can take several minutes on first run.

    Non-fatal: network errors or apk failures are logged but don't abort
    the install. If packages were installed in a prior attempt the
    subsequent ensure_* checks will find them and skip re-installation.
    """
    say("Syncing packages to firmware (may take a few minutes)...")
    out, err, code = ssh.exec("vellum upgrade 2>&1", timeout=360)
    combined = (out or "") + (err or "")
    if code != 0 and "already" not in combined.lower() and "up to date" not in combined.lower():
        # Non-fatal — apk/network errors here don't necessarily mean installed
        # packages are broken. Continue and let the ensure_* steps verify state.
        say("Warning: vellum upgrade returned non-zero — continuing anyway")


def _ensure_xovi(ssh, say):
    """Install/update XOVI and the qt-resource-rebuilder extension.

    XOVI is a community extension framework — it does NOT ship with the
    device, so on a fresh Move /home/root/xovi/ won't exist until we put it
    there.  `vellum add` is idempotent (no-op when already installed), so
    we don't bother checking first and just always run add+update for both
    packages.

    The `update` step is mandatory: xovi.so must match the running xochitl
    binary, and a stale 3.26 build will freeze xochitl on 3.27.  Targeted
    `vellum update <pkg>` is more reliable than the full `vellum upgrade`,
    which can fail on transient apk network errors.

    xovi-extensions provides qt-resource-rebuilder, which AppLoad needs to
    inject its hamburger-menu entry into xochitl.
    """
    say("Installing/updating XOVI for current firmware...")
    ssh.exec("vellum add xovi 2>&1 || true", timeout=180)
    ssh.exec("vellum update xovi 2>&1 || true", timeout=180)

    say("Installing/updating XOVI extensions...")
    ssh.exec("vellum add xovi-extensions 2>&1 || true", timeout=180)
    ssh.exec("vellum update xovi-extensions 2>&1 || true", timeout=180)

    # Verify XOVI actually landed.  We silenced vellum's exit codes above so
    # transient apk hiccups don't abort the install — this is the single
    # point where we catch a real failure (no network, broken vellum, etc).
    _, _, code = ssh.exec(f"test -d {XOVI_DIR}", timeout=5)
    if code != 0:
        raise RuntimeError(
            "XOVI install failed — /home/root/xovi missing after vellum add. "
            "Check network connectivity and that vellum is functional."
        )


def _appload_present(ssh):
    """Return True if AppLoad's extension .so is installed."""
    _, _, code = ssh.exec(f"test -f {APPLOAD_SO_PATH}", timeout=5)
    return code == 0


def _install_appload_direct(ssh, say):
    """Download AppLoad from GitHub and install it directly.

    Used when Vellum's OS compatibility gate blocks installation (e.g. 3.27
    before the Vellum package is updated). The zip contains appload.so and
    qtfb shim libraries; we place them exactly where Vellum would.
    """
    say("Installing AppLoad latest release from GitHub...")
    ssh.exec(f"mkdir -p /tmp/appload-dl {XOVI_DIR}/extensions.d {APPLOAD_SHIMS_DIR}", timeout=5)
    out, err, code = ssh.exec(
        f"wget --no-check-certificate -O /tmp/appload-dl/appload.zip '{APPLOAD_GITHUB_URL}'",
        timeout=120,
    )
    if code != 0:
        raise RuntimeError(f"AppLoad download failed: {(err or out or '').strip()}")
    out, err, code = ssh.exec(
        "cd /tmp/appload-dl && unzip -o appload.zip && "
        f"cp appload.so {APPLOAD_SO_PATH} && "
        f"cp qtfb-shim.so {APPLOAD_SHIMS_DIR}/qtfb-shim.so 2>/dev/null || true; "
        f"cp qtfb-shim-32bit.so {APPLOAD_SHIMS_DIR}/qtfb-shim-32bit.so 2>/dev/null || true; "
        "rm -rf /tmp/appload-dl",
        timeout=30,
    )
    if not _appload_present(ssh):
        raise RuntimeError(f"AppLoad direct install failed: {(err or out or '').strip()}")


def _ensure_appload(ssh, say):
    # Always update AppLoad — an installed-but-outdated binary (e.g. v0.5.1)
    # will crash on newer firmware even though the file exists.  Try vellum
    # first; fall back to the latest GitHub release every time.
    say("Updating AppLoad...")
    ssh.exec("vellum update 2>/dev/null || true", timeout=30)
    ssh.exec("vellum add appload 2>&1 || true", timeout=180)
    # Always pull latest from GitHub — overwrites whatever is installed so we
    # are guaranteed to have a firmware-compatible version.
    _install_appload_direct(ssh, say)

    # Mirror appload.so to the per-service extensions dir as well — xovi/start
    # may set XOVI_ROOT to the per-service path and load extensions from there.
    ssh.exec(
        f"mkdir -p {XOVI_PER_SERVICE_EXT_DIR} && "
        f"cp {APPLOAD_SO_PATH} {XOVI_PER_SERVICE_EXT_DIR}/appload.so 2>/dev/null || true",
        timeout=5,
    )


def _upload_app(ssh, root):
    """Upload all native app files to DEST_DIR."""
    # Create subdirectories
    subdirs = set(APP_FILES.keys()) - {""}
    for sub in sorted(subdirs):
        ssh.exec(f"mkdir -p {DEST_DIR}/{sub}", timeout=5)
    ssh.exec(f"mkdir -p {DEST_DIR}", timeout=5)

    for subdir, files in APP_FILES.items():
        for name in files:
            local = os.path.join(root, subdir, name) if subdir else os.path.join(root, name)
            remote = f"{DEST_DIR}/{subdir}/{name}" if subdir else f"{DEST_DIR}/{name}"
            if not os.path.isfile(local):
                # Optional files (e.g., resources.rcc before build, icon.png)
                if name in ("resources.rcc",):
                    raise RuntimeError(
                        f"Missing {local} -- run `./build.sh` in nativeapp/ first"
                    )
                continue
            with open(local, "rb") as f:
                data = f.read()
            # Normalize line endings for text files
            if name.endswith((".py", ".sh", ".qml", ".qrc", ".json", ".service"))\
               or name == "entry":
                data = data.replace(b"\r\n", b"\n")
            ssh.upload_bytes(data, remote)

    ssh.exec(f"chmod +x {DEST_DIR}/backend/entry", timeout=5)


def _activate_xovi(ssh, say):
    """Rebuild the XOVI hashtable then re-run xovi/start so AppLoad appears in the menu.

    The hashtable (built by qt-resource-rebuilder) maps xochitl's QML resource
    offsets so AppLoad can inject its hamburger-menu entry.  It must be rebuilt
    whenever AppLoad or xochitl changes.

    xovi/start sets XOVI_ROOT to the per-service path, so XOVI reads qmd patch
    files and the hashtable from there — NOT the global exthome.  We symlink the
    per-service qt-resource-rebuilder directory to the global one so all qmd files
    (installed by vellum for any extension) are automatically visible, and future
    extensions installed via reManager are picked up without re-running the installer.
    """
    XOVI_SO = "/home/root/xovi/xovi.so"
    GLOBAL_QRR_DIR = "/home/root/xovi/exthome/qt-resource-rebuilder"
    PER_SERVICE_QRR_DIR = "/home/root/xovi/services/xochitl.service/exthome/qt-resource-rebuilder"

    say("Rebuilding XOVI hashtable for AppLoad (~30-60s)...")
    # A background watchdog kills xochitl after 90s in case XOVI freezes it
    # (e.g. stale xovi.so on a newly upgraded firmware before vellum update
    # takes effect).  Without this the pipeline read blocks until ssh timeout.
    ssh.exec(
        "umount /opt 2>/dev/null; "
        "systemctl stop xochitl; sleep 2; "
        "kill $(pidof xochitl) 2>/dev/null || true; "
        f"mkdir -p {GLOBAL_QRR_DIR}; "
        f"rm -f {GLOBAL_HASHTAB}; "
        "(sleep 90 && kill $(pidof xochitl) 2>/dev/null) & WDOG=$!; "
        f"QMLDIFF_HASHTAB_CREATE={GLOBAL_HASHTAB} "
        "QML_DISABLE_DISK_CACHE=1 "
        f"LD_PRELOAD={XOVI_SO} "
        "/usr/bin/xochitl 2>&1 | "
        "while IFS= read line; do "
        "  echo \"$line\"; "
        f"  case \"$line\" in *'Hashtab saved'*) "
        "    kill $(pidof xochitl) 2>/dev/null; break;; "
        "  esac; "
        "done; "
        "kill $WDOG 2>/dev/null || true",
        timeout=120,
    )

    # Symlink the per-service qt-resource-rebuilder dir to the global one.
    # This makes all qmd extension patches visible to XOVI when running via
    # systemd (XOVI_ROOT points to the per-service path), and means any
    # extension the user later installs via reManager is picked up automatically.
    ssh.exec(
        f"rm -rf {PER_SERVICE_QRR_DIR} && "
        f"mkdir -p $(dirname {PER_SERVICE_QRR_DIR}) && "
        f"ln -sf {GLOBAL_QRR_DIR} {PER_SERVICE_QRR_DIR}",
        timeout=5,
    )

    # Launch xovi/start in the background — it restarts xochitl which may
    # prompt for a PIN, so we must not wait for it in the foreground or the
    # SSH session blocks indefinitely.  The autostart service handles any
    # failure on the next reboot via the pidof safety-net fallback.
    say("Activating XOVI — device will restart xochitl shortly...")
    ssh.exec(
        "umount /opt 2>/dev/null; "
        "nohup bash /home/root/xovi/start >/tmp/xovi-start.log 2>&1 & "
        "sleep 2; "
        "mount -a 2>/dev/null",
        timeout=15,
    )


def _install_watchdog_dropin(ssh):
    """Install the [Service]\\nWatchdogSec=0 drop-in on persistent rootfs.

    Safe: no [Unit] section. A [Unit] section with deps caused a factory
    reset before — only [Service] is allowed in this drop-in.
    """
    local = os.path.join(_resources_dir(), "xochitl-nowatchdog.conf")
    with open(local, "r") as f:
        content = f.read().replace("\r\n", "\n")

    # Sanity: a [Unit] section is allowed here ONLY to RESET inherited
    # values (e.g., OnFailure=, JobTimeoutSec=0). Never add cross-unit
    # dependencies — that's what caused the factory reset in the past.
    for forbidden in ("Requires=", "Wants=", "After=", "Before=", "BindsTo="):
        if forbidden in content:
            raise RuntimeError(
                f"Refusing to write xochitl drop-in containing '{forbidden}' "
                "(only blank-value resets allowed in [Unit])"
            )

    ssh.exec("mount -o remount,rw /", timeout=5)
    try:
        ssh.exec(f"mkdir -p {WATCHDOG_DROPIN_DIR}", timeout=5)
        ssh.upload_string(content, WATCHDOG_DROPIN_PATH)
    finally:
        ssh.exec("mount -o remount,ro /", timeout=5)

    ssh.exec("systemctl daemon-reload", timeout=10)


def _remove_watchdog_dropin(ssh):
    ssh.exec("mount -o remount,rw /", timeout=5)
    try:
        ssh.exec(f"rm -f {WATCHDOG_DROPIN_PATH}", timeout=5)
        ssh.exec(f"rmdir {WATCHDOG_DROPIN_DIR} 2>/dev/null || true", timeout=5)
    finally:
        ssh.exec("mount -o remount,ro /", timeout=5)
    ssh.exec("systemctl daemon-reload", timeout=10)


def _install_emergency_override(ssh):
    """Override rm-emergency.service so it doesn't reboot on xochitl hangs.

    The OTA swu_applied=1 path is preserved (that reboot is needed for
    partition swap). For all other emergencies, we just log and do nothing.
    """
    local = os.path.join(_resources_dir(), "rm-emergency-override.conf")
    with open(local, "r") as f:
        content = f.read().replace("\r\n", "\n")

    for forbidden in ("Requires=", "Wants=", "After=", "Before=", "BindsTo="):
        if forbidden in content:
            raise RuntimeError(
                f"Refusing rm-emergency override containing '{forbidden}'"
            )

    ssh.exec("mount -o remount,rw /", timeout=5)
    try:
        ssh.exec(f"mkdir -p {EMERGENCY_DROPIN_DIR}", timeout=5)
        ssh.upload_string(content, EMERGENCY_DROPIN_PATH)
    finally:
        ssh.exec("mount -o remount,ro /", timeout=5)
    ssh.exec("systemctl daemon-reload", timeout=10)


def _remove_emergency_override(ssh):
    ssh.exec("mount -o remount,rw /", timeout=5)
    try:
        ssh.exec(f"rm -f {EMERGENCY_DROPIN_PATH}", timeout=5)
        ssh.exec(f"rmdir {EMERGENCY_DROPIN_DIR} 2>/dev/null || true", timeout=5)
    finally:
        ssh.exec("mount -o remount,ro /", timeout=5)
    ssh.exec("systemctl daemon-reload", timeout=10)


def _install_autostart(ssh):
    """Install XOVI autostart service so MoveWriter survives reboots."""
    script_local = os.path.join(_resources_dir(), "movewriter-xovi-autostart.sh")
    service_local = os.path.join(_resources_dir(), "movewriter-xovi.service")

    with open(script_local, "r") as f:
        script = f.read().replace("\r\n", "\n")
    with open(service_local, "r") as f:
        service = f.read().replace("\r\n", "\n")

    # Sanity: no forbidden [Unit] deps in our service file. We allow [Unit]
    # with just Description, but never After/Requires/Wants (caused factory reset).
    for forbidden in ("Requires=", "Wants=", "After=", "Before=", "BindsTo="):
        if forbidden in service:
            raise RuntimeError(
                f"Refusing to write autostart service with '{forbidden}' "
                "in persistent rootfs"
            )

    ssh.exec("mount -o remount,rw /", timeout=5)
    try:
        ssh.upload_string(script, AUTOSTART_SCRIPT_PATH)
        ssh.exec(f"chmod +x {AUTOSTART_SCRIPT_PATH}", timeout=5)
        ssh.upload_string(service, AUTOSTART_SERVICE_PATH)
        ssh.exec(
            "mkdir -p /usr/lib/systemd/system/multi-user.target.wants",
            timeout=5,
        )
        ssh.exec(
            f"ln -sf {AUTOSTART_SERVICE_PATH} {AUTOSTART_SYMLINK_PATH}",
            timeout=5,
        )
    finally:
        ssh.exec("mount -o remount,ro /", timeout=5)

    ssh.exec("systemctl daemon-reload", timeout=10)


def _remove_autostart(ssh):
    ssh.exec("mount -o remount,rw /", timeout=5)
    try:
        ssh.exec(f"rm -f {AUTOSTART_SCRIPT_PATH}", timeout=5)
        ssh.exec(f"rm -f {AUTOSTART_SERVICE_PATH}", timeout=5)
        ssh.exec(f"rm -f {AUTOSTART_SYMLINK_PATH}", timeout=5)
    finally:
        ssh.exec("mount -o remount,ro /", timeout=5)
    ssh.exec("systemctl daemon-reload", timeout=10)
