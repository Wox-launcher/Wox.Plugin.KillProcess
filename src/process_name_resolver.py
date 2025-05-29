import os
import platform
from typing import Optional

import psutil

# Import platform specific modules
if platform.system() == "Darwin":
    try:
        from AppKit import NSURL, NSBundle, NSWorkspace  # type: ignore
    except ImportError:
        NSURL = None  # type: ignore
        NSBundle = None  # type: ignore
        NSWorkspace = None  # type: ignore
else:
    NSURL = None  # type: ignore
    NSBundle = None  # type: ignore
    NSWorkspace = None  # type: ignore


class ProcessNameResolver:
    def __init__(self):
        self._cache: dict[int, tuple[str, float]] = {}  # type: ignore
        self._cache_expiration = 60  # Cache expiration time in seconds

    def _get_macos_app_name_from_bundle(self, app_path: str) -> Optional[str]:
        """Get application name from macOS bundle."""
        try:
            # Check if required classes are available
            if NSURL is None or NSBundle is None:
                return None

            # Convert the path to a file URL if it's not already
            if not app_path.startswith("file://"):
                url = NSURL.fileURLWithPath_(app_path)
            else:
                url = NSURL.URLWithString_(app_path)

            # Try to get the bundle
            bundle = NSBundle.bundleWithURL_(url)
            if bundle:
                # Try to get the localized name from the bundle
                localized_info = bundle.localizedInfoDictionary()
                if localized_info:
                    localized_name = localized_info.get("CFBundleDisplayName") or localized_info.get("CFBundleName")
                    if localized_name:
                        return str(localized_name)

                # If no localized name, try the regular info dictionary
                info_dict = bundle.infoDictionary()
                if info_dict:
                    name = info_dict.get("CFBundleDisplayName") or info_dict.get("CFBundleName")
                    if name:
                        return str(name)
        except Exception as e:
            print(f"Error getting bundle name for {app_path}: {str(e)}")
            pass
        return None

    def _get_macos_friendly_name(self, proc: psutil.Process, default_name: str) -> str:
        """Get friendly name for macOS processes."""
        try:
            # Check if NSWorkspace is available
            if NSWorkspace is None:
                return default_name

            # Try to get the application name using NSRunningApplication
            workspace = NSWorkspace.sharedWorkspace()
            for app in workspace.runningApplications():
                if app.processIdentifier() == proc.pid:
                    # Try to get the localized name first
                    if app.localizedName():
                        return str(app.localizedName())

            # If we couldn't get the name from NSRunningApplication, try the bundle path
            try:
                exe_path = proc.exe()
                if ".app" in exe_path:
                    # Find the .app bundle path
                    app_path = exe_path
                    app_index = exe_path.find(".app")
                    if app_index != -1:
                        app_path = exe_path[: app_index + 4]
                        bundle_name = self._get_macos_app_name_from_bundle(app_path)
                        if bundle_name:
                            return bundle_name
            except (psutil.AccessDenied, psutil.NoSuchProcess):
                pass

        except Exception as e:
            print(f"Error getting friendly name: {str(e)}")
            pass

        return default_name

    def _get_linux_friendly_name(self, proc: psutil.Process, default_name: str) -> str:
        """Get friendly name for Linux processes."""
        try:
            # Try to get name from .desktop files
            if hasattr(proc, "exe"):
                exe_path = proc.exe()
                desktop_paths = [
                    "/usr/share/applications/",
                    "/usr/local/share/applications/",
                    os.path.expanduser("~/.local/share/applications/"),
                ]

                exe_name = os.path.basename(exe_path)
                for desktop_path in desktop_paths:
                    for file in os.listdir(desktop_path):
                        if file.endswith(".desktop"):
                            try:
                                with open(os.path.join(desktop_path, file), "r", encoding="utf-8") as f:
                                    content = f.read()
                                    if exe_name in content:
                                        for line in content.split("\n"):
                                            if line.startswith("Name="):
                                                return line[5:].strip()
                            except Exception:
                                continue
        except Exception:
            pass

        return default_name

    def get_friendly_name(self, proc: psutil.Process) -> str:
        """
        Get a user-friendly name for a process.
        This method is platform-aware and will use the appropriate method for each OS.
        """
        try:
            # Get process info using as_dict() method
            proc_info = proc.as_dict(attrs=["name"])
            default_name = proc_info["name"]

            # Use platform-specific name resolution
            system = platform.system()
            if system == "Darwin":
                return self._get_macos_friendly_name(proc, default_name)
            elif system == "Linux":
                return self._get_linux_friendly_name(proc, default_name)

            return default_name
        except Exception as e:
            print(f"Error in get_friendly_name: {str(e)}")
            # If we can't get the info using as_dict(), try to get name directly
            try:
                return proc.name()
            except Exception:
                return "Unknown Process"
