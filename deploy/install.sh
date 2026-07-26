#!/bin/bash
set -euo pipefail
sudo apt-get update -qq
sudo apt-get install -y -qq python3-pygame python3-venv python3-requests python3-flask fonts-noto-cjk
cd /home/kevin/deskbar
if [ ! -d .venv ]; then python3 -m venv --system-site-packages .venv; fi
.venv/bin/pip install -q -r requirements.txt
sudo cp deploy/deskbar.service /etc/systemd/system/deskbar.service
sudo systemctl daemon-reload
sudo systemctl enable deskbar
echo "install.sh 完成"
