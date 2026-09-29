import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class BackendTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.log = self.directory / "commands"
        self.supply = self.directory / "power_supply"
        for name, values in {
            "AC": {"type": "Mains", "online": "0"},
            "BAT0": {"type": "Battery", "capacity": "50"},
        }.items():
            device = self.supply / name
            device.mkdir(parents=True)
            for field, value in values.items():
                (device / field).write_text(value)
        self.settings = {
            "enabled": True, "batteryThreshold": 20,
            "profiles": {"ac": "performance", "batteryHigh": "balanced", "batteryLow": "power-saver"},
            "idle": {state: {"sleepAfterMinutes": 15, "afterSleep": "suspend-then-hibernate", "hibernateAfterMinutes": minutes}
                     for state, minutes in (("ac", 60), ("batteryHigh", 30), ("batteryLow", 10))},
            "lid": {"ignoreLidClose": False, "ac": {"action": "suspend"},
                    "batteryHigh": {"action": "suspend"}, "batteryLow": {"action": "hibernate"}},
        }
        self.config = self.directory / "settings.json"
        self.env = dict(os.environ,
                        OMARCHY_POWER_SUPPLY_PATH=str(self.supply),
                        OMARCHY_SYSTEMD_LOGIND_DIR=str(self.directory / "logind"),
                        OMARCHY_SYSTEMD_SLEEP_DIR=str(self.directory / "sleep"),
                        TEST_COMMAND_LOG=str(self.log))

    def execute(self):
        self.config.write_text(json.dumps(self.settings))
        # Functions override the script's fixed PATH without touching system tools.
        harness = '''
powerprofilesctl() { printf 'balanced\\n'; }
omarchy-powerprofiles-set() { printf '%s\\n' "$*" >> "$TEST_COMMAND_LOG"; }
systemctl() { printf 'systemctl %s\\n' "$*" >> "$TEST_COMMAND_LOG"; }
source "$1" "$2"
'''
        return subprocess.run(["bash", "-c", harness, "bash", str(ROOT / "scripts/power-manager-profile-switch"), str(self.config)],
                              capture_output=True, text=True, env=self.env)

    def test_ac_uses_native_profile_and_ac_hibernate_delay(self):
        (self.supply / "AC/online").write_text("1")
        result = self.execute()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["state"], "ac")
        self.assertIn("ac performance", self.log.read_text())
        self.assertIn("HibernateDelaySec=3600", (self.directory / "sleep/90-power-manager.conf").read_text())

    def test_battery_high_uses_its_own_hibernate_delay(self):
        result = self.execute()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["state"], "batteryHigh")
        self.assertIn("battery balanced", self.log.read_text())
        self.assertIn("HibernateDelaySec=1800", (self.directory / "sleep/90-power-manager.conf").read_text())

    def test_battery_low_uses_its_own_delay_and_lid_action(self):
        (self.supply / "BAT0/capacity").write_text("10")
        result = self.execute()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["state"], "batteryLow")
        self.assertIn("battery power-saver", self.log.read_text())
        self.assertIn("HibernateDelaySec=600", (self.directory / "sleep/90-power-manager.conf").read_text())
        rules = (self.directory / "logind/90-power-manager.conf").read_text()
        self.assertIn("HandleLidSwitch=hibernate", rules)
        self.assertIn("IdleAction=ignore", rules)
        self.assertNotIn("IdleActionSec", rules)

    def test_disabled_management_writes_no_rules(self):
        self.settings["enabled"] = False
        result = self.execute()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["reason"], "disabled")
        self.assertFalse(self.log.exists())
        self.assertFalse((self.directory / "logind").exists())

    def test_invalid_profile_is_rejected_before_commands(self):
        self.settings["profiles"]["ac"] = "performance\nInjected=yes"
        result = self.execute()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Invalid power profile", result.stderr)
        self.assertFalse(self.log.exists())

    def test_invalid_sleep_duration_is_rejected_before_rules(self):
        self.settings["idle"]["batteryHigh"]["hibernateAfterMinutes"] = -1
        result = self.execute()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Invalid sleep duration", result.stderr)
        self.assertFalse((self.directory / "logind").exists())

    def test_invalid_lid_action_is_rejected_before_rules(self):
        self.settings["lid"]["batteryHigh"]["action"] = "suspend\nInjected=yes"
        result = self.execute()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Invalid sleep action", result.stderr)
        self.assertFalse((self.directory / "logind").exists())

    def test_ignore_lid_close_overrides_both_sources(self):
        self.settings["lid"]["ignoreLidClose"] = True
        result = self.execute()
        self.assertEqual(result.returncode, 0, result.stderr)
        rules = (self.directory / "logind/90-power-manager.conf").read_text()
        self.assertIn("HandleLidSwitch=ignore", rules)
        self.assertIn("HandleLidSwitchExternalPower=ignore", rules)

    def test_apply_does_not_report_success_when_profile_helper_fails(self):
        helper_directory = self.directory / "helpers"
        helper_directory.mkdir()
        apply = helper_directory / "power-manager-apply"
        apply.write_bytes((ROOT / "scripts/power-manager-apply").read_bytes())
        apply.chmod(0o755)
        switch = helper_directory / "power-manager-profile-switch"
        switch.write_text("#!/bin/sh\nexit 42\n")
        switch.chmod(0o755)
        self.config.write_text(json.dumps(self.settings))
        env = dict(self.env, OMARCHY_UDEV_DIR=str(self.directory / "udev"))
        result = subprocess.run([str(apply), str(self.config)], capture_output=True, text=True, env=env)
        self.assertEqual(result.returncode, 42)
        self.assertNotIn('"success": true', result.stdout)


if __name__ == "__main__":
    unittest.main()
