# Warehouse Dashboard System

Fullscreen Raspberry Pi dashboard for warehouse job boards fed by a local manager/API service that exposes Current RMS job information.

## What This Contains
- `pi_viewer.py`: PySide6 fullscreen dashboard showing today, tomorrow, prep, outstanding items, and notifications.
- `pi_agent.py`: Background agent that registers the screen, accepts remote commands, and triggers updates/restarts.
- `scripts/install_pi.sh`: Raspberry Pi installer that creates services and the local Python environment.
- `scripts/update_pi.sh`: Git-based updater modelled on the noticeboard app.

## Expected Manager API
The viewer expects a manager server such as `http://192.168.1.90:8765` with these endpoints:

- `POST /register`: records each screen with id, name, current screen, and version.
- `GET /poll/<device_id>`: returns commands such as `set_screen`, `restart`, `reboot`, or `update`.
- `GET /screen/today`
- `GET /screen/tomorrow`
- `GET /screen/prep`
- `GET /screen/outstanding`
- `GET /screen/notifications`

The Current RMS import/backend code is not currently in this folder; this repository is the Pi display/client side.

## Raspberry Pi Setup
Clone the GitHub repo onto the Pi, then run the installer:

```bash
git clone https://github.com/demiwidget/warehouse-dashboard-system.git ~/warehouse-dashboard-system
cd ~/warehouse-dashboard-system/scripts
chmod +x install_pi.sh
./install_pi.sh
```

To point at a different manager host during install:

```bash
WAREHOUSE_MANAGER_IP=192.168.1.90 WAREHOUSE_MANAGER_PORT=8765 ./install_pi.sh
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
- `scripts/install_pi.sh` installs a `warehouse-update.timer`.
- The timer checks GitHub every 6 hours, pulls clean fast-forward updates, reruns the installer, and restarts services.
- If tracked local files on the Pi have been edited, auto-update is skipped to avoid overwriting work.
- A manager command with `{"action": "update"}` starts `warehouse-refresh.service`, which checks GitHub immediately and restarts the viewer.

Manual update:

```bash
~/warehouse-dashboard-system/scripts/update_pi.sh --restart-display
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
