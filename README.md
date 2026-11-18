# micro-sense

A tiny Windows system tray app with two icons, **L** and **R**. Each icon goes from white (quiet) to red (loud) based on how much sound is coming from that speaker. Useful in games where directional audio matters.

## Run from source

Activate your venv, then:

```
pip install PyAudioWPatch numpy pystray pillow
python src\micro_sense.py
```

If you use VS Code, run it from the terminal or select the venv interpreter (`Ctrl+Shift+P` > **Python: Select Interpreter** > `.\venv\Scripts\python.exe`). The Code Runner extension ignores the venv.

## Build the app (.exe)

```
pip install pyinstaller
pyinstaller --onefile --noconsole --name micro-sense --hidden-import pystray._win32 src\micro_sense.py
```

The app is created at `dist\micro-sense.exe`. Copy it somewhere permanent, such as `C:\Tools\micro-sense\`. If you move it later, turn "Start with Windows" off and on again.

## Start with Windows

1. If you previously enabled autostart from the Python script, run the script once more, right-click an icon, untick **Start with Windows**, and quit. This removes the old "Python" entry from Settings > Apps > Startup.
2. Run `micro-sense.exe`.
3. Right-click either icon and tick **Start with Windows**.
4. Check Settings > Apps > Startup. **micro-sense** should be listed and switched on.

## Pin the icons to the taskbar tray

1. Open Settings > Personalization > Taskbar > **Other system tray icons**.
2. Switch **micro-sense** on.
3. If it isn't listed, drag the icons out of the **^** overflow menu into the visible tray.

## Usage

Right-click either icon for:

- **Start with Windows** (toggle)
- **Quit**

## Tuning

Edit these near the top of `src\micro_sense.py`, then rebuild:

- `SENSITIVITY`: raise it (for example `3.0`) if quiet sounds like footsteps barely register.
- `DB_FLOOR`: how quiet a sound can be and still show. Higher values are more sensitive.

## Notes

- Only one copy runs at a time. Launching it again does nothing.
- It listens to your current default output device through WASAPI loopback. Nothing is recorded or saved.
- If you switch output devices (for example speakers to headphones), it switches automatically within a few seconds.
- Windows SmartScreen or your antivirus may warn about the unsigned `.exe`. Allow it or add an exception.