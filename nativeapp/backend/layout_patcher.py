"""Binary patcher for libepaper.so keyboard layouts on reMarkable Move.

Adapted from movewriterapp/core/layout_patcher.py — replaces SSH file
transfers with local Path.read_bytes/write_bytes.

IMPORTANT: Applying a layout requires restarting xochitl, which kills this
app (since it runs inside xochitl via AppLoad). The patch is written to disk
and the user is told to reboot or manually restart xochitl.
"""
import logging
import os
import shutil
import struct
import subprocess
from pathlib import Path

# Import layout mappings — the tools directory is bundled with the backend
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from tools.generate_qmap import get_layout_mappings

log = logging.getLogger(__name__)

LIBEPAPER_PATH = "/usr/lib/plugins/platforms/libepaper.so"
BACKUP_PATH = "/home/root/.movewriter/libepaper.so.orig"
LAYOUT_FILE = "/home/root/.movewriter-layout"
SCRIPT_DIR = "/home/root/.movewriter"

# US keymap location in libepaper.so (ARM64, little-endian)
# Fallback for 3.22/3.26 — _find_keymap_region() auto-detects for newer firmware.
US_KEYMAP_OFFSET = 0x0250b0
ENTRY_SIZE = 16
ENTRY_COUNT = 211


def _find_keymap_region(data):
    """Locate the US keymap table in libepaper.so for any firmware version.

    Scans at 16-byte strides for known US letter entries (HID keycodes 4-7
    mapping to a/b/c/d). Falls back to the hardcoded 3.22/3.26 offset on
    failure. Returns (start_offset, scan_count).
    """
    needle_a = struct.pack('<HH', 4, 0x61)  # HID 4 = 'a'
    needle_b = struct.pack('<HH', 5, 0x62)  # HID 5 = 'b'
    needle_c = struct.pack('<HH', 6, 0x63)  # HID 6 = 'c'
    needle_d = struct.pack('<HH', 7, 0x64)  # HID 7 = 'd'

    scan_window = ENTRY_COUNT * ENTRY_SIZE
    for pos in range(0x10000, len(data) - scan_window, ENTRY_SIZE):
        if data[pos:pos + 4] == needle_a:
            region = data[max(0, pos - scan_window):pos + scan_window]
            if needle_b in region and needle_c in region and needle_d in region:
                start = max(0, pos - scan_window)
                log.info("Keymap detected at ~0x%x (anchor at 0x%x)", start, pos)
                return start, ENTRY_COUNT * 2 + 1

    log.warning("Keymap auto-detect failed; using hardcoded 0x%x", US_KEYMAP_OFFSET)
    return US_KEYMAP_OFFSET, ENTRY_COUNT


def _run(cmd, timeout=10):
    result = subprocess.run(
        cmd, shell=True, capture_output=True, text=True, timeout=timeout
    )
    return result.stdout, result.stderr, result.returncode


def _patch_binary(data, layout_key):
    """Patch the US keymap in libepaper.so binary data with a new layout.

    Groups entries by keycode, sorts by modifier byte, and patches:
      - lowest modifier  → plain unicode
      - second modifier  → shift unicode
    Returns the patched binary as bytes.
    """
    letters, punct = get_layout_mappings(layout_key)

    # Build target mappings: keycode → (plain_unicode, shift_unicode, plain_qt, shift_qt)
    targets = {}
    for kc, new_lower, new_upper, qt_key in letters:
        targets[kc] = (new_lower, new_upper, qt_key, qt_key)
    for kc, plain_u, plain_qt, shift_u, shift_qt in punct:
        targets[kc] = (plain_u, shift_u, plain_qt, shift_qt)

    # Force dead key defaults for keys not in the layout
    DEAD_KEY_DEFAULTS = {
        26: (0x5B, 0x7B, 0x5B, 0x7B),  # [ / {
        27: (0x5D, 0x7D, 0x5D, 0x7D),  # ] / }
    }
    for kc, vals in DEAD_KEY_DEFAULTS.items():
        if kc not in targets:
            targets[kc] = vals

    if not targets:
        return data

    # First pass: group binary entries by keycode
    entries_by_kc = {}
    scan_start, scan_count = _find_keymap_region(data)
    for i in range(scan_count):
        offset = scan_start + i * ENTRY_SIZE
        if offset + ENTRY_SIZE > len(data):
            break
        keycode = struct.unpack_from('<H', data, offset)[0]
        if keycode in targets:
            mod = data[offset + 8]
            entries_by_kc.setdefault(keycode, []).append((offset, mod))

    # Second pass: patch plain and shift entries
    patched = bytearray(data)
    patch_count = 0

    DEAD_KEY_QT_MIN = 0x01001250
    DEAD_KEY_QT_MAX = 0x01001263

    for kc, (new_plain, new_shift, plain_qt, shift_qt) in targets.items():
        entries = entries_by_kc.get(kc, [])
        if not entries:
            log.warning("No entries found for keycode %d", kc)
            continue

        entries.sort(key=lambda e: e[1])

        # Patch plain entry
        offset, mod = entries[0]
        struct.pack_into('<H', patched, offset + 2, new_plain)
        old_qt = struct.unpack_from('<I', patched, offset + 4)[0]
        if DEAD_KEY_QT_MIN <= old_qt <= DEAD_KEY_QT_MAX:
            struct.pack_into('<I', patched, offset + 4, plain_qt)
            struct.pack_into('<H', patched, offset + 10, 0)
        patch_count += 1

        # Patch shift entry
        if len(entries) >= 2:
            offset, mod = entries[1]
            struct.pack_into('<H', patched, offset + 2, new_shift)
            old_qt = struct.unpack_from('<I', patched, offset + 4)[0]
            if DEAD_KEY_QT_MIN <= old_qt <= DEAD_KEY_QT_MAX:
                struct.pack_into('<I', patched, offset + 4, shift_qt)
                struct.pack_into('<H', patched, offset + 10, 0)
            patch_count += 1

    log.info("Patched %d entries for layout '%s'", patch_count, layout_key)
    return bytes(patched)


def apply_layout(layout_key, status_cb=None):
    """Patch libepaper.so on device with the given layout.

    Does NOT restart xochitl — the app runs inside xochitl so restarting
    would kill the app. The layout takes effect after next reboot or
    manual xochitl restart.
    """
    def status(msg):
        log.info(msg)
        if status_cb:
            status_cb(msg)

    os.makedirs(SCRIPT_DIR, exist_ok=True)

    backup = Path(BACKUP_PATH)
    if not backup.exists():
        # Backup the stock binary on first run. Do this silently — status
        # events mid-flight can get dropped if xochitl briefly slows down
        # during the rootfs remount, leaving the UI stuck on intermediate
        # progress text. A single final "Applied" response is more robust.
        shutil.copy2(LIBEPAPER_PATH, BACKUP_PATH)

    original = backup.read_bytes()
    patched = _patch_binary(original, layout_key)

    # Write patched binary (requires rw remount)
    _run("mount -o remount,rw /", timeout=10)
    try:
        Path(LIBEPAPER_PATH).write_bytes(patched)
    finally:
        _run("mount -o remount,ro /", timeout=10)

    # Save layout key to device
    Path(LAYOUT_FILE).write_text(layout_key)
    status("Layout applied — reboot to take effect")


def read_current_layout_key():
    """Return the layout key currently written on-device, or '' if unset."""
    try:
        return Path(LAYOUT_FILE).read_text().strip()
    except (FileNotFoundError, OSError):
        return ""


def read_current_layout_display_name(layouts_list):
    """Return the display name for the layout on device.

    layouts_list is a list of (display_name, layout_key) tuples.
    Returns '' if no layout is applied on device.
    """
    key = read_current_layout_key()
    if not key:
        return ""
    for display, k in layouts_list:
        if k == key:
            return display
    return ""


def restore_original():
    """Restore the original unpatched libepaper.so. Used during uninstall."""
    backup = Path(BACKUP_PATH)
    if not backup.exists():
        return  # No backup means no patching was ever done

    original = backup.read_bytes()

    # Write original binary (requires rw remount)
    # NOTE: This is called during uninstall which may happen while xochitl
    # is running. The restored library takes effect after next reboot.
    _run("mount -o remount,rw /", timeout=10)
    try:
        Path(LIBEPAPER_PATH).write_bytes(original)
    finally:
        _run("mount -o remount,ro /", timeout=10)

    # Clean up layout file and backup
    try:
        os.remove(LAYOUT_FILE)
    except FileNotFoundError:
        pass
    try:
        os.remove(BACKUP_PATH)
    except FileNotFoundError:
        pass
