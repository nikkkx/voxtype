# 🎙️ VoxType

A fast, lightweight, **100% local** push-to-talk voice-to-text typing tool for **Linux**, **Windows**, and **macOS**.

Powered by [`faster-whisper`](https://github.com/SYSTRAN/faster-whisper) — hold down a key (default: **Right Alt**), speak, and release to type directly at your cursor in any app (browsers, Discord, VS Code, terminals, docs, etc.).

---

## ✨ Features

- **Push-to-Talk (Hold-to-Talk)**: Hold **Right Alt** to speak, release to type.
- **100% Local & Private**: Runs `faster-whisper` locally on your CPU (`int8` quantization) — no cloud APIs, no subscriptions.
- **Voice Punctuation & Newlines**: Say *"comma"*, *"period"*, *"question mark"*, or *"new line"* and it formats automatically.
- **Voice Clipboard & Quick Actions**: Say *"paste it"* to paste copied text, *"undo"* for `Ctrl+Z`, *"select all"* for `Ctrl+A`, *"copy that"* for `Ctrl+C`.
- **Custom Snippets**: Define voice shortcuts in `config.json` (e.g., say *"my email"* $\rightarrow$ types your email).
- **System Tray Icon**: Blue mic when ready, glowing red mic while recording.

---

## 🐧 Linux Setup (Arch, Ubuntu, Debian, Fedora)

### 1. Install System Dependencies
- **Arch Linux**:
  ```bash
  sudo pacman -S python pipewire wl-clipboard libnotify
  ```
- **Ubuntu / Debian**:
  ```bash
  sudo apt install python3 python3-venv pipewire wl-clipboard libnotify-bin
  ```
- **Fedora**:
  ```bash
  sudo dnf install python3 pipewire wl-clipboard libnotify
  ```

### 2. Clone & Install
```bash
git clone https://github.com/nikkkx/voxtype.git
cd voxtype
./install.sh
```

### 3. Grant Input Permissions (Required once for global hotkey & typing)
```bash
sudo usermod -aG input $USER
sudo setfacl -m u:$USER:rw /dev/input/event* /dev/uinput
```
*(To persist across reboots, add udev rules for `input` and `uinput`.)*

### 4. Run
```bash
whisperflow --daemon     # Run in background
whisperflow --status     # Check status
whisperflow --kill       # Stop
```

---

## 🪟 Windows Setup (Windows 10 / 11)

### 1. Prerequisites
- Install **Python 3.10+** from [python.org](https://www.python.org/downloads/) (check **"Add Python to PATH"** during install).

### 2. Clone & Install
Open **PowerShell** and run:
```powershell
git clone https://github.com/nikkkx/voxtype.git
cd voxtype
.\install.ps1
```

### 3. Run
```powershell
& "$env:LOCALAPPDATA\whisperflow\venv\Scripts\python.exe" "$env:LOCALAPPDATA\whisperflow\whisperflow.py"
```
Hold **Right Alt** anywhere, speak, and release to type!

---

## 🍎 macOS Setup

### 1. Prerequisites
- Install **Python 3.10+** and **PortAudio** (for `sounddevice`):
  ```bash
  brew install python portaudio
  ```

### 2. Clone & Install
```bash
git clone https://github.com/nikkkx/voxtype.git
cd voxtype
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Grant Permissions
On first run, macOS will ask for **Microphone** and **Accessibility** permissions (needed to detect global keys and paste with `Cmd+V`). Allow both in **System Settings → Privacy & Security**.

### 4. Run
```bash
python3 whisperflow.py
```

---

## ⚙️ Configuration

Settings are stored in `~/.config/whisperflow/config.json`:

```json
{
  "key": "KEY_RIGHTALT",
  "model": "base.en",
  "device": "cpu",
  "compute_type": "int8",
  "language": "en",
  "auto_submit": false,
  "sound_feedback": true,
  "notifications": true,
  "voice_punctuation": true,
  "tray_icon": true,
  "snippets": {
    "my email": "user@example.com",
    "my github": "https://github.com/username"
  }
}
```
