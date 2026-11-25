# 🎙️ WhisperFlow (Cross-Platform)

A lightweight, push-to-talk voice-to-text typing tool for **Linux (Arch, Ubuntu, Fedora, etc.)**, **Windows**, and **macOS**, inspired by Wispr Flow.

It runs **100% locally** on your PC using [`faster-whisper`](https://github.com/SYSTRAN/faster-whisper), capturing speech while you hold down a key (default: **Right Alt**) and typing the transcribed text directly at your cursor the moment you release it.

---

## ✨ Features

- **Push-to-Talk (Hold-to-Talk)**: Hold down **Right Alt** (near the spacebar/arrow keys) to speak, release to type.
- **Voice Punctuation & Newlines**: Say *"comma"*, *"period"*, *"question mark"*, or *"new line"* and it formats cleanly.
- **Voice Clipboard & Actions**: Say *"paste it"* to paste copied text, *"undo"* for `Ctrl+Z`, *"select all"* for `Ctrl+A`.
- **Custom Snippets**: Define custom triggers like saying *"my email"* to insert your actual email address.
- **KDE System Tray Icon**: Sleek mic icon in your KDE panel (blue when ready, glowing red when recording).
- **Smart Shortcut Passthrough**: Preserves standard shortcuts (e.g., `Ctrl+C`, `Ctrl+V`, `Ctrl+Tab`).
- **100% Local & Fast**: Runs `faster-whisper` with `int8` quantization on your CPU (typically 100–300ms for short sentences). Zero external cloud dependencies.
- **Wayland & X11 Native**: Uses `wl-copy` + `evdev.UInput` for instant UTF-8 pasting.
- **Auto-Submit Option**: Configurable option to automatically press `Enter` after typing (ideal for chat apps and AI prompts).
- **Subtle Audio & Visual Feedback**: Plays gentle start/stop chimes and displays non-intrusive desktop notifications (`notify-send`).
- **Daemon / Global Shortcut Support**: Includes a Unix socket for remote triggering (`whisperflow --toggle`) to bind with KDE global shortcuts.
- **Background Systemd Service**: Easily run as a persistent background user service on login.

---

## 🚀 Quick Install

### 1. Requirements Check
The following are standard on modern Arch Linux:
- `python`
- `pipewire` (for `pw-record` and `pw-play`)
- `wl-clipboard` (for `wl-copy` and `wl-paste`)
- `libnotify` (for `notify-send`)

If any are missing:
```bash
sudo pacman -S python pipewire wl-clipboard libnotify
```

### 2. Run the Installer
```bash
cd ~/.gemini/antigravity/scratch/whisperflow-arch
./install.sh
```

The installer:
- Creates a dedicated virtual environment in `~/.local/share/whisperflow/venv`
- Installs `faster-whisper`, `evdev`, and `numpy`
- Installs the `whisperflow` command into `~/.local/bin/whisperflow`
- Creates default configuration in `~/.config/whisperflow/config.json`
- Sets up systemd user service `~/.config/systemd/user/whisperflow.service`

### 3. Grant Input Permissions (Arch Linux)
To allow reading the keyboard globally without root:
```bash
sudo usermod -aG input $USER
```
> **Note:** Apply the new group without logging out by running `newgrp input` in your terminal.

---

## 🛠️ Usage

### Test Microphone and Model
Verify your microphone and transcription in 3 seconds:
```bash
whisperflow --test-mic
```

### Run in Terminal
```bash
whisperflow
```
Now switch to any app (browser, text editor, terminal, chat), hold **Left Control**, speak, and release!

### Run as a Background Service
To have WhisperFlow start automatically on login:
```bash
systemctl --user enable --now whisperflow
```
To view logs or stop:
```bash
journalctl --user -u whisperflow -f
systemctl --user stop whisperflow
```

---

## ⚙️ Configuration

Settings are saved in `~/.config/whisperflow/config.json`:

```json
{
  "key": "KEY_LEFTCTRL",
  "model": "base.en",
  "device": "cpu",
  "compute_type": "int8",
  "language": "en",
  "auto_submit": false,
  "sound_feedback": true,
  "notifications": true,
  "min_hold_seconds": 0.25,
  "paste_delay": 0.05,
  "restore_clipboard": true
}
```

### Options Breakdown:
| Option | Default | Description |
| :--- | :--- | :--- |
| `key` | `"KEY_LEFTCTRL"` | Push-to-talk trigger key (e.g., `KEY_RIGHTCTRL`, `KEY_LEFTALT`, `KEY_CAPSLOCK`, `KEY_F8`). |
| `model` | `"base.en"` | Faster-whisper model: `tiny.en` (ultra-fast), `base.en` (balanced), `small.en` (high accuracy), or multilingual `base`/`small`. |
| `device` | `"cpu"` | `cpu` or `cuda` (if NVIDIA GPU driver is configured). |
| `compute_type` | `"int8"` | `int8` for CPU, `float16` for CUDA. |
| `language` | `"en"` | Language code (`en`, `auto`, `de`, `es`, `fr`, etc.). |
| `auto_submit` | `false` | When `true`, automatically presses `Enter` after typing. |
| `sound_feedback`| `true` | Plays short soft chimes when recording starts and stops. |
| `notifications` | `true` | Shows transient desktop notification banners. |
| `min_hold_seconds` | `0.25` | Minimum hold time to prevent accidental quick taps from triggering dictation. |

---

## ⌨️ Changing the Push-to-Talk Key

To see available key names:
```bash
whisperflow --list-keys
```

Popular keys:
- `KEY_LEFTCTRL` (Left Control, default)
- `KEY_RIGHTCTRL` (Right Control)
- `KEY_LEFTALT` (Left Alt)
- `KEY_RIGHTALT` (Right Alt / AltGr)
- `KEY_CAPSLOCK` (Caps Lock)
- `KEY_F8` / `KEY_F9` (Function keys)
- `KEY_GRAVE` (Tilde / Backtick `` ` ``)

You can pass `--key <KEY>` on the command line or set `"key"` in `config.json`:
```bash
whisperflow --key KEY_RIGHTCTRL
```

---

## ⚡ CLI Flags

| Flag | Description |
| :--- | :--- |
| `--key KEY` | Override trigger key for this session |
| `--model MODEL` | Choose model (`tiny.en`, `base.en`, `small.en`) |
| `--submit` | Press Enter after typing |
| `--no-submit` | Do not press Enter after typing |
| `--no-sound` | Mute audio chimes |
| `--toggle` | Toggle recording on running daemon |
| `--test-mic` | 3-second test of microphone & transcription |
| `--list-keys` | Show common key names |
| `--status` | Show daemon status |
