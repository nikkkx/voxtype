#!/usr/bin/env bash
set -e

# WhisperFlow Arch Linux Installer
# Sets up local faster-whisper push-to-talk voice typing.

GREEN="\033[1;32m"
BLUE="\033[1;34m"
YELLOW="\033[1;33m"
RED="\033[1;31m"
RESET="\033[0m"

echo -e "${BLUE}======================================================${RESET}"
echo -e "${GREEN}      WhisperFlow Arch Linux Installer               ${RESET}"
echo -e "${BLUE}======================================================${RESET}"

# 1. Dependency checks
echo -e "\n[*] Checking system dependencies..."

check_cmd() {
    if ! command -v "$1" >/dev/null 2>&1; then
        echo -e "${RED}[!] Missing required tool: $1${RESET}"
        echo -e "    Please install it using pacman:"
        echo -e "    sudo pacman -S $2"
        exit 1
    else
        echo -e "    [✓] $1 found"
    fi
}

check_cmd python3 python
check_cmd pw-record pipewire
check_cmd pw-play pipewire
check_cmd wl-copy wl-clipboard
check_cmd notify-send libnotify

# 2. Setup directories
APP_DIR="$HOME/.local/share/whisperflow"
BIN_DIR="$HOME/.local/bin"
CONFIG_DIR="$HOME/.config/whisperflow"
SYSTEMD_DIR="$HOME/.config/systemd/user"

mkdir -p "$APP_DIR" "$BIN_DIR" "$CONFIG_DIR" "$SYSTEMD_DIR"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 3. Create Python Virtual Environment
VENV_DIR="$APP_DIR/venv"
if [ ! -d "$VENV_DIR" ]; then
    echo -e "\n[*] Creating Python virtual environment in $VENV_DIR..."
    python3 -m venv "$VENV_DIR"
else
    echo -e "\n[*] Existing virtual environment found in $VENV_DIR"
fi

echo -e "[*] Installing Python packages (faster-whisper, evdev, numpy)..."
"$VENV_DIR/bin/pip" install --upgrade pip --quiet
"$VENV_DIR/bin/pip" install faster-whisper evdev numpy --quiet
echo -e "    [✓] Python packages installed successfully"

# 4. Copy files
echo -e "\n[*] Copying application files..."
cp "$SCRIPT_DIR/whisperflow.py" "$APP_DIR/whisperflow.py"
chmod +x "$APP_DIR/whisperflow.py"

if [ ! -f "$CONFIG_DIR/config.json" ]; then
    cp "$SCRIPT_DIR/config.default.json" "$CONFIG_DIR/config.json"
    echo -e "    [✓] Default configuration created at $CONFIG_DIR/config.json"
else
    echo -e "    [!] Preserved existing configuration at $CONFIG_DIR/config.json"
fi

# 5. Create launcher script in ~/.local/bin
cat << 'EOF' > "$BIN_DIR/whisperflow"
#!/usr/bin/env bash
APP_DIR="$HOME/.local/share/whisperflow"
exec "$APP_DIR/venv/bin/python3" "$APP_DIR/whisperflow.py" "$@"
EOF
chmod +x "$BIN_DIR/whisperflow"
echo -e "    [✓] CLI launcher created at $BIN_DIR/whisperflow"

# 6. Install systemd user service
cp "$SCRIPT_DIR/whisperflow.service" "$SYSTEMD_DIR/whisperflow.service"
systemctl --user daemon-reload 2>/dev/null || true
echo -e "    [✓] Systemd user service installed"

# 7. Check input permissions
echo -e "\n[*] Checking input device permissions..."
if id -nG "$USER" | grep -qw "input"; then
    echo -e "    ${GREEN}[✓] User $USER is already in the 'input' group.${RESET}"
else
    echo -e "    ${YELLOW}[!] User $USER is NOT yet in the 'input' group.${RESET}"
    echo -e "    To allow WhisperFlow to detect Left Control globally without root,"
    echo -e "    please run this command:"
    echo -e "\n    ${GREEN}sudo usermod -aG input $USER${RESET}\n"
    echo -e "    Then either log out and back in, or run:"
    echo -e "    ${GREEN}newgrp input${RESET}"
    echo -e "    in your terminal before launching.\n"
fi

echo -e "${BLUE}======================================================${RESET}"
echo -e "${GREEN}      WhisperFlow installed successfully!            ${RESET}"
echo -e "${BLUE}======================================================${RESET}"
echo -e "Usage:"
echo -e "  1. Test your mic & transcription:"
echo -e "     ${GREEN}whisperflow --test-mic${RESET}"
echo -e "  2. Run in terminal:"
echo -e "     ${GREEN}whisperflow${RESET}"
echo -e "  3. Or run as a background service on login:"
echo -e "     ${GREEN}systemctl --user enable --now whisperflow${RESET}"
echo -e ""
echo -e "Push-to-talk default: Hold ${YELLOW}Left Control${RESET} to speak, release to type!"
echo -e "To customize the key or model, edit: ${YELLOW}~/.config/whisperflow/config.json${RESET}"
echo -e "${BLUE}======================================================${RESET}"
