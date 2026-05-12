"""Tests for tools.generate_qmap — verify .qmap binary header is well-formed."""


def test_magic_and_version_constants():
    from tools import generate_qmap as gq

    assert gq.MAGIC == 0x514D4150  # 'QMAP' ASCII
    assert gq.VERSION == 1


def test_modifier_bits_are_disjoint():
    """Modifier flags are bit-masks — they must not collide."""
    from tools import generate_qmap as gq

    mods = [gq.MOD_PLAIN, gq.MOD_SHIFT, gq.MOD_ALTGR, gq.MOD_CONTROL, gq.MOD_ALT]
    seen = 0
    for m in mods:
        # PLAIN is 0; the others should each set a unique bit
        if m == 0:
            continue
        assert (seen & m) == 0, f"Modifier bit collision: 0x{m:02x}"
        seen |= m
