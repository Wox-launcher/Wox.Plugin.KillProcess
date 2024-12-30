"""
Kill Process plugin for Wox
"""

from .main import KillProcessPlugin
from .process_name_resolver import ProcessNameResolver

__version__ = "0.1.0"
__all__ = ["KillProcessPlugin", "ProcessNameResolver"]
