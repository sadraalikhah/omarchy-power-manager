# Omarchy Power Manager Development

## Architecture

- **Frontend**: `Panel.qml`. Uses native components (`CustomDropdown`, `CustomNumberField`, `CustomButton`).
- **State**: `Model.js` defines defaults. The panel loads `~/.config/onlyvishesh.power-manager.json` and keeps unsaved edits separate from active settings.
- **Desktop policy**: `scripts/power-manager-session` applies and remembers per-source GPU, display, brightness, and native Omarchy power profiles. It saves settings atomically under a file lock and runs as the desktop user.
- **Idle sleep**: `Panel.qml` uses `Quickshell.Wayland.IdleMonitor`, Omarchy's stay-awake indicator, and systemd inhibitor checks. Omarchy owns lock and screensaver timing.
- **Backend**: `scripts/power-manager-profile-switch` updates privileged lid and hibernation rules. It leaves systemd idle actions disabled and delegates native profile changes to the desktop user.
- **Elevation**: `scripts/power-manager-apply`. Triggered via `pkexec` for zero-sandbox-violation logind overrides.

## Customize UI

1. **Inject State**: Add the default variable to `defaultConfig()` inside `Model.js`.
2. **Bind Component**: In `Panel.qml`, implement a Custom component bound to `root.getVal` and `root.setVal`.
3. **Verify Stability**: Run `omarchy restart shell`.
   - _Completion Criterion_: `journalctl -t omarchy-shell -n 50` shows zero QML syntax warnings or errors.

## Diagnose Sleep Failures

Execute the branch matching the failure:

### Branch: Lid Rules Ignored

1. Check `cat /etc/systemd/logind.conf.d/90-power-manager.conf`.
2. If missing, instruct user to click "Apply Rules" via the UI to trigger the Polkit elevation.
3. Check `journalctl -t power-manager-udev` for headless execution crashes.

### Branch: NVIDIA Hibernation Veto

When `suspend-then-hibernate` throws `Operation not permitted`:

1. Force VRAM preservation: Write `options nvidia NVreg_PreserveVideoMemoryAllocations=1` to `/etc/modprobe.d/99-nvidia-hibernate.conf` via `pkexec`.
2. Enable NVIDIA hooks: `systemctl enable nvidia-suspend nvidia-hibernate nvidia-resume` via `pkexec`.
   - _Completion Criterion_: `cat /etc/modprobe.d/99-nvidia-hibernate.conf` returns 1, and `systemctl is-enabled` returns enabled for all three services.

## Contribution Pipeline

1. Clone branch.
2. Apply changes following zero-sandbox-violation rules.
3. Run UI stability verification.
4. Run `python3 -m unittest discover -s tests -v` and check the commit diff.
5. Follow the user's requested review and approval process before publishing commits or a pull request.
