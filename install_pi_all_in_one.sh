#!/usr/bin/env bash
# Legacy installer kept for reference.
# Use scripts/install_pi.sh for GitHub-based auto-updates like the noticeboard app.
set -euo pipefail
MANAGER_IP="192.168.1.90"
MANAGER_PORT="8765"
INSTALL_DIR="$HOME/warehouse_pi"
VENV_DIR="$HOME/warehouse_env"
AUTOSTART_DIR="$HOME/.config/autostart"
AGENT_SERVICE="/etc/systemd/system/warehouse-agent.service"
sudo apt update
sudo apt install -y python3-venv python3-full curl unzip
mkdir -p "$INSTALL_DIR" "$AUTOSTART_DIR"
cp "$(dirname "$0")/pi_viewer.py" "$INSTALL_DIR/pi_viewer.py"
cp "$(dirname "$0")/pi_agent.py" "$INSTALL_DIR/pi_agent.py"
if [ ! -d "$VENV_DIR" ]; then
  python3 -m venv "$VENV_DIR"
fi
"$VENV_DIR/bin/pip" install --upgrade pip
"$VENV_DIR/bin/pip" install PySide6 requests
HOSTNAME_VALUE="$(hostname)"
cat > "$INSTALL_DIR/viewer_config.json" <<EOF
{
  "server": "http://${MANAGER_IP}:${MANAGER_PORT}",
  "device_id": "${HOSTNAME_VALUE}",
  "device_name": "${HOSTNAME_VALUE}",
  "version": "1.0.0",
  "screen": "today",
  "allow_all_screens": true
}
EOF
cat > "$AUTOSTART_DIR/warehouse-viewer.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Warehouse Viewer
Exec=${VENV_DIR}/bin/python ${INSTALL_DIR}/pi_viewer.py
Path=${INSTALL_DIR}
Terminal=false
X-GNOME-Autostart-enabled=true
EOF
sudo bash -c "cat > ${AGENT_SERVICE}" <<EOF
[Unit]
Description=Warehouse Agent
After=network-online.target
Wants=network-online.target

[Service]
User=${USER}
WorkingDirectory=${INSTALL_DIR}
ExecStart=${VENV_DIR}/bin/python ${INSTALL_DIR}/pi_agent.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable warehouse-agent
sudo systemctl restart warehouse-agent || sudo systemctl start warehouse-agent
pkill -f pi_viewer.py || true
DISPLAY=:0 XAUTHORITY="$HOME/.Xauthority" nohup "${VENV_DIR}/bin/python" "${INSTALL_DIR}/pi_viewer.py" >/tmp/warehouse_viewer_install.log 2>&1 &
echo "Install complete. Reboot once to confirm autostart."
