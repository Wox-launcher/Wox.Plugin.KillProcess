"""
Dynamic dependency installation module.

Usage:
    from dynamic_deps import ensure_package

    psutil = ensure_package("psutil")
"""

import importlib
import os
import subprocess
import sys
import types


def _get_cache_dir(plugin_name: str) -> str:
    """Get a reliable cache directory for dependencies."""
    return os.path.join(os.path.expanduser("~"), ".wox", "cache", "python-dynamic-deps", plugin_name)


def _ensure_pip() -> None:
    """Ensure pip is available, installing it if necessary."""
    try:
        subprocess.run([sys.executable, "-m", "pip", "--version"], check=True, capture_output=True)
    except Exception:
        import ensurepip

        ensurepip.bootstrap(upgrade=True)


def _clear_package_modules(package_name: str) -> None:
    """Remove failed modules before importing the newly installed package."""
    for mod in list(sys.modules.keys()):
        if mod == package_name or mod.startswith(f"{package_name}."):
            del sys.modules[mod]


def ensure_package(package_name: str, plugin_name: str = "default") -> types.ModuleType:
    """
    Ensure a package is available, installing it if necessary.

    Args:
        package_name: Name of the package to import (e.g., "psutil")
        plugin_name: Plugin identifier for cache directory isolation

    Returns:
        The imported module
    """
    cache_dir = _get_cache_dir(plugin_name)

    # Add cache dir to path if not already there
    if cache_dir not in sys.path:
        sys.path.insert(0, cache_dir)

    # Try importing first
    try:
        module = importlib.import_module(package_name)
        # Verify module is functional (not a broken partial install)
        if hasattr(module, "__version__") or hasattr(module, "__file__"):
            return module
    except Exception:
        pass

    # Clear any broken cached imports
    _clear_package_modules(package_name)

    # Install to cache directory
    try:
        _ensure_pip()
        os.makedirs(cache_dir, exist_ok=True)
        subprocess.run(
            [sys.executable, "-m", "pip", "install", package_name, "--target", cache_dir, "--upgrade", "--quiet"],
            check=True,
        )
        importlib.invalidate_caches()
        _clear_package_modules(package_name)
        return importlib.import_module(package_name)
    except Exception as e:
        raise ImportError(f"Failed to install or import {package_name}: {e}") from e
