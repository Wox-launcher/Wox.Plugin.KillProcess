import unittest
from types import SimpleNamespace
from unittest.mock import patch

from src.main import MyPlugin, ProcessInfo, _RESULT_LIMIT
from src.process_name_resolver import ProcessNameResolver


def _info(pid: int, name: str, memory_mb: float, friendly_name: str = "", exe_path: str = "") -> ProcessInfo:
    return ProcessInfo(
        pid=pid,
        name=name,
        exe_path=exe_path or f"C:\\{name}",
        memory_mb=memory_mb,
        friendly_name=friendly_name or name,
    )


class FakeProcess:
    def __init__(self, pid: int, name: str, rss: int = 0, exe: str = ""):
        self.pid = pid
        self.info = {"pid": pid, "name": name}
        self._rss = rss
        self._exe = exe
        self.exe_calls = 0
        self.memory_calls = 0

    def exe(self) -> str:
        self.exe_calls += 1
        return self._exe

    def name(self) -> str:
        return self.info["name"]

    def memory_info(self):
        self.memory_calls += 1
        return SimpleNamespace(rss=self._rss)


class TestProcessRefresh(unittest.TestCase):
    def setUp(self):
        self.plugin = MyPlugin()
        self.plugin.name_resolver = ProcessNameResolver()
        self.plugin._processes = {}

    def test_collect_reuses_cached_details(self):
        first = FakeProcess(42, "chrome.exe", exe="C:\\Chrome\\chrome.exe")
        previous = {42: _info(42, "chrome.exe", 10.0, exe_path="C:\\Chrome\\chrome.exe")}

        with patch("src.main.psutil.process_iter", return_value=[first]):
            collected = self.plugin._collect_processes(previous)

        self.assertEqual(first.exe_calls, 0)
        self.assertEqual(collected[42].exe_path, "C:\\Chrome\\chrome.exe")
        self.assertAlmostEqual(collected[42].memory_mb, 10.0)

    def test_collect_keeps_new_pid_without_exe(self):
        proc = FakeProcess(7, "new.exe")
        with patch("src.main.psutil.process_iter", return_value=[proc]):
            collected = self.plugin._collect_processes({})

        self.assertEqual(proc.exe_calls, 0)
        self.assertEqual(collected[7].name, "new.exe")
        self.assertEqual(collected[7].exe_path, "")

    def test_empty_query_returns_top_memory_processes(self):
        self.plugin._processes = {pid: _info(pid, f"proc{pid}.exe", float(pid)) for pid in range(1, 26)}

        selected = self.plugin._select_processes("")
        self.assertEqual(len(selected), _RESULT_LIMIT)
        self.assertEqual([item.pid for item in selected], list(range(25, 5, -1)))

    def test_search_returns_top_memory_matches(self):
        self.plugin._processes = {
            1: _info(1, "chrome.exe", 800, friendly_name="Google Chrome"),
            2: _info(2, "code.exe", 400, exe_path="C:\\Apps\\Code\\code.exe"),
            3: _info(3, "notepad.exe", 20),
            **{pid: _info(pid, "chrome.exe", float(pid), friendly_name="Chrome") for pid in range(10, 40)},
        }

        by_name = self.plugin._select_processes("chrome")
        self.assertEqual(len(by_name), _RESULT_LIMIT)
        self.assertEqual(by_name[0].pid, 1)
        self.assertEqual(by_name[1].pid, 39)

        by_path = self.plugin._select_processes("apps\\code")
        self.assertEqual([item.pid for item in by_path], [2])

    def test_build_result_does_not_need_translation_rpc(self):
        proc = _info(9, "chrome.exe", 512.4, friendly_name="Chrome")
        result = self.plugin._build_result(proc, "")
        self.assertEqual(result.title, "Chrome")
        self.assertEqual(result.score, 512)
        self.assertEqual(len(result.tails), 2)
        self.assertIn("9", result.tails[0].text)
        self.assertIn("512.4", result.tails[1].text)


class TestProcessNameResolver(unittest.TestCase):
    def test_desktop_content_maps_exec_basename(self):
        content = "[Desktop Entry]\nName=Firefox Web Browser\nExec=/usr/bin/firefox %u\n"
        mapping = ProcessNameResolver.names_from_desktop_content(content)
        self.assertEqual(mapping["firefox"], "Firefox Web Browser")

    def test_friendly_name_cache_by_pid_and_create_time(self):
        resolver = ProcessNameResolver()
        proc = FakeProcess(7, "python", exe="/usr/bin/python")

        first = resolver.get_friendly_name(proc, default_name="python", exe_path="/usr/bin/python", create_time=12.0)
        second = resolver.get_friendly_name(proc, default_name="changed", exe_path="/tmp/other", create_time=12.0)
        self.assertEqual(first, second)

        resolver.prune(set())
        self.assertEqual(resolver._cache, {})


if __name__ == "__main__":
    unittest.main()
