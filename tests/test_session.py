import base64
import copy
import importlib.machinery
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/power-manager-session"
loader = importlib.machinery.SourceFileLoader("power_session", str(SCRIPT))
spec = importlib.util.spec_from_loader(loader.name, loader)
session = importlib.util.module_from_spec(spec)
loader.exec_module(session)


def config():
    return {
        "enabled": True,
        "profiles": {"ac": "balanced", "batteryHigh": "power-saver", "batteryLow": "power-saver"},
        "hardware": {"gpuAuto": True, "gpuAc": "hybrid", "gpuBattery": "integrated",
                     "refreshAuto": True, "refreshAc": 144, "refreshBattery": 60},
        "brightness": {"auto": True, "ac": 80, "batteryHigh": 50, "batteryLow": 30},
    }


def actual():
    return {
        "gpu": "hybrid", "refresh": 144, "brightness": 80,
        "monitor": {"name": "eDP-1", "width": 1920, "height": 1080,
                    "x": 200, "y": 100, "scale": 1.25, "transform": 0,
                    "availableModes": ["1920x1080@144.00Hz", "1920x1080@60.00Hz"]},
    }


class SessionTests(unittest.TestCase):
    def apply(self, settings, state, hardware=None, ultimate=False):
        calls = []
        with patch.object(session, "run", side_effect=lambda *args: calls.append(args) or "ok"), \
             patch.object(session.Path, "exists", return_value=ultimate), \
             patch.object(session.Path, "read_text", return_value="0"):
            errors = session.apply(settings, state, hardware or actual())
        return calls, errors

    def test_battery_applies_gpu_display_brightness_and_native_profile(self):
        calls, errors = self.apply(config(), "batteryHigh")
        self.assertEqual(errors, [])
        self.assertIn(("cardwire", "set", "integrated"), calls)
        self.assertIn(("omarchy-brightness-display", "--no-osd", "--monitor", "eDP-1", "50%"), calls)
        self.assertIn(("omarchy-powerprofiles-set", "battery", "power-saver"), calls)
        code = next(call[2] for call in calls if call[0] == "hyprctl")
        for expected in ('1920x1080@60.00', 'position = "200x100"', 'scale = 1.25', 'transform = 0'):
            self.assertIn(expected, code)

    def test_ac_already_at_target_does_not_repeat_hardware_operations(self):
        calls, errors = self.apply(config(), "ac")
        self.assertEqual(errors, [])
        self.assertEqual(calls, [("omarchy-powerprofiles-set", "ac", "balanced")])

    def test_low_battery_uses_its_own_brightness(self):
        calls, _ = self.apply(config(), "batteryLow")
        self.assertIn(("omarchy-brightness-display", "--no-osd", "--monitor", "eDP-1", "30%"), calls)

    def test_disabled_hardware_preferences_leave_hardware_unchanged(self):
        settings = config()
        settings["hardware"]["gpuAuto"] = settings["hardware"]["refreshAuto"] = False
        settings["brightness"]["auto"] = False
        calls, errors = self.apply(settings, "batteryHigh")
        self.assertEqual(errors, [])
        self.assertEqual(calls, [("omarchy-powerprofiles-set", "battery", "power-saver")])

    def test_zero_brightness_means_skip(self):
        settings = config()
        settings["brightness"]["batteryHigh"] = 0
        calls, _ = self.apply(settings, "batteryHigh")
        self.assertFalse(any(call[0] == "omarchy-brightness-display" for call in calls))

    def test_ultimate_gpu_mode_requires_consent_instead_of_live_switch(self):
        calls, errors = self.apply(config(), "batteryHigh", ultimate=True)
        self.assertFalse(any(call[0] == "cardwire" for call in calls))
        self.assertTrue(any("restart" in error for error in errors))

    def test_unadvertised_refresh_is_rejected(self):
        settings = config()
        settings["hardware"]["refreshBattery"] = 120
        calls, errors = self.apply(settings, "batteryHigh")
        self.assertFalse(any(call[0] == "hyprctl" for call in calls))
        self.assertTrue(any("120 Hz" in error for error in errors))

    def test_rotated_display_preserves_transform_and_physical_resolution(self):
        hardware = actual()
        hardware["monitor"].update(width=1080, height=1920, transform=1)
        calls, errors = self.apply(config(), "batteryHigh", hardware)
        self.assertEqual(errors, [])
        code = next(call[2] for call in calls if call[0] == "hyprctl")
        self.assertIn("1920x1080@60.00", code)
        self.assertIn("transform = 1", code)

    def test_command_failure_is_reported(self):
        with patch.object(session, "run", side_effect=RuntimeError("denied")), \
             patch.object(session.Path, "exists", return_value=False):
            errors = session.apply(config(), "batteryHigh", actual())
        self.assertEqual(len(errors), 4)
        self.assertTrue(all("denied" in error for error in errors))

    def test_manual_changes_are_saved_for_previous_power_source(self):
        settings = config()
        changed = session.remember(settings, "ac", actual(), {"gpu": "smart", "refresh": 60, "brightness": 65})
        self.assertEqual(set(changed), {"gpu", "refresh", "brightness"})
        self.assertEqual(settings["hardware"]["gpuAc"], "smart")
        self.assertEqual(settings["hardware"]["refreshAc"], 60)
        self.assertEqual(settings["brightness"]["ac"], 65)
        self.assertEqual(settings["hardware"]["gpuBattery"], "integrated")

    def test_low_battery_brightness_does_not_replace_high_battery_value(self):
        settings = config()
        session.remember(settings, "batteryLow", {"brightness": 30}, {"brightness": 25})
        self.assertEqual(settings["brightness"]["batteryLow"], 25)
        self.assertEqual(settings["brightness"]["batteryHigh"], 50)

    def test_disabled_preferences_are_not_remembered(self):
        settings = config()
        settings["hardware"]["gpuAuto"] = settings["hardware"]["refreshAuto"] = False
        settings["brightness"]["auto"] = False
        before = copy.deepcopy(settings)
        self.assertEqual(session.remember(settings, "ac", actual(), {"gpu": "smart", "refresh": 60, "brightness": 65}), [])
        self.assertEqual(settings, before)

    def test_missing_observations_do_not_overwrite_saved_preferences(self):
        settings = config()
        before = copy.deepcopy(settings)
        self.assertEqual(session.remember(settings, "ac", actual(), {}), [])
        self.assertEqual(settings, before)

    def test_invalid_numeric_settings_fail_before_commands(self):
        for value in (True, -1, 400, "60"):
            settings = config()
            settings["hardware"]["refreshBattery"] = value
            with patch.object(session, "run") as run:
                with self.assertRaises(ValueError):
                    session.apply(settings, "batteryHigh", actual())
                run.assert_not_called()

    def test_save_cli_atomically_writes_complete_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "settings.json"
            encoded = base64.b64encode(json.dumps(config()).encode()).decode()
            result = subprocess.run([str(SCRIPT), "save", str(target), encoded], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertEqual(json.loads(target.read_text()), config())
            self.assertEqual(json.loads(result.stdout)["settings"], config())
            self.assertEqual(sorted(path.name for path in target.parent.iterdir()), ["settings.json", "settings.json.lock"])


if __name__ == "__main__":
    unittest.main()
