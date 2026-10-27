# T-Rig (Test-Rig)

# Unified Device Monitor

A cross-platform desktop application for monitoring and logging data from three laboratory instruments in real time: a **DC electronic load**, a **Bronkhorst mass flow meter**, and a **SuSy fuel cell**. The application provides a single window with three live panels, records all readings to a timestamped CSV file, and is packaged as a standalone executable for Windows, Linux, and macOS.

---

## 1. What This Application Is For

Laboratory setups often rely on multiple instruments from different vendors, each with its own proprietary software and communication protocol. The Unified Device Monitor replaces those scattered tools with one application that:

- Displays live readings from all three devices side by side on a single screen.
- Records every reading to a CSV file at a configurable interval (default: 1 row per second).
- Handles the different protocols transparently: SCPI over serial for the electronic load, ProPar over serial for the flow meter, and SCPI-style commands for the fuel cell.
- Keeps recording even if one device temporarily drops a frame, filling the missing cell with `N/A` rather than losing the whole run.
- Runs on Windows, Linux, and macOS without code changes.

The application is intended for researchers, students, and lab engineers who need a simple, reliable data acquisition front end for these specific instruments.

---

## 2. Application Architecture

The codebase follows a **three-layer architecture** with a strict dependency direction (Presentation → Logic → Data). No layer imports from a layer above it.

```
┌─────────────────────────────────────────────────────┐
│  Presentation Layer                                 │
│    main.py           entry point                    │
│    main_window.py    top-level window, signal       │
│                      wiring, start/stop controls    │
│    panels.py         three device display panels    │
├─────────────────────────────────────────────────────┤
│  Logic Layer                                        │
│    data_logger.py    CSV writer + latest-value      │
│                      cache, thread-safe             │
├─────────────────────────────────────────────────────┤
│  Data Layer                                         │
│    drivers.py        three QThread device drivers   │
│    config.py         all constants (baud rates,     │
│                      terminators, command strings,  │
│                      CSV schema)                    │
└─────────────────────────────────────────────────────┘
```

### Layer responsibilities

| File | Layer | Responsibility |
|------|-------|----------------|
| `config.py` | Shared | All constants: baud rates, line terminators, SCPI/ProPar command strings, CSV column order, poll intervals, port defaults. Imports nothing from the rest of the app. |
| `drivers.py` | Data | Three `QThread` subclasses. Each opens its serial port, loops at its own poll interval, and emits `data_ready`, `connected`, `error`, and `disconnected` signals. No GUI imports. |
| `data_logger.py` | Logic | Thread-safe latest-value cache and CSV writer. Owns the file handle. Has no Qt dependency and can be unit-tested headless. |
| `panels.py` | Presentation | Three `QGroupBox` panels, one per device. Each exposes `update_values`, `update_connected`, `update_error`, and `mark_disconnected` slots. No device I/O, no CSV logic. |
| `main_window.py` | Presentation | Assembles the panels, creates the drivers, wires every signal to both its panel and the logger, runs the CSV timer, and implements `closeEvent` to shut down cleanly. |
| `main.py` | Presentation | Entry point: `QApplication` → `MainWindow` → `show()` → `exec()`. |

### Key design decisions

- **All serial I/O runs off the GUI thread.** Each driver is a `QThread`; the GUI never blocks waiting for a device.
- **Drivers are headless.** They emit signals and know nothing about the GUI. This makes them testable in isolation and reusable in a CLI.
- **The CSV is written from a cached snapshot.** Devices poll asynchronously, but the logger writes exactly one row per tick, so the column count is always identical.
- **Errors never kill the recording.** A dropped frame becomes an `N/A` cell; the rest of the run continues.
- **Stop and close are always safe.** `stop()` is cooperative, threads are joined with a timeout, and the CSV file is flushed after every row, so a crash loses at most the row currently being written.

---

## 3. Compilation

The application can be packaged as a standalone executable with **PyInstaller**. Note: **you cannot cross-compile.** Build on the OS you want to target.

First, in every environment, install the dependencies and PyInstaller:

```bash
pip install PySide6 pyserial bronkhorst-propar pyinstaller
```

Then, from the project root, run:

```bash
pyinstaller --name="UnifiedDeviceMonitor" --windowed --onefile --collect-all propar main.py
```

The resulting executable is placed in `dist/`.

### Windows

Run the packaging command above in a Windows Command Prompt or PowerShell. The output is `dist\UnifiedDeviceMonitor.exe`. Double-click to launch; no Python installation is required on the target machine.

### Linux

Run the same command in a Linux terminal. The output is `dist/UnifiedDeviceMonitor`. Grant execute permissions:

```bash
chmod +x dist/UnifiedDeviceMonitor
```

### macOS

Run the same command in a macOS terminal. The output is `dist/UnifiedDeviceMonitor` (an executable, not a `.app` bundle). To produce a `.app` bundle instead, add `--windowed` and PyInstaller will generate `dist/UnifiedDeviceMonitor.app`.

### Why `--collect-all propar`?

The Bronkhorst `propar` library ships binary extensions that PyInstaller does not always detect automatically. The `--collect-all propar` flag forces every file in the package to be included. If you skip it, the packaged application will fail at runtime with a `ModuleNotFoundError` when the flow meter driver starts.

---

## Requirements

- Python 3.10 or newer
- PySide6
- pyserial
- bronkhorst-propar
- PyInstaller (for packaging only)

To run from source:

```bash
python main.py
```

---

## License

Specify your license here (e.g., MIT, Apache-2.0, or proprietary).
