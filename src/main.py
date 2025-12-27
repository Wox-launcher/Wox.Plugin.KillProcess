import asyncio
import platform
import uuid
from dataclasses import dataclass, field
from typing import Dict

import psutil
from wox_plugin import (
    ActionContext,
    Context,
    Plugin,
    PluginInitParams,
    PublicAPI,
    Query,
    Result,
    ResultAction,
    ResultTail,
    ResultTailType,
    WoxImage,
    WoxImageType,
)

from .process_name_resolver import ProcessNameResolver


@dataclass
class ProcessInfo:
    pid: int
    name: str
    exe_path: str
    username: str
    memory_mb: float
    friendly_name: str


@dataclass
class TrackedResult:
    result_id: str
    pid: int


class MyPlugin(Plugin):
    api: PublicAPI
    name_resolver: ProcessNameResolver
    _processes: Dict[int, ProcessInfo] = field(default_factory=dict)
    _tracked_results: Dict[str, TrackedResult] = field(default_factory=dict)
    _refresh_task: asyncio.Task | None = None
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    @staticmethod
    def _format_app_path(exe_path: str) -> str:
        """Format path for display - truncate to .app on macOS."""
        if not exe_path:
            return exe_path

        if platform.system() == "Darwin":
            # Find .app in the path and truncate to that level
            app_index = exe_path.find(".app")
            if app_index != -1:
                # Include the .app part
                return exe_path[: app_index + 4]

        return exe_path

    async def init(self, _ctx: Context, init_params: PluginInitParams) -> None:
        self.api = init_params.api
        self.name_resolver = ProcessNameResolver()
        self._processes = {}
        self._tracked_results = {}
        self._lock = asyncio.Lock()

        # Start background refresh task
        self._refresh_task = asyncio.create_task(self._refresh_processes_loop())

    async def _t(self, ctx: Context, key: str, **kwargs) -> str:
        """Get translated string with parameter substitution."""
        template = await self.api.get_translation(ctx, key)
        if kwargs:
            return template.format(**kwargs)
        return template

    async def kill_process(self, ctx: Context, pid: int) -> None:
        try:
            process = psutil.Process(pid)
            process.terminate()
            await self.api.notify(ctx, await self._t(ctx, "notify_success", pid=str(pid)))
        except psutil.NoSuchProcess:
            await self.api.notify(ctx, await self._t(ctx, "notify_no_process", pid=str(pid)))
        except psutil.AccessDenied:
            await self.api.notify(ctx, await self._t(ctx, "notify_access_denied", pid=str(pid)))
        except Exception as e:
            await self.api.notify(ctx, await self._t(ctx, "notify_error", pid=str(pid), error=str(e)))

    async def action(self, _ctx: Context, actionContext: ActionContext):
        try:
            pid = int(actionContext.context_data["pid"])
            await self.kill_process(Context.new(), pid)
        except ValueError:
            await self.api.notify(Context.new(), "i18n:notify_invalid_pid")

    async def _refresh_processes_loop(self) -> None:
        """Background task to periodically refresh process list."""
        while True:
            await self._refresh_processes()
            await asyncio.sleep(1)

    async def _refresh_processes(self) -> None:
        """Refresh the cached process list and update tracked results."""
        async with self._lock:
            new_processes: Dict[int, ProcessInfo] = {}

            for proc in psutil.process_iter(["pid", "name", "username", "memory_info"]):
                try:
                    pinfo = proc.info
                    proc_obj = psutil.Process(pinfo["pid"])
                    friendly_name = self.name_resolver.get_friendly_name(proc_obj)

                    memory_mb = 0
                    try:
                        memory_info = pinfo["memory_info"]
                        memory_mb = memory_info.rss / (1024 * 1024) if memory_info else 0
                    except Exception:
                        pass

                    exe_path = ""
                    try:
                        exe_path = proc_obj.exe() or ""
                    except Exception:
                        pass

                    new_processes[pinfo["pid"]] = ProcessInfo(
                        pid=pinfo["pid"],
                        name=pinfo["name"],
                        exe_path=exe_path,
                        username=pinfo["username"] or "N/A",
                        memory_mb=memory_mb,
                        friendly_name=friendly_name,
                    )
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    continue

            self._processes = new_processes

            # Update tracked results
            await self._update_tracked_results()

    async def _create_tails(self, ctx: Context, proc_info: ProcessInfo) -> list[ResultTail]:
        """Create result tails for PID and memory info."""
        tails = []

        # PID tail
        pid_text = await self._t(ctx, "tail_pid", pid=str(proc_info.pid))
        tails.append(ResultTail(type=ResultTailType.TEXT, text=pid_text))

        # Memory tail
        memory_text = await self._t(ctx, "tail_memory", memory_mb=f"{proc_info.memory_mb:.1f}")
        tails.append(ResultTail(type=ResultTailType.TEXT, text=memory_text))

        return tails

    async def _update_tracked_results(self) -> None:
        """Update all tracked results with fresh process data."""
        to_remove: list[str] = []
        ctx = Context.new()

        for result_id, tracked in self._tracked_results.items():
            # Check if process still exists
            process = self._processes.get(tracked.pid)
            if not process:
                to_remove.append(result_id)
                continue

            try:
                # Get updatable result (returns None if no longer visible)
                updatable = await self.api.get_updatable_result(ctx, result_id)
                if updatable is None:
                    to_remove.append(result_id)
                    continue

                # Update the result data
                updatable.title = await self._t(ctx, "process_title", friendly_name=process.friendly_name, pid=str(process.pid))
                updatable.sub_title = self._format_app_path(process.exe_path) or process.name
                updatable.tails = await self._create_tails(ctx, process)

                # Try to update the result
                success = await self.api.update_result(ctx, updatable)
                if not success:
                    # Result no longer visible
                    to_remove.append(result_id)
            except Exception:
                to_remove.append(result_id)

        # Remove stale results
        for result_id in to_remove:
            self._tracked_results.pop(result_id, None)

    async def query(self, ctx: Context, query: Query) -> list[Result]:
        results: list[Result] = []
        search_term = query.search.lower() if query.search else ""

        # Clear previous tracked results
        self._tracked_results.clear()

        # Use cached process list
        async with self._lock:
            for pid, proc_info in list(self._processes.items()):
                process_name = proc_info.name.lower()
                friendly_name = proc_info.friendly_name
                exe_path = proc_info.exe_path.lower()

                # Filter processes if search term exists
                if (
                    search_term
                    and search_term not in process_name
                    and search_term not in friendly_name.lower()
                    and search_term not in exe_path
                ):
                    continue

                result_id = str(uuid.uuid4())
                exec_path = self._format_app_path(proc_info.exe_path) or proc_info.name
                result = Result(
                    title=await self._t(ctx, "process_title", friendly_name=friendly_name, pid=str(pid)),
                    sub_title=exec_path,
                    icon=WoxImage(image_type=WoxImageType.FILE_ICON, image_data=exec_path),
                    tails=await self._create_tails(ctx, proc_info),
                    actions=[
                        ResultAction(
                            name="i18n:kill_action",
                            context_data={"pid": str(pid)},
                            prevent_hide_after_action=True,
                            action=self.action,
                        )
                    ],
                    id=result_id,
                    score=(100 if search_term and (search_term in process_name or search_term in friendly_name.lower()) else 50),
                )
                results.append(result)

                # Track this result for updates
                self._tracked_results[result_id] = TrackedResult(
                    result_id=result_id,
                    pid=pid,
                )

        return results


plugin = MyPlugin()
