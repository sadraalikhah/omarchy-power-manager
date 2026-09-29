import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class SafetyTests(unittest.TestCase):
    def test_charge_limit_rejects_out_of_range_and_ambiguous_numbers(self):
        # Simulate the root boundary only. Invalid arguments must stop before sysfs writes.
        harness = 'id() { printf "0\\n"; }; source "$1" "$2" "$3" "$4"'
        with tempfile.TemporaryDirectory() as directory:
            for value in ("-1", "101", "1000", "08", "0100", "nan"):
                result = subprocess.run(["bash", "-c", harness, "bash", str(ROOT / "scripts/power-manager-limit"), value,
                                         directory, str(Path(directory) / "persistence")], capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0, value)
                self.assertIn("Invalid limit format", result.stdout, value)

    def test_charge_limit_cannot_write_arbitrary_files(self):
        harness = 'id() { printf "0\\n"; }; source "$1" 80 "$2" "$3"'
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "not-a-battery"
            target.mkdir()
            threshold = target / "charge_control_end_threshold"
            threshold.write_text("100\n")
            persistence = Path(directory) / "not-a-system-rule"
            result = subprocess.run(["bash", "-c", harness, "bash", str(ROOT / "scripts/power-manager-limit"),
                                     str(target), str(persistence)], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(threshold.read_text(), "100\n")
            self.assertFalse(persistence.exists())

    def execute_apply(self, directory, helper=None):
        apply = directory / "power-manager-apply"
        apply.write_bytes((ROOT / "scripts/power-manager-apply").read_bytes())
        apply.chmod(0o755)
        if helper is not None:
            switch = directory / "power-manager-profile-switch"
            switch.write_text(helper)
            switch.chmod(0o755)
        config = directory / "settings.json"
        config.write_text('{"enabled":true}')
        env = dict(os.environ, OMARCHY_UDEV_DIR=str(directory / "udev"))
        return subprocess.run([str(apply), str(config)], capture_output=True, text=True, env=env)

    def test_apply_reports_failure_when_helper_is_missing(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            result = self.execute_apply(directory)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn('"success": true', result.stdout)
            self.assertFalse((directory / "udev").exists())

    def test_apply_preserves_helper_failure_status(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = self.execute_apply(Path(temporary), "#!/bin/sh\nexit 42\n")
            self.assertEqual(result.returncode, 42)
            self.assertNotIn('"success": true', result.stdout)


if __name__ == "__main__":
    unittest.main()
