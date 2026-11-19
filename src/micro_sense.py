from __future__ import annotations

import ctypes
import os
import sys
import threading
import time
import tkinter as tk
import winreg
from ctypes import wintypes
from typing import Final

import numpy as np
import pyaudiowpatch as pyaudio
import pystray
from PIL import Image, ImageDraw, ImageFont, ImageFont as FontType, ImageTk

DB_FLOOR: Final = 50.0
SENSITIVITY: Final = 5.0
GWL_EXSTYLE: Final = -20
WS_EX_TRANSPARENT: Final = 0x00000020
WS_EX_TOOLWINDOW: Final = 0x00000080
WS_EX_LAYERED: Final = 0x00080000
WS_EX_NOACTIVATE: Final = 0x08000000
LWA_COLORKEY: Final = 0x00000001
LWA_ALPHA: Final = 0x00000002
INDICATOR_SIZE: Final = 24
TRANSPARENT_COLOR: Final = "#010203"
TRANSPARENT_COLORREF: Final = 0x00030201
SECOND_ICON_START_DELAY: Final = 0.35

RUN_KEY: Final = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_NAME: Final = "micro-sense"
levels: list[float] = [0.0, 0.0]
display_levels: list[float] = [0.0, 0.0]
lock = threading.Lock()
_mutex: object | None = None


def launch_command() -> str:
    """Return the command that launches micro-sense."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'

    pyw = sys.executable
    if pyw.lower().endswith("python.exe"):
        pyw = pyw[:-10] + "pythonw.exe"
    return f'"{pyw}" "{os.path.abspath(__file__)}"'


def autostart_enabled() -> bool:
    """Return whether micro-sense is configured to start with Windows."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, APP_NAME)
            return True
    except OSError:
        return False


def toggle_autostart(_icon: object = None, _item: object = None) -> None:
    """Enable or disable Windows startup and refresh the tray menu."""
    del _icon, _item
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if autostart_enabled():
            winreg.DeleteValue(k, APP_NAME)
        else:
            winreg.SetValueEx(k, APP_NAME, 0, winreg.REG_SZ, launch_command())


def already_running() -> bool:
    """Return whether another instance owns the application's mutex."""
    global _mutex
    _mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "LRMeterSingleInstance")
    return ctypes.windll.kernel32.GetLastError() == 183


def start_audio() -> tuple[pyaudio.PyAudio, pyaudio.Stream]:
    """Open the default WASAPI loopback device and begin capturing audio."""
    p = pyaudio.PyAudio()
    try:
        dev = p.get_default_wasapi_loopback()
        ch = int(dev["maxInputChannels"])
        if ch < 1:
            raise RuntimeError("The default audio device has no input channels")

        if ch == 1:
            left_idx, right_idx = [0], [0]
        else:
            left_idx = [i for i in (0, 4, 6) if i < ch] or [0]
            right_idx = [i for i in (1, 5, 7) if i < ch] or [0]

        def callback(
            in_data: bytes,
            frame_count: int,
            time_info: object,
            status: int,
        ) -> tuple[None, int]:
            """Convert one captured buffer into left and right RMS levels."""
            del frame_count, time_info, status
            samples = np.frombuffer(in_data, dtype=np.int16)
            if samples.size % ch != 0:
                return (None, pyaudio.paContinue)
            audio = samples.astype(np.float32).reshape(-1, ch) / 32768.0
            out = [
                float(np.sqrt(np.mean(np.square(audio[:, indices]))))
                if audio.shape[0] else 0.0
                for indices in (left_idx, right_idx)
            ]
            with lock:
                levels[:] = out
            return (None, pyaudio.paContinue)

        stream = p.open(
            format=pyaudio.paInt16,
            channels=ch,
            rate=int(dev["defaultSampleRate"]),
            input=True,
            input_device_index=dev["index"],
            frames_per_buffer=1024,
            stream_callback=callback,
        )
        stream.start_stream()
        return p, stream
    except Exception:
        p.terminate()
        raise


def to_fraction(rms: float) -> float:
    """Convert an RMS level into a bounded 0.0-1.0 meter fraction."""
    rms = float(rms)
    if not np.isfinite(rms) or rms <= 0:
        return 0.0

    rms = max(rms * SENSITIVITY, 1e-6)
    db = 20.0 * np.log10(rms)
    fraction = (db + DB_FLOOR) / DB_FLOOR
    return float(min(1.0, max(0.0, fraction)))


def load_font() -> FontType.FreeTypeFont | FontType.ImageFont:
    """Load the preferred display font, with a PIL default fallback."""
    for name in ("arialbd.ttf", "arial.ttf", "segoeuib.ttf"):
        try:
            return ImageFont.truetype(name, 44)
        except OSError:
            pass
    return ImageFont.load_default()


FONT: Final = load_font()
_cache: dict[tuple[str, int, bool], Image.Image] = {}


def make_icon(letter: str, step: int, lead: bool = False) -> Image.Image:
    """Create a tray icon; step ranges from 0 (white) to 15 (full red).

    lead=True adds a green outline (this side is the louder one).
    """
    if len(letter) != 1:
        raise ValueError("letter must contain exactly one character")
    step = min(15, max(0, int(step)))
    key = (letter, step, lead)
    if key not in _cache:
        f = step / 15
        g = int(255 * (1 - f))
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        dr = ImageDraw.Draw(img)
        dr.rounded_rectangle((2, 2, 62, 62), radius=10, fill=(255, g, g, 255),
                             outline=(0, 200, 0, 255) if lead else None, width=6)
        dr.text((32, 33), letter, font=FONT, fill=(40, 40, 40, 255), anchor="mm")
        _cache[key] = img
    return _cache[key]


def make_direction_indicator(
    root: tk.Tk,
    y: int,
) -> tuple[tk.Toplevel, ImageTk.PhotoImage]:
    """Create a transparent, click-through window with a red circle."""
    scale = 4
    image = Image.new(
        "RGB",
        (INDICATOR_SIZE * scale, INDICATOR_SIZE * scale),
        (1, 2, 3),
    )
    ImageDraw.Draw(image).ellipse(
        (5 * scale, 5 * scale, 19 * scale, 19 * scale),
        fill="#ff3030",
    )
    image = image.resize((INDICATOR_SIZE, INDICATOR_SIZE), Image.Resampling.LANCZOS)
    circle = ImageTk.PhotoImage(image, master=root)

    window = tk.Toplevel(root)
    window.overrideredirect(True)
    window.attributes("-topmost", True)
    window.geometry(f"{INDICATOR_SIZE}x{INDICATOR_SIZE}+12+{y}")
    canvas = tk.Canvas(
        window,
        width=INDICATOR_SIZE,
        height=INDICATOR_SIZE,
        background=TRANSPARENT_COLOR,
        highlightthickness=0,
    )
    canvas.pack()
    canvas.create_image(0, 0, image=circle, anchor="nw")

    window.update_idletasks()
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetWindowLongW.restype = ctypes.c_long
    user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
    user32.SetWindowLongW.restype = ctypes.c_long
    user32.SetLayeredWindowAttributes.argtypes = [
        wintypes.HWND,
        wintypes.COLORREF,
        ctypes.c_ubyte,
        wintypes.DWORD,
    ]
    user32.SetLayeredWindowAttributes.restype = wintypes.BOOL
    hwnd = wintypes.HWND(int(window.wm_frame(), 0))
    ctypes.set_last_error(0)
    style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    if style == 0 and ctypes.get_last_error():
        raise ctypes.WinError()
    ctypes.set_last_error(0)
    user32.SetWindowLongW(
        hwnd,
        GWL_EXSTYLE,
        style
        | WS_EX_TRANSPARENT
        | WS_EX_TOOLWINDOW
        | WS_EX_LAYERED
        | WS_EX_NOACTIVATE,
    )
    if ctypes.get_last_error():
        raise ctypes.WinError()
    ctypes.set_last_error(0)
    if not user32.SetLayeredWindowAttributes(
        hwnd,
        TRANSPARENT_COLORREF,
        230,
        LWA_COLORKEY | LWA_ALPHA,
    ):
        raise ctypes.WinError()
    window.withdraw()
    return window, circle


def default_loopback_name() -> str | None:
    """Return the name of the current default loopback device, if any. For switched output devices"""
    p = pyaudio.PyAudio()
    try:
        return str(p.get_default_wasapi_loopback()["name"])
    except Exception:
        return None
    finally:
        p.terminate()


def main() -> None:
    """Run the tray application until the user chooses Quit."""
    if already_running():
        return

    root = tk.Tk()
    root.withdraw()
    running = threading.Event()
    running.set()

    icons = []
    screen_width = root.winfo_screenwidth()
    screen_height = root.winfo_screenheight()
    indicator_y = (screen_height - INDICATOR_SIZE) // 2
    indicator_window, indicator_image = make_direction_indicator(
        root,
        indicator_y,
    )
    indicator_visible = False
    last_direction: int | None = None
    p, stream = start_audio()
    device = default_loopback_name()

    def quit_app(_icon: object = None, _item: object = None) -> None:
        """Stop the update thread and all tray icons."""
        del _icon, _item
        running.clear()
        for tray_icon in icons:
            tray_icon.stop()
        root.after(0, root.quit)

    menu = pystray.Menu(
        pystray.MenuItem("Start with Windows", toggle_autostart,
                         checked=lambda _: autostart_enabled()),
        pystray.MenuItem("Quit", quit_app),
    )
    icons = [
        pystray.Icon("micro-sense-L", make_icon("L", 0), "Left", menu),
        pystray.Icon("micro-sense-R", make_icon("R", 0), "Right", menu),
    ]

    def updater() -> None:
        """Smooth captured levels and update both tray icons."""
        smooth = [0.0, 0.0]
        last: list[tuple[int, bool] | None] = [None, None]
        while running.is_set():
            with lock:
                raw = list(levels)
            for i in (0, 1):
                f = to_fraction(raw[i])
                smooth[i] = f if f > smooth[i] else smooth[i] - 0.08
                smooth[i] = max(0.0, smooth[i])
            with lock:
                display_levels[:] = smooth
            steps = [int(round(s * 15)) for s in smooth]
            for i in (0, 1):
                state = (steps[i], steps[i] > steps[1 - i])
                if state != last[i]:
                    last[i] = state
                    icons[i].icon = make_icon("LR"[i], *state)
            time.sleep(0.05)

    def update_direction_indicator() -> None:
        """Show a red circle on the side with clearly louder audio."""
        nonlocal indicator_visible, last_direction
        with lock:
            current = list(display_levels)
        direction = None
        if max(current) > 0.02:
            if current[0] > current[1] + 0.03:
                direction = 0
            elif current[1] > current[0] + 0.03:
                direction = 1

        if direction is None:
            if indicator_visible:
                indicator_window.withdraw()
                indicator_visible = False
            last_direction = None
        else:
            if direction != last_direction:
                x = 12 if direction == 0 else screen_width - INDICATOR_SIZE - 12
                indicator_window.geometry(
                    f"{INDICATOR_SIZE}x{INDICATOR_SIZE}+{x}+{indicator_y}"
                )
                last_direction = direction
            if not indicator_visible:
                indicator_window.deiconify()
                indicator_visible = True
        root.after(50, update_direction_indicator)

    def watcher() -> None:
        """Restart capture when the default output device changes."""
        nonlocal p, stream, device
        while running.is_set():
            time.sleep(3)
            name = default_loopback_name()
            if name is None or name == device:
                continue
            try:
                new_p, new_stream = start_audio()
            except Exception:
                continue
            old_p, old_stream = p, stream
            p, stream, device = new_p, new_stream, name
            try:
                old_stream.stop_stream()
                old_stream.close()
                old_p.terminate()
            except Exception:
                pass

    try:
        left_icon_ready = threading.Event()
        right_icon_ready = threading.Event()

        def show_right_icon(_icon: object) -> None:
            icons[1].visible = True
            right_icon_ready.set()

        def show_left_icon(_icon: object) -> None:
            if not right_icon_ready.wait(timeout=10):
                raise TimeoutError("The right tray icon did not initialize")
            time.sleep(SECOND_ICON_START_DELAY)
            icons[0].visible = True
            left_icon_ready.set()

        icons[1].run_detached(setup=show_right_icon)
        icons[0].run_detached(setup=show_left_icon)
        if not right_icon_ready.wait(timeout=10):
            raise TimeoutError("The right tray icon did not initialize")
        if not left_icon_ready.wait(timeout=10):
            raise TimeoutError("The left tray icon did not initialize")
        threading.Thread(target=updater, daemon=True).start()
        threading.Thread(target=watcher, daemon=True).start()
        root.after(50, update_direction_indicator)
        root.mainloop()
    finally:
        running.clear()
        for tray_icon in icons:
            tray_icon.stop()
        root.destroy()
        stream.stop_stream()
        stream.close()
        p.terminate()

if __name__ == "__main__":
    main()