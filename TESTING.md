# Testing

Run the regression suite without changing hardware or system configuration:

```bash
python3 -m unittest discover -s tests -v
node --check Model.js
bash -n scripts/power-manager-apply scripts/power-manager-limit scripts/power-manager-profile-switch
```

GitHub Actions runs these checks with read-only repository access.

In an Omarchy Wayland session, run the panel smoke test:

```bash
python3 tests/qml_smoke.py
python3 tests/qml_smoke.py /tmp/power-manager-preview.png
```

The smoke test creates temporary settings with management disabled. It loads
two panel instances, checks menu routing, and optionally captures the rendered
card. It does not change your settings, profiles, brightness, or sleep rules.
The panel briefly appears and closes after the check. Shared shell imports and
the test's detached widget instances can produce warnings; the pass marker is
the assertion result, not a claim that every QML warning was eliminated.

These checks do not test real privileged writes, firmware charge-limit support,
or suspend/resume. Test those integrations before changing their behavior.
