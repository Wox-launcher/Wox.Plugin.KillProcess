import datetime
import os
import platform

import psutil
from wox_plugin import (
    ActionContext,
    Context,
    Plugin,
    PluginInitParams,
    PublicAPI,
    Query,
    RefreshableResult,
    Result,
    ResultAction,
    WoxImage,
    WoxImageType,
)

# Import macOS specific modules if running on macOS
if platform.system() == "Darwin":
    try:
        from AppKit import NSWorkspace
    except ImportError:
        pass


class KillProcessPlugin(Plugin):
    api: PublicAPI

    async def init(self, ctx: Context, init_params: PluginInitParams) -> None:
        self.api = init_params.api

    def on_refresh(self, r: RefreshableResult) -> RefreshableResult:
        r.sub_title = f"Refresh at {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        return r

    async def kill_process(self, ctx: Context, pid: int) -> None:
        try:
            process = psutil.Process(pid)
            process.terminate()
            await self.api.notify(ctx, f"Successfully terminated process {pid}")
        except psutil.NoSuchProcess:
            await self.api.notify(ctx, f"Process {pid} no longer exists")
        except psutil.AccessDenied:
            await self.api.notify(ctx, f"Access denied when trying to kill process {pid}")
        except Exception as e:
            await self.api.notify(ctx, f"Error killing process {pid}: {str(e)}")

    async def action(self, actionContext: ActionContext):
        try:
            pid = int(actionContext.context_data)
            await self.kill_process(Context.new(), pid)
        except ValueError:
            await self.api.notify(Context.new(), "Invalid process ID")

    def get_friendly_name(self, proc) -> str:
        try:
            # macOS specific handling
            if platform.system() == "Darwin":
                try:
                    # Try to get the application name using NSRunningApplication
                    workspace = NSWorkspace.sharedWorkspace()
                    for app in workspace.runningApplications():
                        if app.processIdentifier() == proc.pid:
                            # Get the localized name of the application
                            if app.localizedName():
                                return str(app.localizedName())
                            break
                except Exception:  # Catch specific AppKit related exceptions
                    pass

            # Generic handling for other platforms or fallback
            if hasattr(proc, "exe"):
                try:
                    exe_path = proc.exe()
                    # For macOS, try to get the app name from the .app bundle
                    if platform.system() == "Darwin" and ".app/" in exe_path:
                        app_path = exe_path[: exe_path.find(".app/") + 4]
                        return os.path.splitext(os.path.basename(app_path))[0]
                    return os.path.splitext(os.path.basename(exe_path))[0]
                except (psutil.AccessDenied, psutil.NoSuchProcess):
                    pass

            # Fallback to process name if exe is not available
            return proc.info["name"]
        except Exception:  # Catch any remaining exceptions to ensure we always return a name
            return proc.info["name"]

    async def query(self, ctx: Context, query: Query) -> list[Result]:
        results: list[Result] = []
        search_term = query.search.lower() if query.search else ""

        # Get all running processes
        for proc in psutil.process_iter(["pid", "name", "username", "memory_info"]):
            try:
                pinfo = proc.info
                process_name = pinfo["name"].lower()
                friendly_name = self.get_friendly_name(proc)

                # Filter processes if search term exists
                if search_term and search_term not in process_name and search_term not in friendly_name.lower():
                    continue

                # Calculate memory usage in MB
                try:
                    memory_info = pinfo["memory_info"]
                    memory_mb = memory_info.rss / (1024 * 1024) if memory_info else 0
                    memory_text = f"Memory: {memory_mb:.1f} MB"
                except Exception:
                    memory_text = "Memory: N/A"

                results.append(
                    Result(
                        title=f"{friendly_name} (PID: {pinfo['pid']})",
                        sub_title=f"Process: {pinfo['name']} | User: {pinfo['username']} | {memory_text}",
                        icon=WoxImage(
                            image_type=WoxImageType.RELATIVE,
                            image_data="image/app.png",
                        ),
                        context_data=str(pinfo["pid"]),
                        actions=[
                            ResultAction(
                                name="Kill Process",
                                prevent_hide_after_action=True,
                                action=self.action,
                            )
                        ],
                        refresh_interval=1000,
                        on_refresh=self.on_refresh,
                        score=(100 if search_term and (search_term in process_name or search_term in friendly_name.lower()) else 50),
                    )
                )
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue

        return results


plugin = KillProcessPlugin()
