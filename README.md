# Warehouse Dashboard System

Fullscreen Raspberry Pi warehouse job board plus a PC management app. The PC manager stores Current RMS details locally, serves dashboard data to multiple Pis, and controls which screen each Pi shows.

## What This Contains
- `manager_app/`: PC management app and local Flask server for Pi connections and Current RMS data.
- `pi_viewer.py`: PySide6 fullscreen dashboard showing today, tomorrow, prep, outstanding items, and notifications.
- `pi_agent.py`: Background Pi agent that registers the screen and accepts screen/restart/reboot commands.
- `pi_update_window.py`: Fullscreen Pi update progress window shown when an update is being applied.
- `scripts/install_pi.sh`: Raspberry Pi installer that creates services and the local Python environment.
- `scripts/update_pi.sh`: Git-based updater modelled on the noticeboard app.

## PC Manager Setup
On Windows, double-click `Warehouse Manager.vbs` from the project folder. It creates `.venv`, installs the PC dependencies, starts the local API server, and opens the manager window.

Use the manager tabs:

- `Connection`: shows the PC addresses that Pis should connect to.
- `Current RMS`: enter the API base URL, subdomain, API key, view IDs, and any prep item exclusions.
- `Alerts`: configure update polling, quiet hours, popup behavior, and alert sounds for each event type.
- `Pi Screens`: shows every registered Pi and lets you switch selected Pis between Today, Tomorrow, Prep, Outstanding, and Notifications.

There is deliberately no update tab. Code updates are handled by Git on the Pi during boot/reboot and by the updater service.

The manager is expected to stay open because it serves the live dashboard data to the Pis. If it exits unexpectedly, the launcher restarts it automatically. To close it deliberately, close the window and confirm the prompt.

## Local Secrets
Current RMS credentials are not stored in committed files. The manager writes real API settings to:

```text
manager_data/settings.json
```

`manager_data/` is ignored by Git. `manager_settings.example.json` is only a blank reference file.

## Raspberry Pi Setup
Clone the GitHub repo onto each Pi, then run the installer with the PC manager IP shown in the Connection tab:

```bash
git clone https://github.com/demiwidget/warehouse-job-display.git ~/warehouse-job-display
cd ~/warehouse-job-display/scripts
chmod +x install_pi.sh
WAREHOUSE_MANAGER_IP=YOUR_PC_MANAGER_IP WAREHOUSE_MANAGER_PORT=8765 ./install_pi.sh
```

Useful checks:

```bash
sudo systemctl status warehouse-viewer.service
sudo systemctl status warehouse-agent.service
sudo journalctl -u warehouse-viewer -u warehouse-agent -f
```

## Auto Updates
This now follows the same broad update pattern as the noticeboard app:

- The Pi runs from a Git clone rather than copied files.
- `scripts/install_pi.sh` installs an update-on-boot service and a `warehouse-update.timer`.
- On reboot, the Pi checks GitHub, pulls clean fast-forward updates, reruns the installer, and restarts services.
- When an update is found, the Pi shows a full-screen `Updating` window with live status and step progress.
- The timer also checks every 6 hours as a safety net.
- If tracked local files on the Pi have been edited, auto-update is skipped to avoid overwriting work.

Manual update:

```bash
~/warehouse-job-display/scripts/update_pi.sh --restart-display
```

## Pi Audio
Pi alert sounds default to the attached HDMI screen output. The installer writes this into `viewer_config.json`, and the viewer reapplies the preferred sink on startup so sound stays on the screen after reboots.

## Manager Pi Trial
The normal PC manager still works as before. For a trial split, install a spare Raspberry Pi as an always-on Manager Pi:

```bash
WAREHOUSE_REBOOT_AFTER_INSTALL=1 bash -c "$(curl -fsSL https://raw.githubusercontent.com/demiwidget/warehouse-job-display/main/scripts/bootstrap_manager_pi.sh || wget -qO- https://raw.githubusercontent.com/demiwidget/warehouse-job-display/main/scripts/bootstrap_manager_pi.sh)"
```

After it reboots, the Manager Pi status display shows the URL and PC Login Code. On the PC, run `Warehouse Remote Manager.vbs` for the normal no-command-window app launcher, or run `scripts/create_remote_manager_shortcut.ps1` once to create a desktop shortcut. The first successful login is remembered locally under your Windows user profile, so you should not need to enter the Manager Pi address every time. `Warehouse Remote Manager.cmd` is kept as a troubleshooting launcher if you ever need to see command output.

Display Pis can then be installed or repointed with the live install commands shown in the PC manager Connection page, using the Manager Pi IP instead of the PC IP.

## Custom Sounds
Use `.wav` files for reliable Pi playback. In the manager `Alerts` tab, use `Import WAV Sound` to copy a sound into the repo's `sounds/` folder, then use that filename in the relevant alert sound box.

The manager serves sounds to the Pis on demand. When a Pi receives an alert, it asks the manager for the named `.wav` file and refreshes its local copy before playing it. Keep filenames exact, for example `job-tomorrow.wav` and `job-tomorow.wav` are different files.

For permanent rollout to new/rebuilt Pis, commit and push custom sound files to GitHub as well.

## Local Files Not Committed
Device-specific and generated files are intentionally ignored:

- `viewer_config.json`
- `.venv/`
- `warehouse_env/`
- `warehouse_pi/`
- `warehouse_update_extract/`
- `warehouse_update.zip`
- `viewer.log`
