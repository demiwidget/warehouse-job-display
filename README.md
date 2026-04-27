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

## Local Files Not Committed
Device-specific and generated files are intentionally ignored:

- `viewer_config.json`
- `.venv/`
- `warehouse_env/`
- `warehouse_pi/`
- `warehouse_update_extract/`
- `warehouse_update.zip`
- `viewer.log`
