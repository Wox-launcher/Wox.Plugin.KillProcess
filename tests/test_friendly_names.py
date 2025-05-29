import platform
import unittest

import psutil

from src.process_name_resolver import ProcessNameResolver


class TestProcessNameResolver(unittest.TestCase):
    def setUp(self):
        self.resolver = ProcessNameResolver()

    def test_friendly_name_differences(self):
        """Test that get_friendly_name actually returns different names for some processes"""
        print(f"\nRunning on: {platform.system()}")

        print("\nListing all processes and their friendly names:")
        print("-" * 100)
        print(f"{'PID':<10} {'Original Name':<30} {'Friendly Name':<40} {'Changed':<10}")
        print("-" * 100)

        found_different_name = False
        processes_checked = 0
        different_checked = 0

        for proc in psutil.process_iter(["pid", "name", "exe", "cmdline"]):
            try:
                proc_info = proc.as_dict(attrs=["pid", "name"])
                original_name = proc_info["name"]
                friendly_name = self.resolver.get_friendly_name(proc)
                changed = "✓" if original_name != friendly_name else ""
                print(f"{proc.pid:<10} {original_name:<30} {friendly_name:<40} {changed:<10}")
                processes_checked += 1

                if original_name != friendly_name:
                    found_different_name = True
                    different_checked += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess) as e:
                print(f"Error accessing PID {proc.pid}: {type(e).__name__}")
                continue

        print(f"\nProcesses checked: {processes_checked}")
        print(f"Different names checked: {different_checked}")

        self.assertTrue(
            found_different_name,
            "No processes were found with different friendly names. The friendly name resolver might not be working correctly.",
        )


if __name__ == "__main__":
    unittest.main()
