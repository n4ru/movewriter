#!/bin/sh
# MoveWriter Native — Full setup & deploy to reMarkable Move
# Usage: ./setup.sh [device_ip]
#
# This script:
#   1. Checks SSH connectivity
#   2. Installs rmpp-entware (opkg) if missing
#   3. Installs Python 3 via opkg if missing
#   4. Installs Vellum if missing
#   5. Installs XOVI via Vellum if missing
#   6. Installs AppLoad extension if missing
#   7. Deploys MoveWriter app files
#
# Prerequisites: SSH access to the Move (USB cable, password auth)
set -e

DEVICE="${1:-10.11.99.1}"
DEST="/home/root/xovi/services/xochitl.service/exthome/appload/movewriter"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Colors for terminal output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

info()  { printf "${GREEN}[✓]${NC} %s\n" "$1"; }
warn()  { printf "${YELLOW}[!]${NC} %s\n" "$1"; }
fail()  { printf "${RED}[✗]${NC} %s\n" "$1"; exit 1; }
step()  { printf "\n${GREEN}──── %s ────${NC}\n" "$1"; }

# ── Step 1: Check SSH connectivity ──────────────────────────
step "Checking SSH connection to $DEVICE"

if ! ssh -o ConnectTimeout=5 -o BatchMode=yes root@"$DEVICE" "echo ok" >/dev/null 2>&1; then
    # Try with password prompt
    echo "Connect your Move via USB and enter the SSH password."
    echo "  (Find it on the Move: Settings → General → Help → Copyrights and licenses)"
    echo ""
    if ! ssh -o ConnectTimeout=5 root@"$DEVICE" "echo ok" >/dev/null 2>&1; then
        fail "Cannot connect to $DEVICE. Is the Move plugged in via USB?"
    fi
fi
info "SSH connection OK"

# Helper to run commands on device
run_on_device() {
    ssh root@"$DEVICE" "$@"
}

# ── Step 2: Install rmpp-entware (opkg) if missing ─────────
step "Checking for opkg (package manager)"

if run_on_device "command -v opkg" >/dev/null 2>&1; then
    info "opkg already installed"
else
    warn "opkg not found — installing rmpp-entware..."
    run_on_device "wget --no-check-certificate -O- https://raw.githubusercontent.com/hmenzagh/rmpp-entware/main/rmpp_entware.sh | bash -s -- --force"
    # opkg is in /opt/bin — add to PATH for subsequent commands
    if run_on_device "/opt/bin/opkg --version" >/dev/null 2>&1; then
        info "opkg installed successfully"
    else
        fail "opkg installation failed. Try manually: ssh root@$DEVICE then run the install command from https://github.com/hmenzagh/rmpp-entware"
    fi
fi

# ── Step 3: Install Python 3 if missing ────────────────────
step "Checking for Python 3"

if run_on_device "command -v python3 || test -x /opt/bin/python3" >/dev/null 2>&1; then
    info "Python 3 already installed"
else
    warn "Python 3 not found — installing via opkg..."
    run_on_device "export PATH=/opt/bin:/opt/sbin:\$PATH && opkg update && opkg install python3"
    if run_on_device "test -x /opt/bin/python3" >/dev/null 2>&1; then
        info "Python 3 installed successfully"
    else
        fail "Python 3 installation failed"
    fi
fi

# ── Step 4: Install Vellum if missing ──────────────────────
step "Checking for Vellum"

if run_on_device "command -v vellum" >/dev/null 2>&1; then
    info "Vellum already installed"
else
    warn "Vellum not found — installing..."
    run_on_device "wget --no-check-certificate -O /tmp/bootstrap.sh https://github.com/vellum-dev/vellum-cli/releases/latest/download/bootstrap.sh && bash /tmp/bootstrap.sh && rm -f /tmp/bootstrap.sh"
    if run_on_device "command -v vellum" >/dev/null 2>&1; then
        info "Vellum installed successfully"
    else
        fail "Vellum installation failed. Try manually: https://github.com/vellum-dev/vellum"
    fi
fi

# ── Step 5: Install XOVI if missing ────────────────────────
step "Checking for XOVI"

if run_on_device "test -d /home/root/xovi"; then
    info "XOVI already installed"
else
    warn "XOVI not found — installing via Vellum..."
    run_on_device "vellum add xovi"
    if run_on_device "test -d /home/root/xovi"; then
        info "XOVI installed successfully"
    else
        fail "XOVI installation failed. Try manually: ssh root@$DEVICE 'vellum add xovi'"
    fi
fi

# ── Step 5b: Install xovi-extensions (provides qt-resource-rebuilder) ─
step "Installing XOVI extensions"

# qt-resource-rebuilder is required for AppLoad to inject its hamburger-menu
# entry into xochitl.  It ships in the xovi-extensions Vellum package.
run_on_device "vellum add xovi-extensions 2>/dev/null || true"
info "XOVI extensions up-to-date"

# ── Step 6: Install AppLoad extension if missing ───────────
step "Checking for AppLoad"

APPLOAD_SO="/home/root/xovi/extensions.d/appload.so"
APPLOAD_PER_SERVICE="/home/root/xovi/services/xochitl.service/extensions.d/appload.so"

if run_on_device "test -f $APPLOAD_SO"; then
    info "AppLoad already installed"
else
    warn "AppLoad not found — installing via Vellum..."
    run_on_device "vellum update 2>/dev/null || true"
    run_on_device "vellum add appload 2>/dev/null || true"
    if run_on_device "test -f $APPLOAD_SO"; then
        info "AppLoad installed via Vellum"
    else
        warn "Vellum blocked (OS 3.27 not yet supported) — installing from GitHub..."
        run_on_device "
            mkdir -p /tmp/appload-dl /home/root/xovi/extensions.d /home/root/shims
            wget --no-check-certificate -O /tmp/appload-dl/appload.zip \
                'https://github.com/asivery/rm-appload/releases/download/v0.5.1/appload-aarch64.zip'
            cd /tmp/appload-dl && unzip -o appload.zip
            cp appload.so $APPLOAD_SO
            cp qtfb-shim.so /home/root/shims/ 2>/dev/null || true
            cp qtfb-shim-32bit.so /home/root/shims/ 2>/dev/null || true
            rm -rf /tmp/appload-dl
        "
        if run_on_device "test -f $APPLOAD_SO"; then
            info "AppLoad installed from GitHub"
        else
            fail "AppLoad installation failed. Install manually: https://github.com/asivery/rm-appload"
        fi
    fi
fi

# Mirror appload.so to the per-service extensions dir — xovi/start may load from there.
run_on_device "mkdir -p \$(dirname $APPLOAD_PER_SERVICE) && cp $APPLOAD_SO $APPLOAD_PER_SERVICE 2>/dev/null || true"
info "AppLoad mirrored to per-service extensions dir"

# ── Step 7: Rebuild XOVI hashtable ─────────────────────────
step "Rebuilding XOVI hashtable (required for AppLoad menu entry)"

# xovi/start sets XOVI_ROOT to the per-service exthome, so qt-resource-rebuilder
# reads the hashtable from there.  Build at the global path and copy to both.
GLOBAL_HASHTAB="/home/root/xovi/exthome/qt-resource-rebuilder/hashtab"
PER_SERVICE_HASHTAB="/home/root/xovi/services/xochitl.service/exthome/qt-resource-rebuilder/hashtab"

warn "Stopping xochitl and rebuilding hashtable (~30-60s)..."
run_on_device "
    umount /opt 2>/dev/null
    systemctl stop xochitl
    sleep 2
    kill \$(pidof xochitl) 2>/dev/null || true
    mkdir -p \$(dirname $GLOBAL_HASHTAB) \$(dirname $PER_SERVICE_HASHTAB)
    rm -f $GLOBAL_HASHTAB $PER_SERVICE_HASHTAB
    QMLDIFF_HASHTAB_CREATE=$GLOBAL_HASHTAB QML_DISABLE_DISK_CACHE=1 \
        LD_PRELOAD=/home/root/xovi/xovi.so /usr/bin/xochitl 2>&1 | \
        while IFS= read line; do
            echo \"\$line\"
            case \"\$line\" in *'Hashtab saved'*)
                cp $GLOBAL_HASHTAB $PER_SERVICE_HASHTAB 2>/dev/null || true
                kill \$(pidof xochitl) 2>/dev/null
                break;;
            esac
        done
"
info "Hashtable rebuilt and copied to per-service path"

# ── Step 8: Deploy MoveWriter app ──────────────────────────
step "Deploying MoveWriter Native"

run_on_device "mkdir -p $DEST/backend $DEST/qml/components $DEST/resources $DEST/tools"

# Copy all app files
scp "$SCRIPT_DIR/manifest.json" root@"$DEVICE":"$DEST/"
[ -f "$SCRIPT_DIR/icon.png" ] && scp "$SCRIPT_DIR/icon.png" root@"$DEVICE":"$DEST/"

# QML
scp "$SCRIPT_DIR"/qml/main.qml \
    "$SCRIPT_DIR"/qml/ServiceSection.qml \
    "$SCRIPT_DIR"/qml/KeyboardSection.qml \
    "$SCRIPT_DIR"/qml/PasskeyOverlay.qml \
    root@"$DEVICE":"$DEST/qml/"
scp "$SCRIPT_DIR"/qml/components/*.qml root@"$DEVICE":"$DEST/qml/components/"
scp "$SCRIPT_DIR"/qml/application.qrc root@"$DEVICE":"$DEST/qml/"

# Backend
scp "$SCRIPT_DIR"/backend/entry \
    "$SCRIPT_DIR"/backend/main.py \
    "$SCRIPT_DIR"/backend/protocol.py \
    "$SCRIPT_DIR"/backend/bluetooth.py \
    "$SCRIPT_DIR"/backend/service.py \
    "$SCRIPT_DIR"/backend/layout_patcher.py \
    "$SCRIPT_DIR"/backend/config.py \
    "$SCRIPT_DIR"/backend/__init__.py \
    root@"$DEVICE":"$DEST/backend/"

# Tools (layout data)
scp "$SCRIPT_DIR"/tools/generate_qmap.py \
    "$SCRIPT_DIR"/tools/__init__.py \
    root@"$DEVICE":"$DEST/tools/"

# Resources
scp "$SCRIPT_DIR"/resources/bt-keyboard.sh \
    "$SCRIPT_DIR"/resources/remarkable-bt-keyboard.service \
    root@"$DEVICE":"$DEST/resources/"

# Make entry script executable
run_on_device "chmod +x $DEST/backend/entry"

info "MoveWriter deployed to $DEST"

# ── Step 9: Activate XOVI (loads AppLoad into running xochitl) ─────────
step "Activating XOVI"

warn "Starting XOVI — AppLoad will appear in hamburger menu (~10s)..."
run_on_device "
    umount /opt 2>/dev/null
    bash /home/root/xovi/start
    sleep 5
    mount -a 2>/dev/null
"
info "XOVI active — AppLoad loaded"

# ── Done ───────────────────────────────────────────────────
step "Setup complete!"
echo ""
echo "  MoveWriter Native is installed on your Move."
echo "  Open the hamburger menu (☰) on the Move → AppLoad → MoveWriter"
echo ""
echo "  AppLoad appears in the ☰ hamburger menu (top-right), NOT the sidebar."
echo ""
