#!/usr/bin/env python3
"""
WhisperFlow Arch - Simple, fast, local voice-to-text typing tool for Arch Linux.
Uses faster-whisper with local models and push-to-talk key holding.
"""

import os
import sys
import re
import time
import json
import wave
import shutil
import signal
import select
import socket
import argparse
import threading
import subprocess
from pathlib import Path
from typing import Optional, List, Dict, Any

import numpy as np

IS_LINUX = sys.platform.startswith("linux")
IS_WINDOWS = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"

# Lazy imports for fast startup when querying status/toggle
evdev = None
ecodes = None
WhisperModel = None
pynput_keyboard = None
sd = None
pyperclip = None


def ensure_imports():
    global evdev, ecodes, WhisperModel, pynput_keyboard, sd, pyperclip
    if IS_LINUX and evdev is None:
        try:
            import evdev as _evdev
            from evdev import ecodes as _ecodes
            evdev = _evdev
            ecodes = _ecodes
        except ImportError:
            pass

    if not IS_LINUX or evdev is None:
        if pynput_keyboard is None:
            try:
                from pynput import keyboard as _pk
                pynput_keyboard = _pk
            except ImportError:
                sys.exit("[ERROR] Missing 'pynput'. Run: pip install pynput")
        if sd is None:
            try:
                import sounddevice as _sd
                sd = _sd
            except ImportError:
                sys.exit("[ERROR] Missing 'sounddevice'. Run: pip install sounddevice")
        if pyperclip is None:
            try:
                import pyperclip as _pc
                pyperclip = _pc
            except ImportError:
                sys.exit("[ERROR] Missing 'pyperclip'. Run: pip install pyperclip")

    if WhisperModel is None:
        try:
            from faster_whisper import WhisperModel as _WhisperModel
            WhisperModel = _WhisperModel
        except ImportError:
            sys.exit("[ERROR] Missing 'faster-whisper'. Run: pip install faster-whisper")


DEFAULT_CONFIG = {
    "key": "KEY_RIGHTALT",
    "model": "base.en",
    "device": "cpu",
    "compute_type": "int8",
    "language": "en",
    "auto_submit": False,
    "sound_feedback": True,
    "notifications": True,
    "voice_punctuation": True,
    "tray_icon": True,
    "min_hold_seconds": 0.25,
    "paste_delay": 0.08,
    "restore_clipboard": False,
    "snippets": {
        "my email": "nikk@example.com",
        "shrug": "¯\\_(ツ)_/¯"
    }
}

CONFIG_DIR = Path.home() / ".config" / "whisperflow"
CONFIG_FILE = CONFIG_DIR / "config.json"
CACHE_DIR = Path.home() / ".cache" / "whisperflow"
SOCKET_FILE = CACHE_DIR / "whisperflow.sock"
PID_FILE = CACHE_DIR / "whisperflow.pid"
LOG_FILE = CACHE_DIR / "whisperflow.log"


def load_config() -> Dict[str, Any]:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    cfg = DEFAULT_CONFIG.copy()
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r") as f:
                user_cfg = json.load(f)
                cfg.update(user_cfg)
        except Exception as e:
            print(f"[WARN] Failed to read config file ({e}), using defaults.")
    else:
        save_config(cfg)
    return cfg


def save_config(cfg: Dict[str, Any]):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=4)


class AudioFeedback:
    """Generates and plays short, subtle audio cues without external audio files."""
    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self.start_sound = CACHE_DIR / "start.wav"
        self.stop_sound = CACHE_DIR / "stop.wav"
        if self.enabled:
            self._ensure_sounds()

    def _generate_beep(self, path: Path, freq: float, duration: float = 0.05):
        sample_rate = 16000
        t = np.linspace(0, duration, int(sample_rate * duration), False)
        tone = np.sin(2 * np.pi * freq * t)
        envelope = np.sin(np.pi * np.linspace(0, 1, len(t)))
        audio = (tone * envelope * 0.25 * 32767).astype(np.int16)
        with wave.open(str(path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(audio.tobytes())

    def _ensure_sounds(self):
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        if not self.start_sound.exists():
            self._generate_beep(self.start_sound, freq=880, duration=0.04)  # High chime
        if not self.stop_sound.exists():
            self._generate_beep(self.stop_sound, freq=660, duration=0.04)   # Soft chime

    def _play_file(self, path: Path):
        if not self.enabled:
            return
        try:
            if IS_WINDOWS:
                import winsound
                winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC)
            elif IS_MAC:
                subprocess.Popen(["afplay", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            elif shutil.which("pw-play"):
                subprocess.Popen(["pw-play", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            elif shutil.which("paplay"):
                subprocess.Popen(["paplay", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass

    def play_start(self):
        self._play_file(self.start_sound)

    def play_stop(self):
        self._play_file(self.stop_sound)


class Notifier:
    """Lightweight cross-platform desktop notification."""
    def __init__(self, enabled: bool = True):
        self.enabled = enabled

    def notify(self, title: str, message: str, icon: str = "audio-input-microphone", timeout: int = 1500):
        if not self.enabled:
            return
        try:
            if IS_LINUX and shutil.which("notify-send"):
                subprocess.Popen([
                    "notify-send",
                    "-a", "WhisperFlow",
                    "-i", icon,
                    "-t", str(timeout),
                    "-h", "int:transient:1",
                    title,
                    message
                ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            elif IS_MAC:
                safe_msg = message.replace('"', '\\"')
                safe_title = title.replace('"', '\\"')
                subprocess.Popen([
                    "osascript", "-e",
                    f'display notification "{safe_msg}" with title "{safe_title}"'
                ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass


class AudioRecorder:
    """Streams raw audio from PipeWire (Linux) or sounddevice (Windows/macOS/fallback)."""
    def __init__(self, sample_rate: int = 16000):
        self.sample_rate = sample_rate
        self.proc: Optional[subprocess.Popen] = None
        self._raw_data: bytearray = bytearray()
        self._sd_chunks: List[np.ndarray] = []
        self._sd_stream = None
        self._reader_thread: Optional[threading.Thread] = None
        self.recording = False
        self.use_pw = IS_LINUX and shutil.which("pw-record") is not None

    def start(self):
        if self.recording:
            return
        self.recording = True
        self._raw_data = bytearray()
        self._sd_chunks = []

        if self.use_pw:
            self.proc = subprocess.Popen(
                ["pw-record", "--raw", "--target", "@DEFAULT_AUDIO_SRC@", f"--rate={self.sample_rate}", "--channels=1", "--format=s16", "-"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                bufsize=1024 * 16
            )

            def _reader():
                while self.recording and self.proc and self.proc.stdout:
                    chunk = self.proc.stdout.read(2048)
                    if not chunk:
                        break
                    self._raw_data.extend(chunk)

            self._reader_thread = threading.Thread(target=_reader, daemon=True)
            self._reader_thread.start()
        else:
            ensure_imports()
            def _callback(indata, frames, time_info, status):
                if self.recording:
                    self._sd_chunks.append(indata.copy())

            self._sd_stream = sd.InputStream(
                samplerate=self.sample_rate,
                channels=1,
                dtype="float32",
                callback=_callback
            )
            self._sd_stream.start()

    def stop(self) -> Optional[np.ndarray]:
        if not self.recording:
            return None
        self.recording = False

        if self.use_pw:
            if self.proc:
                try:
                    self.proc.terminate()
                    self.proc.wait(timeout=0.3)
                except Exception:
                    try:
                        self.proc.kill()
                    except Exception:
                        pass
                if self.proc.stdout:
                    try:
                        remaining = self.proc.stdout.read()
                        if remaining:
                            self._raw_data.extend(remaining)
                    except Exception:
                        pass
                self.proc = None

            if self._reader_thread:
                self._reader_thread.join(timeout=0.3)
                self._reader_thread = None

            if len(self._raw_data) < 1600:
                return None

            pcm16 = np.frombuffer(self._raw_data, dtype="<i2")
            return pcm16.astype(np.float32) / 32768.0
        else:
            if self._sd_stream:
                try:
                    self._sd_stream.stop()
                    self._sd_stream.close()
                except Exception:
                    pass
                self._sd_stream = None
            if not self._sd_chunks:
                return None
            audio = np.concatenate(self._sd_chunks, axis=0).flatten()
            if len(audio) < 800:
                return None
            return audio

    def cancel(self):
        self.recording = False
        if self.proc:
            try:
                self.proc.kill()
            except Exception:
                pass
            self.proc = None
        if self._sd_stream:
            try:
                self._sd_stream.stop()
                self._sd_stream.close()
            except Exception:
                pass
            self._sd_stream = None
        self._raw_data = bytearray()
        self._sd_chunks = []


class TextTyper:
    """Types or pastes text into the currently active window across Linux, Windows, and macOS."""
    def __init__(self, restore_clipboard: bool = False, paste_delay: float = 0.08):
        ensure_imports()
        self.restore_clipboard = restore_clipboard
        self.paste_delay = paste_delay
        self.ui = None
        self.kbd = None
        self.use_uinput = IS_LINUX and evdev is not None and shutil.which("wl-copy") is not None
        if self.use_uinput:
            self._init_uinput()
        else:
            self.kbd = pynput_keyboard.Controller()

    def _init_uinput(self) -> bool:
        if not self.use_uinput:
            return False
        if self.ui is not None:
            return True
        try:
            self.ui = evdev.UInput({
                ecodes.EV_KEY: [
                    ecodes.KEY_LEFTCTRL,
                    ecodes.KEY_LEFTSHIFT,
                    ecodes.KEY_LEFTALT,
                    ecodes.KEY_RIGHTALT,
                    ecodes.KEY_V,
                    ecodes.KEY_C,
                    ecodes.KEY_A,
                    ecodes.KEY_Z,
                    ecodes.KEY_ENTER,
                    ecodes.KEY_INSERT
                ]
            }, name="whisperflow-uinput-typer")
            time.sleep(0.05)
            return True
        except Exception as e:
            user = os.environ.get("USER", "user")
            print(f"[ERROR] Virtual keyboard error: {e}")
            print(f"        To fix typing, grant permission to /dev/uinput:")
            print(f"        sudo setfacl -m u:{user}:rw /dev/uinput")
            self.ui = None
            return False

    def emit_action(self, action: str):
        """Simulates common editor shortcuts ('select_all', 'undo', 'copy') cross-platform."""
        if self.use_uinput:
            key_map = {
                "select_all": ecodes.KEY_A,
                "undo": ecodes.KEY_Z,
                "copy": ecodes.KEY_C,
            }
            if action in key_map:
                self.emit_combo(ecodes.KEY_LEFTCTRL, key_map[action])
        elif self.kbd:
            mod = pynput_keyboard.Key.cmd if IS_MAC else pynput_keyboard.Key.ctrl
            char_map = {"select_all": "a", "undo": "z", "copy": "c"}
            if action in char_map:
                with self.kbd.pressed(mod):
                    self.kbd.press(char_map[action])
                    self.kbd.release(char_map[action])

    def emit_combo(self, *key_codes):
        """Simulates pressing and releasing a key combination (Linux uinput)."""
        if self.ui is None:
            self._init_uinput()
        if self.ui:
            self.ui.write(ecodes.EV_KEY, ecodes.KEY_RIGHTALT, 0)
            self.ui.write(ecodes.EV_KEY, ecodes.KEY_LEFTALT, 0)
            self.ui.syn()
            time.sleep(0.01)

            for k in key_codes:
                self.ui.write(ecodes.EV_KEY, k, 1)
            self.ui.syn()
            time.sleep(0.03)
            for k in reversed(key_codes):
                self.ui.write(ecodes.EV_KEY, k, 0)
            self.ui.syn()

    def paste_text(self, text: str, auto_submit: bool = False):
        if not text:
            return

        if self.use_uinput:
            if self.ui is None:
                self._init_uinput()

            try:
                p = subprocess.Popen(
                    ["wl-copy"],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                p.stdin.write(text.encode("utf-8"))
                p.stdin.close()
            except Exception as e:
                print(f"[ERROR] Failed to copy to clipboard: {e}")
                return

            time.sleep(self.paste_delay)

            if self.ui:
                self.ui.write(ecodes.EV_KEY, ecodes.KEY_RIGHTALT, 0)
                self.ui.write(ecodes.EV_KEY, ecodes.KEY_LEFTALT, 0)
                self.ui.syn()
                time.sleep(0.01)

                self.ui.write(ecodes.EV_KEY, ecodes.KEY_LEFTCTRL, 1)
                self.ui.write(ecodes.EV_KEY, ecodes.KEY_V, 1)
                self.ui.syn()
                time.sleep(0.03)
                self.ui.write(ecodes.EV_KEY, ecodes.KEY_V, 0)
                self.ui.write(ecodes.EV_KEY, ecodes.KEY_LEFTCTRL, 0)
                self.ui.syn()

                if auto_submit:
                    time.sleep(0.05)
                    self.ui.write(ecodes.EV_KEY, ecodes.KEY_ENTER, 1)
                    self.ui.syn()
                    time.sleep(0.02)
                    self.ui.write(ecodes.EV_KEY, ecodes.KEY_ENTER, 0)
                    self.ui.syn()
            else:
                print("\n[ERROR] Cannot type text because /dev/uinput is not accessible!")
                subprocess.Popen([
                    "notify-send", "-a", "WhisperFlow", "-i", "dialog-error", "-t", "4000",
                    "WhisperFlow Error", "Cannot type: /dev/uinput permission needed!\nRun: sudo setfacl -m u:$USER:rw /dev/uinput"
                ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            # Windows / macOS / X11 fallback via pyperclip + pynput
            try:
                pyperclip.copy(text)
            except Exception as e:
                print(f"[ERROR] Clipboard copy failed: {e}")
                return

            time.sleep(self.paste_delay)
            mod = pynput_keyboard.Key.cmd if IS_MAC else pynput_keyboard.Key.ctrl
            with self.kbd.pressed(mod):
                self.kbd.press("v")
                self.kbd.release("v")

            if auto_submit:
                time.sleep(0.05)
                self.kbd.press(pynput_keyboard.Key.enter)
                self.kbd.release(pynput_keyboard.Key.enter)

    def close(self):
        if self.ui:
            try:
                self.ui.close()
            except Exception:
                pass


class Transcriber:
    """Wrapper around faster-whisper WhisperModel."""
    def __init__(self, model_name: str = "base.en", device: str = "cpu", compute_type: str = "int8", language: Optional[str] = "en"):
        ensure_imports()
        print(f"[*] Initializing faster-whisper model '{model_name}' on {device} ({compute_type})...")
        t0 = time.time()
        self.model = WhisperModel(model_name, device=device, compute_type=compute_type)
        self.language = language if language != "auto" else None
        print(f"[✓] Model ready in {time.time()-t0:.2f}s")

    def transcribe(self, audio: np.ndarray) -> str:
        if audio is None or len(audio) == 0:
            return ""

        rms = float(np.sqrt(np.mean(audio**2)))

        # 1. Try first with Silero VAD filter
        segments, _ = self.model.transcribe(
            audio,
            beam_size=1,
            language=self.language,
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=300)
        )
        parts = [seg.text for seg in segments]
        text = " ".join(parts).strip()

        # 2. If VAD filtered everything out but there was significant audio energy, retry without VAD
        if not text and rms > 0.012:
            segments, _ = self.model.transcribe(
                audio,
                beam_size=1,
                language=self.language,
                vad_filter=False
            )
            parts = [seg.text for seg in segments]
            text = " ".join(parts).strip()

        if text:
            text = text[0].upper() + text[1:]
        return text


class InputMonitor:
    """Monitors keyboard devices via evdev for push-to-talk key hold."""
    def __init__(self, key_name: Any, on_press, on_release, on_cancel):
        ensure_imports()
        self.key_name = key_name
        self.trigger_codes = set()

        # Support single key, list, or 'both_ctrl'
        if isinstance(key_name, list):
            for k in key_name:
                c = getattr(ecodes, k, None)
                if c is not None:
                    self.trigger_codes.add(c)
        elif str(key_name).lower() in ("both_ctrl", "all_ctrl"):
            self.trigger_codes = {ecodes.KEY_RIGHTCTRL, ecodes.KEY_LEFTCTRL}
        else:
            c = getattr(ecodes, str(key_name), None)
            if c is not None:
                self.trigger_codes.add(c)

        if not self.trigger_codes:
            raise ValueError(f"Unknown key code: '{key_name}'")

        self.on_press = on_press
        self.on_release = on_release
        self.on_cancel = on_cancel

        self.is_holding = False
        self.active_code = None
        self.combo_detected = False
        self.press_time = 0.0
        self.running = False
        self.keyboards: List[Any] = []

    def find_keyboards(self) -> List[Any]:
        devices = []
        try:
            for path in evdev.list_devices():
                try:
                    dev = evdev.InputDevice(path)
                    caps = dev.capabilities()
                    if ecodes.EV_KEY in caps:
                        keys = caps[ecodes.EV_KEY]
                        # Device must have at least one trigger key and common keyboard keys
                        if any(tc in keys for tc in self.trigger_codes) and (ecodes.KEY_A in keys or ecodes.KEY_ENTER in keys):
                            devices.append(dev)
                except Exception:
                    pass
        except Exception:
            pass
        return devices

    def init_devices(self) -> bool:
        self.keyboards = self.find_keyboards()
        return len(self.keyboards) > 0

    def run(self):
        if not self.keyboards:
            return False

        key_names_str = ", ".join(self.key_name if isinstance(self.key_name, list) else [str(self.key_name)])
        print(f"[✓] Monitoring {len(self.keyboards)} keyboard device(s) for trigger key(s): {key_names_str}")
        self.running = True
        dev_map = {dev.fd: dev for dev in self.keyboards}

        while self.running:
            try:
                r, _, _ = select.select(list(dev_map.keys()), [], [], 0.5)
                for fd in r:
                    dev = dev_map[fd]
                    for event in dev.read():
                        if event.type != ecodes.EV_KEY:
                            continue

                        # Trigger Key Event
                        if event.code in self.trigger_codes:
                            if event.value == 1:  # Down
                                self.is_holding = True
                                self.active_code = event.code
                                self.combo_detected = False
                                self.press_time = time.time()
                                self.on_press()
                            elif event.value == 0:  # Up
                                if self.is_holding and event.code == self.active_code:
                                    self.is_holding = False
                                    self.active_code = None
                                    if not self.combo_detected:
                                        duration = time.time() - self.press_time
                                        self.on_release(duration)
                                    else:
                                        self.combo_detected = False

                        # Any other key pressed while holding trigger key
                        elif event.value == 1 and self.is_holding:
                            self.combo_detected = True
                            self.on_cancel()

            except (OSError, select.error):
                time.sleep(0.5)
                self.keyboards = self.find_keyboards()
                dev_map = {dev.fd: dev for dev in self.keyboards}

        return True

    def stop(self):
        self.running = False


class PynputInputMonitor:
    """Cross-platform keyboard monitor using pynput (Windows, macOS, Linux X11)."""
    def __init__(self, key_name: Any, on_press, on_release, on_cancel):
        ensure_imports()
        self.key_name = key_name
        self.on_press = on_press
        self.on_release = on_release
        self.on_cancel = on_cancel
        self.is_holding = False
        self.combo_detected = False
        self.press_time = 0.0
        self.listener = None
        self.target_keys = self._resolve_keys(key_name)

    def _resolve_keys(self, key_name: Any) -> set:
        K = pynput_keyboard.Key
        mapping = {
            "KEY_RIGHTALT": [K.alt_r, getattr(K, "alt_gr", K.alt_r)],
            "KEY_LEFTALT": [K.alt_l],
            "KEY_RIGHTCTRL": [K.ctrl_r],
            "KEY_LEFTCTRL": [K.ctrl_l],
            "KEY_CAPSLOCK": [K.caps_lock],
            "KEY_F8": [K.f8],
            "KEY_F9": [K.f9],
        }
        names = key_name if isinstance(key_name, list) else [str(key_name)]
        keys = set()
        for n in names:
            if n in mapping:
                keys.update(mapping[n])
        if not keys:
            keys.add(K.alt_r)
        return keys

    def init_devices(self) -> bool:
        return True

    def run(self):
        def _on_press(key):
            if key in self.target_keys:
                if not self.is_holding:
                    self.is_holding = True
                    self.combo_detected = False
                    self.press_time = time.time()
                    self.on_press()
            elif self.is_holding:
                self.combo_detected = True
                self.on_cancel()

        def _on_release(key):
            if key in self.target_keys and self.is_holding:
                self.is_holding = False
                if not self.combo_detected:
                    self.on_release(time.time() - self.press_time)
                else:
                    self.combo_detected = False

        with pynput_keyboard.Listener(on_press=_on_press, on_release=_on_release) as listener:
            self.listener = listener
            listener.join()
        return True

    def stop(self):
        if self.listener:
            self.listener.stop()


class TextFormatter:
    """Handles voice punctuation formatting and custom snippet replacements."""
    def __init__(self, voice_punctuation: bool = True, snippets: Optional[Dict[str, str]] = None):
        self.voice_punctuation = voice_punctuation
        self.snippets = snippets or {}

    def format(self, text: str, clipboard: str = "") -> str:
        if not text:
            return ""

        # 1. Clipboard paste command
        if clipboard:
            clean = re.sub(r'^[^\w]+|[^\w]+$', '', text).lower()
            if clean in ('paste it', 'paste that', 'paste', 'paste clipboard', 'paste here'):
                return clipboard
            paste_pattern = re.compile(r'\b(paste it|paste that|paste clipboard|paste here)\b', re.IGNORECASE)
            text = paste_pattern.sub(lambda m: clipboard, text)

        # 2. Custom Snippet replacements (case-insensitive, longest phrase first)
        sorted_snippets = sorted(self.snippets.items(), key=lambda x: len(x[0]), reverse=True)
        for phrase, replacement in sorted_snippets:
            pattern = re.compile(rf'\b{re.escape(phrase)}\b', re.IGNORECASE)
            text = pattern.sub(lambda m, r=replacement: r, text)

        # 2. Voice Punctuation rules
        if self.voice_punctuation:
            rules = [
                (r'\b(full stop|period)\b', '.'),
                (r'\bcomma\b', ','),
                (r'\bquestion mark\b', '?'),
                (r'\b(exclamation mark|exclamation point)\b', '!'),
                (r'\bcolon\b', ':'),
                (r'\b(semi colon|semicolon)\b', ';'),
                (r'\b(new paragraph|next paragraph)\b', '\n\n'),
                (r'\b(new line|next line)\b', '\n'),
                (r'\b(dash|hyphen)\b', '-'),
            ]
            for pattern, repl in rules:
                text = re.sub(pattern, repl, text, flags=re.IGNORECASE)

            # Clean spaces before punctuation
            text = re.sub(r'\s+([.,!?:;])', r'\1', text)
            # Clean spaces around newlines
            text = re.sub(r'[ \t]*\n[ \t]*', '\n', text)

        # 3. Capitalize first letter and sentences
        if text:
            text = text[0].upper() + text[1:]
            def cap(m):
                return m.group(1) + m.group(2).upper()
            text = re.sub(r'([.!?]\s+|\n+)([a-z])', cap, text)

        return text.strip()


class TrayIconManager:
    """Manages the KDE system tray icon with idle and recording states."""
    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self.icon = None
        self._thread = None
        if self.enabled:
            self._start()

    def _create_icon_image(self, recording: bool = False):
        try:
            from PIL import Image, ImageDraw
            img = Image.new('RGBA', (64, 64), (0, 0, 0, 0))
            d = ImageDraw.Draw(img)
            
            color = (245, 50, 50, 255) if recording else (70, 160, 245, 255)
            base_color = (255, 255, 255, 255)
            
            if recording:
                d.ellipse((3, 3, 61, 61), fill=(255, 30, 30, 70), outline=(255, 60, 60, 255), width=2)
            
            d.rounded_rectangle((24, 14, 40, 36), radius=8, fill=color)
            d.arc((18, 24, 46, 42), start=0, end=180, fill=base_color, width=3)
            d.line((32, 42, 32, 50), fill=base_color, width=3)
            d.line((22, 50, 42, 50), fill=base_color, width=3)
            return img
        except Exception:
            return None

    def _start(self):
        try:
            import pystray
            img = self._create_icon_image(False)
            if img is None:
                return

            def on_edit_config(icon, item):
                subprocess.Popen(["xdg-open", str(CONFIG_FILE)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            def on_quit(icon, item):
                icon.stop()
                os.kill(os.getpid(), signal.SIGTERM)

            menu = pystray.Menu(
                pystray.MenuItem("🎙️ WhisperFlow (Active)", lambda: None, enabled=False),
                pystray.MenuItem("⚙️ Edit Config & Snippets", on_edit_config),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("❌ Quit", on_quit)
            )

            self.icon = pystray.Icon("whisperflow", img, "WhisperFlow (Ready)", menu)
            self._thread = threading.Thread(target=self.icon.run, daemon=True)
            self._thread.start()
        except Exception as e:
            print(f"[WARN] Tray icon could not be loaded: {e}")
            self.icon = None

    def set_recording(self, recording: bool):
        if not self.enabled or self.icon is None:
            return
        try:
            self.icon.icon = self._create_icon_image(recording)
            self.icon.title = "WhisperFlow: 🔴 Recording..." if recording else "WhisperFlow: Ready"
        except Exception:
            pass

    def stop(self):
        if self.icon:
            try:
                self.icon.stop()
            except Exception:
                pass


class App:
    """Core WhisperFlow daemon application."""
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.feedback = AudioFeedback(enabled=config.get("sound_feedback", True))
        self.notifier = Notifier(enabled=config.get("notifications", True))
        self.recorder = AudioRecorder()
        self.typer = TextTyper(
            restore_clipboard=config.get("restore_clipboard", False),
            paste_delay=config.get("paste_delay", 0.08)
        )
        self.transcriber = Transcriber(
            model_name=config.get("model", "base.en"),
            device=config.get("device", "cpu"),
            compute_type=config.get("compute_type", "int8"),
            language=config.get("language", "en")
        )
        self.formatter = TextFormatter(
            voice_punctuation=config.get("voice_punctuation", True),
            snippets=config.get("snippets", {})
        )
        self.tray = TrayIconManager(enabled=config.get("tray_icon", True))
        MonitorCls = InputMonitor if (IS_LINUX and evdev is not None) else PynputInputMonitor
        self.monitor = MonitorCls(
            key_name=config.get("key", "KEY_RIGHTALT"),
            on_press=self.on_key_down,
            on_release=self.on_key_up,
            on_cancel=self.on_cancel
        )
        self.min_hold_seconds = config.get("min_hold_seconds", 0.25)
        self.auto_submit = config.get("auto_submit", False)
        self.is_recording = False
        self.last_clipboard = ""
        self._lock = threading.Lock()

    def on_key_down(self):
        with self._lock:
            if self.is_recording:
                return
            self.is_recording = True
            # Snapshot current clipboard so voice paste commands can use it
            self.last_clipboard = ""
            try:
                if IS_LINUX and shutil.which("wl-paste"):
                    res = subprocess.run(["wl-paste", "--no-newline"], capture_output=True, text=True, timeout=0.2)
                    if res.returncode == 0:
                        self.last_clipboard = res.stdout
                elif pyperclip is not None:
                    self.last_clipboard = pyperclip.paste() or ""
            except Exception:
                self.last_clipboard = ""

            self.tray.set_recording(True)
            self.feedback.play_start()
            self.notifier.notify("WhisperFlow", "🎙️ Listening... Speak now!", timeout=2500)
            self.recorder.start()
            print("🎙️ Recording started... [Speak now]")

    def on_key_up(self, duration: float = 1.0):
        with self._lock:
            if not self.is_recording:
                return
            self.is_recording = False

        self.tray.set_recording(False)

        if duration < self.min_hold_seconds:
            self.recorder.cancel()
            return

        self.feedback.play_stop()
        audio = self.recorder.stop()
        if audio is None:
            self.notifier.notify("WhisperFlow", "❌ Audio too short", icon="dialog-warning", timeout=1200)
            return

        rms = float(np.sqrt(np.mean(audio**2)))
        print(f"[*] Transcribing {len(audio)/16000:.1f}s of audio (RMS: {rms:.3f})...")
        t0 = time.time()
        try:
            raw_text = self.transcriber.transcribe(audio)

            # 1. Check for quick voice editor actions
            clean_cmd = re.sub(r'^[^\w]+|[^\w]+$', '', raw_text).lower()
            if clean_cmd in ("select all", "select everything"):
                self.typer.emit_action("select_all")
                self.notifier.notify("WhisperFlow", "⚡ Selected All", timeout=1500)
                return
            if clean_cmd in ("undo", "undo that", "undo this"):
                self.typer.emit_action("undo")
                self.notifier.notify("WhisperFlow", "⚡ Undo", timeout=1500)
                return
            if clean_cmd in ("copy that", "copy this", "copy it"):
                self.typer.emit_action("copy")
                self.notifier.notify("WhisperFlow", "⚡ Copied", timeout=1500)
                return

            # 2. Format with voice punctuation, snippets, and clipboard injection
            text = self.formatter.format(raw_text, clipboard=self.last_clipboard)
            dt = time.time() - t0

            if text:
                print(f"[✓] ({dt:.2f}s) Transcribed: \"{text}\"")
                self.typer.paste_text(text, auto_submit=self.auto_submit)
                self.notifier.notify("WhisperFlow", f"✍️ {text}", icon="input-keyboard", timeout=2500)
            else:
                print("[*] No speech recognized.")
                self.notifier.notify("WhisperFlow", "❌ No speech heard", icon="dialog-warning", timeout=1500)
        except Exception as e:
            print(f"[ERROR] Transcription/paste failed: {e}")
            self.notifier.notify("WhisperFlow", f"❌ Error: {e}", icon="dialog-error", timeout=2000)

    def on_cancel(self):
        with self._lock:
            if self.is_recording:
                self.is_recording = False
                self.tray.set_recording(False)
                self.recorder.cancel()
                print("[-] Key combo detected: cancelled voice typing.")

    def toggle(self):
        if not self.is_recording:
            self.on_key_down()
        else:
            self.on_key_up(duration=1.0)

    def start_socket_server(self):
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        if SOCKET_FILE.exists():
            SOCKET_FILE.unlink()

        def _server():
            server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            server.bind(str(SOCKET_FILE))
            server.listen(5)
            while True:
                try:
                    conn, _ = server.accept()
                    data = conn.recv(1024).decode("utf-8").strip()
                    if data == "toggle":
                        self.toggle()
                        conn.sendall(b"OK: toggled\n")
                    elif data == "start":
                        self.on_key_down()
                        conn.sendall(b"OK: recording started\n")
                    elif data == "stop":
                        self.on_key_up(duration=1.0)
                        conn.sendall(b"OK: recording stopped\n")
                    elif data == "status":
                        status = "recording" if self.is_recording else "idle"
                        conn.sendall(f"OK: {status} (Key: {self.config.get('key')})\n".encode("utf-8"))
                    conn.close()
                except Exception:
                    pass

        t = threading.Thread(target=_server, daemon=True)
        t.start()

    def run(self):
        self.start_socket_server()
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        PID_FILE.write_text(str(os.getpid()))

        can_monitor = self.monitor.init_devices()

        if can_monitor:
            print("\n" + "=" * 60)
            print("  WhisperFlow Voice Typing Ready!")
            print(f"  Hold down [{self.config.get('key')}] to speak.")
            print("  Release it to type automatically at your cursor.")
            if self.auto_submit:
                print("  [Auto-submit enabled: Enter key will be pressed after typing]")
            print("=" * 60 + "\n")
            self.notifier.notify("WhisperFlow", f"Active! Hold [{self.config.get('key')}] to talk.", timeout=2000)
            self.monitor.run()
        else:
            user = os.environ.get("USER", "nikk")
            print("\n" + "=" * 60)
            print("  [!] Keyboard devices in /dev/input/ not yet accessible.")
            print(f"  Grant instant permission in your current session by running:")
            print(f"      sudo setfacl -m u:{user}:rw /dev/input/event*")
            print("=" * 60 + "\n")
            self.notifier.notify("WhisperFlow", "Waiting for input permission (see terminal).", timeout=3000)

            if sys.stdin.isatty():
                # Interactive terminal prompt
                while True:
                    try:
                        input("👉 Press [ENTER] to START speaking...")
                        self.on_key_down()
                        input("🔴 RECORDING... Speak now! Press [ENTER] to STOP and type...")
                        self.on_key_up(duration=2.0)
                        print()
                    except (KeyboardInterrupt, EOFError):
                        break
            else:
                # Non-interactive / Daemon mode: keep socket alive and poll for device permissions
                while True:
                    time.sleep(2)
                    if self.monitor.init_devices():
                        print("[✓] Keyboard devices now accessible! Activating push-to-talk...")
                        self.notifier.notify("WhisperFlow", f"Active! Hold [{self.config.get('key')}] to talk.", timeout=2000)
                        self.monitor.run()
                        break


def send_ipc_command(command: str) -> bool:
    if not SOCKET_FILE.exists():
        return False
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.connect(str(SOCKET_FILE))
        s.sendall(command.encode("utf-8"))
        res = s.recv(1024).decode("utf-8")
        print(res.strip())
        s.close()
        return True
    except Exception:
        return False


def detect_key():
    """Detects any pressed key and configures it as the trigger key."""
    ensure_imports()
    devices = []
    for path in evdev.list_devices():
        try:
            dev = evdev.InputDevice(path)
            caps = dev.capabilities()
            if ecodes.EV_KEY in caps and ecodes.KEY_ENTER in caps[ecodes.EV_KEY]:
                devices.append(dev)
        except Exception:
            pass

    if not devices:
        user = os.environ.get("USER", "nikk")
        print("[ERROR] Cannot read keyboard devices from /dev/input/.")
        print(f"Run this command first to grant permission:\n    sudo setfacl -m u:{user}:rw /dev/input/event*\n")
        return

    print("\n" + "=" * 60)
    print("  Key Detection Mode")
    print("=" * 60)
    print("  Please PRESS the key you want to use (e.g. Right Ctrl)...")
    print("  (Listening across", len(devices), "input devices...)")

    dev_map = {dev.fd: dev for dev in devices}
    detected_name = None
    detected_code = None

    while detected_name is None:
        try:
            r, _, _ = select.select(list(dev_map.keys()), [], [], 1.0)
            for fd in r:
                dev = dev_map[fd]
                for event in dev.read():
                    if event.type == ecodes.EV_KEY and event.value == 1:
                        # Find name
                        for name in dir(ecodes):
                            if name.startswith("KEY_") and getattr(ecodes, name) == event.code:
                                detected_name = name
                                detected_code = event.code
                                break
                        if detected_name:
                            break
                if detected_name:
                    break
        except KeyboardInterrupt:
            print("\nCancelled.")
            return

    print(f"\n[✓] Detected key: {detected_name} (Scancode: {detected_code})")
    cfg = load_config()
    cfg["key"] = detected_name
    save_config(cfg)
    print(f"[✓] Saved '{detected_name}' to ~/.config/whisperflow/config.json!\n")


def test_microphone():
    """Interactive test of microphone input level and transcription."""
    ensure_imports()
    config = load_config()
    feedback = AudioFeedback()
    transcriber = Transcriber(
        model_name=config.get("model", "base.en"),
        device=config.get("device", "cpu"),
        compute_type=config.get("compute_type", "int8"),
        language=config.get("language", "en")
    )

    print("\n" + "=" * 60)
    print("  Microphone & Transcription Test")
    print("=" * 60)
    print("[*] Recording 4 seconds from your default microphone...")
    print("    >>> PLEASE SPEAK OUT LOUD NOW! (e.g. 'Testing voice typing on Arch') <<<\n")

    feedback.play_start()
    proc = subprocess.Popen(
        ["pw-record", "--raw", "--target", "@DEFAULT_AUDIO_SRC@", f"--rate=16000", "--channels=1", "--format=s16", "-"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        bufsize=1024 * 16
    )

    raw_data = bytearray()
    t_end = time.time() + 4.0
    bar_width = 24

    while time.time() < t_end:
        chunk = proc.stdout.read(1600)
        if not chunk:
            break
        raw_data.extend(chunk)

        pcm = np.frombuffer(chunk, dtype="<i2")
        rms = float(np.sqrt(np.mean((pcm.astype(float) / 32768.0)**2)))
        level = min(1.0, rms * 8.0)
        filled = int(level * bar_width)
        bar = "█" * filled + "░" * (bar_width - filled)
        rem = max(0.0, t_end - time.time())
        sys.stdout.write(f"\r    [{rem:.1f}s remaining] [{bar}] Vol: {int(level*100):3d}%")
        sys.stdout.flush()

    sys.stdout.write("\n\n")
    proc.terminate()
    try:
        proc.wait(timeout=0.3)
    except Exception:
        proc.kill()
    feedback.play_stop()

    if len(raw_data) < 3200:
        print("[ERROR] No audio recorded. Please check your PipeWire microphone setup.")
        return

    pcm16 = np.frombuffer(raw_data, dtype="<i2")
    audio = pcm16.astype(np.float32) / 32768.0
    overall_rms = float(np.sqrt(np.mean(audio**2)))
    peak = float(np.max(np.abs(audio)))

    print(f"[*] Audio Stats: Overall RMS = {overall_rms:.4f}, Peak = {peak:.4f}")
    if overall_rms < 0.005:
        print("    ⚠️  Warning: Audio level was extremely low. Microphone might be muted")
        print("    or volume slider in KDE System Settings -> Audio is too low.")

    print(f"[*] Transcribing {len(audio)/16000:.1f}s of audio...")
    t0 = time.time()
    text = transcriber.transcribe(audio)
    print(f"[✓] Transcribed in {time.time()-t0:.2f}s:")
    print(f"\n    Result: \"{text}\"\n")


def stop_daemon():
    """Kills running WhisperFlow daemon."""
    my_pid = os.getpid()
    stopped = False
    if PID_FILE.exists():
        try:
            pid = int(PID_FILE.read_text().strip())
            if pid != my_pid:
                os.kill(pid, signal.SIGTERM)
                print(f"[✓] Stopped WhisperFlow (PID: {pid})")
                stopped = True
        except Exception:
            pass
        try:
            PID_FILE.unlink()
        except Exception:
            pass
    if SOCKET_FILE.exists():
        try:
            SOCKET_FILE.unlink()
        except Exception:
            pass
    if not stopped:
        try:
            out = subprocess.check_output(["pgrep", "-f", "whisperflow.py"]).decode().split()
            for p in out:
                p_int = int(p.strip())
                if p_int != my_pid:
                    os.kill(p_int, signal.SIGTERM)
                    print(f"[✓] Stopped WhisperFlow (PID: {p_int})")
                    stopped = True
        except Exception:
            pass
    if not stopped:
        print("WhisperFlow was not running.")


def daemonize(args):
    """Spawns whisperflow detached in the background."""
    stop_daemon()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    bin_path = Path.home() / ".local" / "share" / "whisperflow" / "whisperflow.py"
    python_bin = Path.home() / ".local" / "share" / "whisperflow" / "venv" / "bin" / "python3"

    cmd = [str(python_bin), "-u", str(bin_path)]
    if args.submit:
        cmd.append("--submit")
    if args.key:
        cmd.extend(["--key", args.key])

    log_fd = open(str(LOG_FILE), "a")
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    proc = subprocess.Popen(
        cmd,
        stdout=log_fd,
        stderr=log_fd,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
        env=env
    )
    PID_FILE.write_text(str(proc.pid))
    time.sleep(1.0)
    if proc.poll() is None:
        print(f"[✓] WhisperFlow started in background (PID: {proc.pid})")
        print(f"    Active trigger key: [{args.key or load_config().get('key')}]")
        print(f"    Logs: {LOG_FILE}")
        print(f"    To stop: whisperflow --kill")
    else:
        print(f"[ERROR] WhisperFlow failed to start. Check logs at: {LOG_FILE}")


def main():
    parser = argparse.ArgumentParser(description="WhisperFlow: Local voice-to-text typing for Arch Linux.")
    parser.add_argument("--key", type=str, help="Evdev key name (e.g. KEY_RIGHTCTRL, KEY_LEFTCTRL, KEY_F8)")
    parser.add_argument("--model", type=str, help="Whisper model (e.g. tiny.en, base.en, small.en)")
    parser.add_argument("--device", type=str, choices=["cpu", "cuda"], help="Computation device (cpu or cuda)")
    parser.add_argument("--compute-type", type=str, help="Compute type (int8, float16, float32)")
    parser.add_argument("--language", type=str, help="Language code (en, auto, de, fr, es, etc.)")
    parser.add_argument("--submit", action="store_true", help="Automatically press Enter after typing")
    parser.add_argument("--no-submit", action="store_true", help="Do not press Enter after typing")
    parser.add_argument("--sound", action="store_true", help="Enable audio chimes")
    parser.add_argument("--no-sound", action="store_true", help="Disable audio chimes")
    parser.add_argument("--daemon", action="store_true", help="Run WhisperFlow in the background as a daemon")
    parser.add_argument("--kill", action="store_true", help="Stop running WhisperFlow daemon")
    parser.add_argument("--toggle", action="store_true", help="Toggle recording state of running daemon")
    parser.add_argument("--start", action="store_true", help="Start recording via running daemon")
    parser.add_argument("--stop", action="store_true", help="Stop recording and type via running daemon")
    parser.add_argument("--status", action="store_true", help="Check status of running daemon")
    parser.add_argument("--test-mic", action="store_true", help="Run a quick interactive microphone and model test")
    parser.add_argument("--detect-key", action="store_true", help="Press any key to detect and set it as trigger key")

    args = parser.parse_args()

    if args.kill:
        stop_daemon()
        return
    if args.daemon:
        daemonize(args)
        return
    if args.detect_key:
        detect_key()
        return
    if args.toggle:
        if not send_ipc_command("toggle"):
            print("WhisperFlow daemon is not running.")
        return
    if args.start:
        send_ipc_command("start")
        return
    if args.stop:
        send_ipc_command("stop")
        return
    if args.status:
        if not send_ipc_command("status"):
            print("WhisperFlow daemon is not running.")
        return
    if args.test_mic:
        test_microphone()
        return

    cfg = load_config()
    if args.key:
        cfg["key"] = args.key
    if args.model:
        cfg["model"] = args.model
    if args.device:
        cfg["device"] = args.device
    if args.compute_type:
        cfg["compute_type"] = args.compute_type
    if args.language:
        cfg["language"] = args.language
    if args.submit:
        cfg["auto_submit"] = True
    elif args.no_submit:
        cfg["auto_submit"] = False
    if args.sound:
        cfg["sound_feedback"] = True
    elif args.no_sound:
        cfg["sound_feedback"] = False

    app = App(cfg)

    def _sig_handler(sig, frame):
        app.tray.stop()
        app.monitor.stop()
        app.recorder.cancel()
        app.typer.close()
        if SOCKET_FILE.exists():
            try:
                SOCKET_FILE.unlink()
            except Exception:
                pass
        if PID_FILE.exists():
            try:
                PID_FILE.unlink()
            except Exception:
                pass
        sys.exit(0)

    signal.signal(signal.SIGINT, _sig_handler)
    signal.signal(signal.SIGTERM, _sig_handler)

    app.run()


if __name__ == "__main__":
    main()
