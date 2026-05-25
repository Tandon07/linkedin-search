#!/usr/bin/env bash
# ==============================================================================
# LinkedIn Job Automator - Ubuntu VM Provisioning Script
# ==============================================================================
# This script automates setting up a headless browser environment, python, and 
# configuring a systemd background service on a clean Ubuntu LTS Azure VM.
#
# Usage:
#   chmod +x setup_vm.sh
#   ./setup_vm.sh
# ==============================================================================

set -e # Exit immediately if a command exits with a non-zero status

# Text Formatting
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${BLUE}======================================================================${NC}"
echo -e "${BLUE}    Starting LinkedIn Job Automator VM Provisioning Script            ${NC}"
echo -e "${BLUE}======================================================================${NC}"

# Detect Directories & User
APP_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
CURRENT_USER=$(whoami)

echo -e "${GREEN}[INFO] App Directory:${NC} ${APP_DIR}"
echo -e "${GREEN}[INFO] Running as User:${NC} ${CURRENT_USER}"

# 1. Update OS package lists
echo -e "\n${YELLOW}[STEP 1] Updating system package repositories...${NC}"
sudo apt-get update -y

# 2. Install basic system dependencies
echo -e "\n${YELLOW}[STEP 2] Installing essential system software...${NC}"
sudo apt-get install -y python3 python3-pip python3-venv git curl unzip wget libxi6 libnss3

# 3. Install Google Chrome Stable (headless engine)
echo -e "\n${YELLOW}[STEP 3] Installing Google Chrome Stable...${NC}"
if ! command -v google-chrome &> /dev/null; then
    wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | sudo gpg --dearmor -o /usr/share/keyrings/googlechrome-keyring.gpg
    echo "deb [arch=amd64 signed-by=/usr/share/keyrings/googlechrome-keyring.gpg] http://dl.google.com/linux/chrome/deb/ stable main" | sudo tee /etc/apt/sources.list.d/google-chrome.list
    sudo apt-get update -y
    sudo apt-get install -y google-chrome-stable
    echo -e "${GREEN}[OK] Google Chrome Stable installed successfully.${NC}"
else
    echo -e "${GREEN}[OK] Google Chrome is already installed.${NC}"
fi

# 4. Setup Python Virtual Environment
echo -e "\n${YELLOW}[STEP 4] Setting up Python virtual environment...${NC}"
if [ ! -d "${APP_DIR}/venv" ]; then
    python3 -m venv "${APP_DIR}/venv"
    echo -e "${GREEN}[OK] Virtual environment created.${NC}"
else
    echo -e "${GREEN}[OK] Virtual environment already exists.${NC}"
fi

# Activate virtualenv and install pip dependencies
echo -e "${YELLOW}[INFO] Installing pip requirements...${NC}"
"${APP_DIR}/venv/bin/pip" install --upgrade pip
"${APP_DIR}/venv/bin/pip" install -r "${APP_DIR}/requirements.txt"
echo -e "${GREEN}[OK] Python packages installed successfully.${NC}"

# 5. Create the systemd Service
echo -e "\n${YELLOW}[STEP 5] Configuring systemd background service...${NC}"
SERVICE_FILE="/etc/systemd/system/linkedin-automator.service"

sudo bash -c "cat > ${SERVICE_FILE}" <<EOF
[Unit]
Description=LinkedIn Job Application Automator Daemon
After=network.target

[Service]
Type=simple
User=${CURRENT_USER}
WorkingDirectory=${APP_DIR}
ExecStart=${APP_DIR}/venv/bin/python main.py
Restart=always
RestartSec=15
StandardOutput=syslog
StandardError=syslog
SyslogIdentifier=linkedin-automator

[Install]
WantedBy=multi-user.target
EOF

echo -e "${GREEN}[OK] systemd service file created at ${SERVICE_FILE}.${NC}"

# 6. Reload systemd and enable service
echo -e "\n${YELLOW}[STEP 6] Enabling and starting the background service...${NC}"
sudo systemctl daemon-reload
sudo systemctl enable linkedin-automator.service

echo -e "${BLUE}======================================================================${NC}"
echo -e "${GREEN}    Provisioning Completed Successfully!                              ${NC}"
echo -e "${BLUE}======================================================================${NC}"
echo -e "\n${YELLOW}Next Steps Reminder:${NC}"
echo -e " 1. Make sure to fill in your private configurations in ${GREEN}${APP_DIR}/.env${NC} on the VM."
echo -e " 2. To start the background service, run:"
echo -e "    ${BLUE}sudo systemctl start linkedin-automator.service${NC}"
echo -e " 3. To view running logs in real-time, run:"
echo -e "    ${BLUE}journalctl -u linkedin-automator.service -f -n 50${NC}"
echo -e " 4. To stop the service, run:"
echo -e "    ${BLUE}sudo systemctl stop linkedin-automator.service${NC}"
echo -e "${BLUE}======================================================================${NC}"
