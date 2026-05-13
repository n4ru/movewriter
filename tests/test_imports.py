"""Smoke test: every non-UI module imports cleanly.

Catches syntax errors, missing dependencies, and circular imports without
needing a display or device connection.
"""
import importlib
import pytest


CORE_MODULES = [
    "core.config",
    "core.ssh_client",
    "core.bluetooth",
    "core.service_installer",
    "core.native_app_installer",
    "core.layout_patcher",
]

TOOL_MODULES = [
    "tools.generate_qmap",
]


@pytest.mark.parametrize("mod", CORE_MODULES + TOOL_MODULES)
def test_module_imports(mod):
    importlib.import_module(mod)
