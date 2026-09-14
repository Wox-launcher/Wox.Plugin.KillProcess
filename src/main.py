# ruff: noqa: E402
from .dynamic_deps import ensure_package

psutil = ensure_package("psutil", plugin_name="killprocess")  # type: ignore[assignment]

import platform
import uuid
from dataclasses import dataclass, field, replace
from typing import Dict
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

_RESULT_LIMIT = 20
_I18N_DEFAULTS = {
    "process_title": "{friendly_name}",
    "tail_pid": "PID: {pid}",
    "tail_memory": "{memory_mb} MB",
    "notify_success": "Successfully terminated process {pid}",
    "notify_no_process": "Process {pid} no longer exists",
    "notify_access_denied": "Access denied when trying to kill process {pid}",
    "notify_error": "Error killing process {pid}: {error}",
}


@dataclass
class ProcessInfo:
    pid: int
    name: str
    exe_path: str
    memory_mb: float
    friendly_name: str


class MyPlugin(Plugin):
    api: PublicAPI
    name_resolver: ProcessNameResolver
    _processes: Dict[int, ProcessInfo] = field(default_factory=dict)
    _templates: Dict[str, str] = field(default_factory=lambda: dict(_I18N_DEFAULTS))

    @staticmethod
    def _format_app_path(exe_path: str) -> str:
        """Format path for display - truncate to .app on macOS."""
        if not exe_path:
            return exe_path

        if platform.system() == "Darwin":
            app_index = exe_path.find(".app")
            if app_index != -1:
                return exe_path[: app_index + 4]

        return exe_path

    async def init(self, _ctx: Context, init_params: PluginInitParams) -> None:
        self.api = init_params.api
        self.name_resolver = ProcessNameResolver()
        self._processes = {}
        self._templates = dict(_I18N_DEFAULTS)
        for key in _I18N_DEFAULTS:
            self._templates[key] = await self.api.get_translation(_ctx, key)
        self._processes = self._collect_processes({})

    def _t(self, key: str, **kwargs) -> str:
        """Format a cached translation. Avoid per-result GetTranslation RPCs."""
        templates = getattr(self, "_templates", None)
        if not isinstance(templates, dict):
            templates = _I18N_DEFAULTS
        template = templates.get(key) or _I18N_DEFAULTS.get(key, key)
        if kwargs:
            return template.format(**kwargs)
        return template

    async def kill_process(self, ctx: Context, pid: int) -> None:
        try:
            process = psutil.Process(pid)
            process.terminate()
            await self.api.notify(ctx, self._t("notify_success", pid=str(pid)))
        except psutil.NoSuchProcess:
            await self.api.notify(ctx, self._t("notify_no_process", pid=str(pid)))
        except psutil.AccessDenied:
            await self.api.notify(ctx, self._t("notify_access_denied", pid=str(pid)))
        except Exception as e:
            await self.api.notify(ctx, self._t("notify_error", pid=str(pid), error=str(e)))

    async def action(self, _ctx: Context, actionContext: ActionContext):
        try:
            pid = int(actionContext.context_data["pid"])
            await self.kill_process(Context.new(), pid)
        except ValueError:
            await self.api.notify(Context.new(), "i18n:notify_invalid_pid")

    def _collect_processes(self, previous: Dict[int, ProcessInfo]) -> Dict[int, ProcessInfo]:
        """List processes with pid+name only. memory_info/create_time block the Python host."""
        new_processes: Dict[int, ProcessInfo] = {}

        for proc in psutil.process_iter(["pid", "name"]):
            try:
                pinfo = proc.info
                pid = pinfo["pid"]
                name = pinfo["name"] or ""
                cached = previous.get(pid)
                if cached is not None and cached.name == name:
                    new_processes[pid] = cached
                    continue

                new_processes[pid] = ProcessInfo(
                    pid=pid,
                    name=name,
                    exe_path=cached.exe_path if cached else "",
                    memory_mb=cached.memory_mb if cached else 0.0,
                    friendly_name=cached.friendly_name if cached else name,
                )
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue

        return new_processes

    def _hydrate_details(self, proc_info: ProcessInfo) -> ProcessInfo:
        """Read memory/exe only for rows we are about to show."""
        try:
            proc = psutil.Process(proc_info.pid)
            memory_mb = proc.memory_info().rss / (1024 * 1024)
            exe_path = proc_info.exe_path
            if not exe_path:
                try:
                    exe_path = proc.exe() or ""
                except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess, OSError):
                    exe_path = ""
            friendly_name = self.name_resolver.get_friendly_name(
                proc,
                default_name=proc_info.name,
                exe_path=exe_path,
            )
            return replace(
                proc_info,
                memory_mb=memory_mb,
                exe_path=exe_path,
                friendly_name=friendly_name,
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            return proc_info

    def _create_tails(self, proc_info: ProcessInfo) -> list[ResultTail]:
        """Create result tails for PID and memory info."""
        return [
            ResultTail(type=ResultTailType.TEXT, text=self._t("tail_pid", pid=str(proc_info.pid))),
            ResultTail(
                type=ResultTailType.TEXT,
                text=self._t("tail_memory", memory_mb=f"{proc_info.memory_mb:.1f}"),
            ),
        ]

    @staticmethod
    def _matches_search(proc_info: ProcessInfo, search_term: str) -> bool:
        return (
            search_term in proc_info.name.lower()
            or search_term in proc_info.friendly_name.lower()
            or search_term in proc_info.exe_path.lower()
        )

    def _select_processes(self, search_term: str) -> list[ProcessInfo]:
        """Return the top memory consumers, optionally filtered by search."""
        search_term = search_term.strip().lower()
        processes = list(self._processes.values())
        if search_term:
            processes = [item for item in processes if self._matches_search(item, search_term)]
        processes.sort(key=lambda item: item.memory_mb, reverse=True)
        return processes[:_RESULT_LIMIT]

    def _build_result(self, proc_info: ProcessInfo, search_term: str) -> Result:
        process_name = proc_info.name.lower()
        friendly_name = proc_info.friendly_name
        result_id = str(uuid.uuid4())
        exec_path = self._format_app_path(proc_info.exe_path) or proc_info.name
        return Result(
            title=self._t("process_title", friendly_name=friendly_name, pid=str(proc_info.pid)),
            sub_title=exec_path,
            icon=WoxImage(image_type=WoxImageType.FILE_ICON, image_data=exec_path),
            tails=self._create_tails(proc_info),
            actions=[
                ResultAction(
                    name="i18n:kill_action",
                    context_data={"pid": str(proc_info.pid)},
                    prevent_hide_after_action=True,
                    action=self.action,
                )
            ],
            id=result_id,
            score=(
                int(proc_info.memory_mb)
                if not search_term
                else (100 if search_term in process_name or search_term in friendly_name.lower() else 50)
            ),
        )

    async def query(self, ctx: Context, query: Query) -> list[Result]:
        search_term = query.search.strip().lower() if query.search else ""
        self._processes = self._collect_processes(self._processes)
        selected = [self._hydrate_details(item) for item in self._select_processes(search_term)]
        for item in selected:
            self._processes[item.pid] = item
        return [self._build_result(item, search_term) for item in selected]


plugin = MyPlugin()
