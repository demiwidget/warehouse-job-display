# Warehouse Dashboard System

Always-on Raspberry Pi warehouse dashboard system for Current RMS job information.

The current production layout is:

- `Manager Pi`: always-on backend that talks to Current RMS, detects alerts, stores settings, serves screens, and controls display Pis.
- `PC remote app`: Windows control panel for settings, alerts, Pi controls, Manager Pi controls, and install commands.
- `Display Pis`: fullscreen dashboard screens connected to the Manager Pi.

## Files

- `manager_app/`: shared manager UI, remote API client, backend state, Current RMS integration, and Flask server.
- `manager_status_display.py`: small touchscreen status display for the Manager Pi.
- `pi_viewer.py`: fullscreen dashboard app for display Pis.
- `pi_agent.py`: display Pi background agent for registration, commands, updates, reboot/restart, and alerts.
- `pi_update_window.py`: fullscreen update progress window for display Pis.
- `scripts/bootstrap_manager_pi.sh`: live Manager Pi installer.
- `scripts/bootstrap_pi.sh`: live display Pi installer.
- `scripts/install_manager_pi.sh`: Manager Pi service/runtime installer.
- `scripts/install_pi.sh`: display Pi service/runtime installer.
- `scripts/update_manager_pi.sh`: Manager Pi GitHub update service target.
- `scripts/update_pi.sh`: display Pi GitHub updater.
- `scripts/reset_manager_password.sh`: local Manager Pi password reset helper.
- `Warehouse Remote Manager.vbs`: normal no-command-window PC remote launcher.
- `Warehouse Remote Manager.cmd`: troubleshooting PC remote launcher with visible command output.

## Manager Pi Install

Run this on the Manager Pi:

```bash
WAREHOUSE_REBOOT_AFTER_INSTALL=1 bash -c "$(curl -fsSL https://raw.githubusercontent.com/demiwidget/warehouse-job-display/main/scripts/bootstrap_manager_pi.sh || wget -qO- https://raw.githubusercontent.com/demiwidget/warehouse-job-display/main/scripts/bootstrap_manager_pi.sh)"
```

After reboot, the Manager Pi screen shows its URL. It does not show the password.

If the password is lost, reset it from a terminal on the Manager Pi:

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/demiwidget/warehouse-job-display/main/scripts/reset_manager_password.sh || wget -qO- https://raw.githubusercontent.com/demiwidget/warehouse-job-display/main/scripts/reset_manager_password.sh)"
```

## PC Remote App

On Windows, run `Warehouse Remote Manager.vbs` for the normal app launcher.

Optional: create a desktop shortcut once:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\create_remote_manager_shortcut.ps1
```

The PC app remembers the Manager Pi address locally, but asks for the Manager Pi password each time. Use the `Manager Pi` tab to change the password, update/reboot/restart the Manager Pi, and check GitHub update status.

## Display Pi Install

Use the live command shown in the PC app `Connection` tab, or run this on each display Pi with the Manager Pi IP:

```bash
WAREHOUSE_MANAGER_IP=192.168.1.179 WAREHOUSE_MANAGER_PORT=8765 WAREHOUSE_OVERWRITE_OLD_SYSTEM=1 WAREHOUSE_REBOOT_AFTER_INSTALL=1 bash -c "$(curl -fsSL https://raw.githubusercontent.com/demiwidget/warehouse-job-display/main/scripts/bootstrap_pi.sh || wget -qO- https://raw.githubusercontent.com/demiwidget/warehouse-job-display/main/scripts/bootstrap_pi.sh)"
```

## Updates

- Manager Pi checks GitHub on boot and can be updated from the PC app `Manager Pi` tab.
- Display Pis check GitHub on boot and via timer.
- Display Pis show a fullscreen update progress window during updates.
- The PC remote launcher pulls GitHub updates before opening.

## Sounds

Use `.wav` files for reliable Pi playback. In the PC app `Alerts` tab, use `Import WAV Sound` to upload a sound to the Manager Pi. The Manager Pi serves sounds to display Pis on demand.

For permanent rollout to new/rebuilt Pis, commit and push custom sound files to GitHub as well.

## Secrets And Local Data

Real Current RMS credentials, device lists, logs, passwords, and generated runtime files are not committed. They live under ignored local paths such as:

- `manager_data/`
- `viewer_config.json`
- `.venv/`
- `warehouse_env/`
- `warehouse_pi/`
- `warehouse_update_extract/`
- `warehouse_update.zip`
- `*.log`
