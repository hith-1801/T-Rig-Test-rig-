"""
config.py
=========
Central configuration for the Unified Device Monitor application.

This module is intentionally dependency-free: it imports only the Python
standard library. It must NOT import PySide6, serial, propar, or any of
the other application modules. Every other module imports FROM here.

Contents
--------
1.  Device identity constants (baud rates, addresses, terminators)
2.  SCPI/ProPar command strings (verbatim from the original scripts)
3.  Timing constants (poll intervals, CSV write interval)
4.  CSV schema (column order)
5.  Port-selection policy (GUI dropdown, per user request)
6.  Application metadata (name, window title)

Design notes
------------
*   The three original scripts used three DIFFERENT line terminators:
        dc-electronic-load.py  -> b"\n"   (LF)
        flow-meter-bronkhost.py-> ProPar framing (handled by propar lib)
        SuSy.py                -> b"\r"   (CR)
    These are preserved exactly below so the drivers behave identically
    to the scripts that are known to work with the hardware.

*   The three original scripts used three DIFFERENT baud rates:
        electronic load : 19200
        Bronkhorst flow : 38400
        SuSy fuel cell  : 9600
    These are preserved exactly below.

*   Ports are NOT hard-coded. Per user requirement, the user selects
    each port from a GUI dropdown. The DEFAULT_PORT_* values below are
    only *initial suggestions* for the dropdown; they are not enforced.
"""

from __future__ import annotations

# =========================================================================
# 1. APPLICATION METADATA
# =========================================================================

APP_NAME = "Unified Device Monitor"
APP_VERSION = "1.0.0"
WINDOW_MIN_WIDTH = 1100
WINDOW_MIN_HEIGHT = 500


# =========================================================================
# 2. DEVICE COMMUNICATION CONSTANTS
#    (verbatim from the three original working scripts)
# =========================================================================

# --- Electronic load (from dc-electronic-load.py) -----------------------
LOAD_BAUDRATE = 19200
LOAD_TIMEOUT_S = 1.0
LOAD_LINE_TERMINATOR = b"\n"          # original used command + b"\n"
LOAD_INITIAL_DELAY_S = 0.5            # original: time.sleep(0.5) after open
LOAD_QUERY_DELAY_S = 0.1              # original: delay=0.1 in query()
LOAD_POLL_INTERVAL_S = 0.5            # original: time.sleep(0.5) in loop

# --- Bronkhorst flow meter (from flow-meter-bronkhost.py) ----------------
FLOW_BAUDRATE = 38400
FLOW_DEVICE_ADDRESS = 0x80
FLOW_POLL_INTERVAL_S = 1.0            # original: time.sleep(1)

# --- SuSy fuel cell (from SuSy.py) --------------------------------------
SUSY_BAUDRATE = 9600
SUSY_TIMEOUT_S = 1.0
SUSY_LINE_TERMINATOR = b"\r"          # original used command + b"\r"
SUSY_INITIAL_DELAY_S = 0.5            # original: time.sleep(0.5) after open
SUSY_QUERY_DELAY_S = 0.1              # original: delay=0.1 in query()
SUSY_POLL_INTERVAL_S = 1.0            # original: POLL_INTERVAL = 1.0


# =========================================================================
# 3. SCPI / PROPAR COMMAND STRINGS
#    (verbatim from the three original working scripts)
# =========================================================================

# Electronic load SCPI commands
LOAD_CMD_IDN        = "*IDN?"
LOAD_CMD_MEAS_VOLT  = ":MEAS:VOLT?"
LOAD_CMD_MEAS_CURR  = ":MEAS:CURR?"
LOAD_CMD_FUNC       = ":FUNC?"

# SuSy SCPI-style commands (note lowercase and CR terminator)
SUSY_CMD_IDN      = "*idn?"
SUSY_CMD_VOLT     = "*vol?"
SUSY_CMD_CURR     = "*cur?"
SUSY_CMD_TEMP     = "*temp?"
SUSY_CMD_PRESSURE = "*pres?"     # SuSy500 only
SUSY_CMD_ERROR    = "*error?"    # SuSy500 only

# Bronkhorst ProPar parameter addresses (process, parameter)
FLOW_PARAM_FMEASURE       = (33, 0)   # actual flow, FLOAT
FLOW_PARAM_PRODUCT_CODE   = (37, 1)   # product code, STRING
FLOW_PARAM_SERIAL_NUMBER  = (37, 2)   # serial number, STRING


# =========================================================================
# 4. TIMING
# =========================================================================

# How often the DataLogger snapshots the latest cached values and writes
# one CSV row. Independent of each device's own poll interval.
CSV_WRITE_INTERVAL_MS = 1000          # one row per second


# =========================================================================
# 5. CSV SCHEMA
#    Column order is fixed here so DataLogger and any downstream consumer
#    (Excel, pandas, etc.) agree on the layout.
# =========================================================================

CSV_COLUMNS = [
    "timestamp",              # ISO-8601 local time with milliseconds
    "load_voltage_v",
    "load_current_a",
    "load_function",
    "flow_rate_ln_per_min",
    "fuelcell_voltage_mv",
    "fuelcell_current_ma",
    "fuelcell_temp_c",
    "fuelcell_pressure_mbar",
    "fuelcell_error",
]

# Filename pattern: session_YYYYMMDD_HHMMSS.csv
CSV_FILENAME_PREFIX = "session_"
CSV_FILENAME_TIMESTAMP_FORMAT = "%Y%m%d_%H%M%S"


# =========================================================================
# 6. PORT-SELECTION POLICY
#    Per user requirement: the user picks each port from a GUI dropdown.
#    The defaults below are only the *initially highlighted* entries in
#    each dropdown. They are NOT enforced and do NOT need to match the
#    machine running the app.
# =========================================================================

# Initial dropdown selection suggestions (may not exist on every OS)
DEFAULT_LOAD_PORT = "/dev/ttyACM0"     # from dc-electronic-load.py
DEFAULT_FLOW_PORT = ""                 # blank -> user must pick
DEFAULT_SUSY_PORT = ""                 # blank -> user must pick

# Placeholder text shown when a port list is empty
PORT_PLACEHOLDER = "<no ports detected>"


# =========================================================================
# 7. SANITY CHECKS (fail fast at import time if config is internally broken)
# =========================================================================

def _validate() -> None:
    """Raise RuntimeError if any invariant in this config file is broken.

    This runs once at import time. It catches typos in this file itself
    (e.g. a duplicated CSV column name) before any GUI or driver code runs.
    """
    if len(CSV_COLUMNS) != len(set(CSV_COLUMNS)):
        raise RuntimeError(
            "config.py: CSV_COLUMNS contains duplicate names: "
            f"{CSV_COLUMNS!r}"
        )

    if CSV_WRITE_INTERVAL_MS <= 0:
        raise RuntimeError(
            f"config.py: CSV_WRITE_INTERVAL_MS must be > 0, "
            f"got {CSV_WRITE_INTERVAL_MS!r}"
        )

    for name, value in (
        ("LOAD_BAUDRATE", LOAD_BAUDRATE),
        ("FLOW_BAUDRATE", FLOW_BAUDRATE),
        ("SUSY_BAUDRATE", SUSY_BAUDRATE),
    ):
        if not isinstance(value, int) or value <= 0:
            raise RuntimeError(
                f"config.py: {name} must be a positive int, got {value!r}"
            )

    for name, value in (
        ("LOAD_LINE_TERMINATOR", LOAD_LINE_TERMINATOR),
        ("SUSY_LINE_TERMINATOR", SUSY_LINE_TERMINATOR),
    ):
        if not isinstance(value, (bytes, bytearray)) or len(value) == 0:
            raise RuntimeError(
                f"config.py: {name} must be non-empty bytes, got {value!r}"
            )

    if not (0 <= FLOW_DEVICE_ADDRESS <= 0xFF):
        raise RuntimeError(
            f"config.py: FLOW_DEVICE_ADDRESS must be 0..255, "
            f"got {FLOW_DEVICE_ADDRESS!r}"
        )


_validate()
