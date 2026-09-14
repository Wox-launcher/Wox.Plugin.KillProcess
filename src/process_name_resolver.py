import os
import platform
import time
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

_LINUX_DESKTOP_REFRESH_SEC = 60.0
_LINUX_DESKTOP_DIRS = (
    "/usr/share/applications/",
    "/usr/local/share/applications/",
)


class ProcessNameResolver:
    def __init__(self):
        self._cache: dict[tuple[int, float], str] = {}
        self._macos_app_names: dict[int, str] | None = None
        self._bundle_name_cache: dict[str, str] = {}
        self._linux_desktop_map: dict[str, str] | None = None
        self._linux_desktop_loaded_at = 0.0

    def prepare_batch(self) -> None:
        """Refresh per-scan platform maps. Call once before a batch of lookups."""
        system = platform.system()
        if system == "Darwin":
            self._macos_app_names = self._read_macos_app_names()
        elif system == "Linux":
            self._ensure_linux_desktop_map()

    def prune(self, live_keys: set[tuple[int, float]]) -> None:
        stale = [key for key in self._cache if key not in live_keys]
        for key in stale:
            del self._cache[key]

    def get_friendly_name(
        self,
        proc: psutil.Process,
        default_name: str | None = None,
        exe_path: str | None = None,
        create_time: float | None = None,
    ) -> str:
        """
        Get a user-friendly name for a process.
        This method is platform-aware and will use the appropriate method for each OS.
        """
        try:
            if not default_name:
                default_name = self._process_name(proc)
            if create_time is None:
                try:
                    create_time = proc.create_time()
                except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
                    create_time = 0.0

            cache_key = (proc.pid, create_time)
            cached = self._cache.get(cache_key)
            if cached is not None:
                return cached

            system = platform.system()
            if system == "Darwin":
                friendly_name = self._get_macos_friendly_name(proc, default_name, exe_path or "")
            elif system == "Linux":
                friendly_name = self._get_linux_friendly_name(proc, default_name, exe_path or "")
            else:
                friendly_name = default_name

            self._cache[cache_key] = friendly_name
            return friendly_name
        except Exception:
            try:
                return default_name or proc.name()
            except Exception:
                return "Unknown Process"

    def _process_name(self, proc: psutil.Process) -> str:
        try:
            return proc.name() or "Unknown Process"
        except Exception:
            return "Unknown Process"

    def _read_macos_app_names(self) -> dict[int, str]:
        names: dict[int, str] = {}
        if NSWorkspace is None:
            return names
        try:
            workspace = NSWorkspace.sharedWorkspace()
            for app in workspace.runningApplications():
                localized = app.localizedName()
                if localized:
                    names[app.processIdentifier()] = str(localized)
        except Exception:
            pass
        return names

    def _get_macos_app_name_from_bundle(self, app_path: str) -> Optional[str]:
        """Get application name from macOS bundle."""
        cached = self._bundle_name_cache.get(app_path)
        if cached is not None:
            return cached

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
                        name = str(localized_name)
                        self._bundle_name_cache[app_path] = name
                        return name

                # If no localized name, try the regular info dictionary
                info_dict = bundle.infoDictionary()
                if info_dict:
                    name = info_dict.get("CFBundleDisplayName") or info_dict.get("CFBundleName")
                    if name:
                        resolved = str(name)
                        self._bundle_name_cache[app_path] = resolved
                        return resolved
        except Exception:
            pass
        return None

    def _get_macos_friendly_name(self, proc: psutil.Process, default_name: str, exe_path: str) -> str:
        """Get friendly name for macOS processes."""
        try:
            if self._macos_app_names is None:
                self._macos_app_names = self._read_macos_app_names()

            localized = self._macos_app_names.get(proc.pid)
            if localized:
                return localized

            path = exe_path
            if not path:
                try:
                    path = proc.exe() or ""
                except (psutil.AccessDenied, psutil.NoSuchProcess):
                    path = ""

            if ".app" in path:
                app_index = path.find(".app")
                if app_index != -1:
                    app_path = path[: app_index + 4]
                    bundle_name = self._get_macos_app_name_from_bundle(app_path)
                    if bundle_name:
                        return bundle_name
        except Exception:
            pass

        return default_name

    @staticmethod
    def names_from_desktop_content(content: str) -> dict[str, str]:
        """Map executable basenames from Exec= lines to the desktop Name=."""
        name = ""
        exec_basenames: list[str] = []
        for raw_line in content.splitlines():
            line = raw_line.strip()
            if line.startswith("Name=") and not name:
                name = line[5:].strip()
            elif line.startswith("Exec="):
                command = line[5:].strip().split()
                if command:
                    exec_basenames.append(os.path.basename(command[0].strip("\"'")))
        if not name:
            return {}
        return {basename: name for basename in exec_basenames if basename}

    def _linux_desktop_dirs(self) -> list[str]:
        dirs = list(_LINUX_DESKTOP_DIRS)
        dirs.append(os.path.expanduser("~/.local/share/applications/"))
        return dirs

    def _ensure_linux_desktop_map(self) -> dict[str, str]:
        now = time.monotonic()
        if self._linux_desktop_map is not None and now - self._linux_desktop_loaded_at < _LINUX_DESKTOP_REFRESH_SEC:
            return self._linux_desktop_map

        mapping: dict[str, str] = {}
        for desktop_dir in self._linux_desktop_dirs():
            try:
                for filename in os.listdir(desktop_dir):
                    if not filename.endswith(".desktop"):
                        continue
                    try:
                        with open(os.path.join(desktop_dir, filename), encoding="utf-8") as desktop_file:
                            mapping.update(self.names_from_desktop_content(desktop_file.read()))
                    except OSError:
                        continue
            except OSError:
                continue

        self._linux_desktop_map = mapping
        self._linux_desktop_loaded_at = now
        return mapping

    def _get_linux_friendly_name(self, proc: psutil.Process, default_name: str, exe_path: str) -> str:
        """Get friendly name for Linux processes."""
        try:
            mapping = self._ensure_linux_desktop_map()
            path = exe_path
            if not path:
                path = proc.exe() or ""
            exe_name = os.path.basename(path)
            if exe_name and exe_name in mapping:
                return mapping[exe_name]
        except (psutil.AccessDenied, psutil.NoSuchProcess, OSError):
            pass
        except Exception:
            pass

        return default_name
