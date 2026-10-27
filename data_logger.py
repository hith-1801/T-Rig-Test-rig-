"""
data_logger.py
==============
CSV logging layer for the Unified Device Monitor.

Contains one class, `DataLogger`, which:

    *  Owns the open CSV file handle.
    *  Maintains an in-memory cache of the latest value from each device.
    *  Writes exactly one CSV row per `snapshot()` call.
    *  Fills missing values with "N/A" so the column count is always
       identical to len(config.CSV_COLUMNS).
    *  Flushes to disk after every row (so data survives a crash).
    *  Is thread-safe: the driver threads never touch this class directly,
       but `update()` may be called from any thread in the future without
       corrupting state.

Design rules that this file obeys
---------------------------------
1.  NO imports from drivers.py / panels.py / main_window.py / main.py.
    This module is pure logic; it does not know what a QThread is.
2.  NO Qt dependency at all. This means you can unit-test it without a
    display server.
3.  Column order is always exactly `config.CSV_COLUMNS`. If a caller
    passes an unknown key to `update()`, it is ignored (silently) rather
    than corrupting the row. If a known key is missing at snapshot time,
    it is written as "N/A".
4.  The file is opened with newline="" so the csv module controls line
    endings per RFC 4180 (works on Windows and Linux/macOS alike).
5.  The file is flushed after every row but NOT fsync'd; fsync on every
    row would be too slow for 1 Hz logging. flush() is sufficient to
    make the data visible to other processes (Excel, pandas) immediately.
"""

from __future__ import annotations

import csv
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import config


# Sentinel value written when a column has no value at snapshot time.
NA = "N/A"


class DataLogger:
    """Thread-safe CSV logger with a latest-value cache per column."""

    def __init__(self, output_dir: Optional[str] = None) -> None:
        """
        Create a logger. No file is opened until `open()` is called.

        Parameters
        ----------
        output_dir : str | None
            Directory in which the session CSV will be created.
            If None, defaults to the current working directory.
        """
        self._output_dir = Path(output_dir) if output_dir else Path.cwd()
        self._cache: Dict[str, str] = {}
        self._lock = threading.Lock()
        self._csv_file = None
        self._writer: Optional[csv.writer] = None
        self._path: Optional[Path] = None
        self._row_count = 0

    # ---------------------------------------------------------------
    # Lifecycle
    # ---------------------------------------------------------------

    def open(self) -> Path:
        """
        Create the session file and write the header row.

        Returns
        -------
        pathlib.Path
            Full path of the newly created CSV file.

        Raises
        ------
        FileExistsError
            If the generated filename already exists (extremely unlikely
            given the timestamp granularity is 1 s, but we check rather
            than silently overwrite).
        OSError
            On any filesystem error.
        """
        if self._csv_file is not None:
            raise RuntimeError("DataLogger.open() called twice without close()")

        self._output_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime(config.CSV_FILENAME_TIMESTAMP_FORMAT)
        filename = f"{config.CSV_FILENAME_PREFIX}{stamp}.csv"
        path = self._output_dir / filename

        if path.exists():
            raise FileExistsError(
                f"Refusing to overwrite existing session file: {path}"
            )

        # newline="" lets csv.write do RFC-4180 line endings itself.
        self._csv_file = open(path, "w", newline="", encoding="utf-8")
        self._writer = csv.writer(self._csv_file)
        self._writer.writerow(config.CSV_COLUMNS)
        self._csv_file.flush()
        self._path = path
        self._row_count = 0
        return path

    def close(self) -> None:
        """Flush and close the file. Idempotent."""
        with self._lock:
            if self._csv_file is None:
                return
            try:
                self._csv_file.flush()
            finally:
                try:
                    self._csv_file.close()
                finally:
                    self._csv_file = None
                    self._writer = None

    # ---------------------------------------------------------------
    # Data path
    # ---------------------------------------------------------------

    def update(self, values: Dict[str, Any]) -> None:
        """
        Merge `values` into the cache.

        Unknown keys are ignored. `None` values are converted to N/A.
        Empty strings are converted to N/A (so the load and SuSy drivers,
        which emit raw strings, never write blank cells by accident).

        Safe to call from any thread.
        """
        with self._lock:
            for key, value in values.items():
                if key not in config.CSV_COLUMNS:
                    # Not a column we know about. Ignore rather than
                    # let a typo silently create a new column.
                    continue
                if value is None:
                    self._cache[key] = NA
                elif isinstance(value, str) and value.strip() == "":
                    self._cache[key] = NA
                else:
                    self._cache[key] = str(value)

    def snapshot(self) -> bool:
        """
        Write one CSV row from the current cache.

        A fresh timestamp is generated inside this method, so the row is
        stamped at write time, not at the time any device last reported.

        Returns
        -------
        bool
            True if a row was written; False if the logger is not open.
        """
        with self._lock:
            if self._csv_file is None or self._writer is None:
                return False

            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            # Build the row in exactly the config-specified order.
            row = []
            for column in config.CSV_COLUMNS:
                if column == "timestamp":
                    row.append(timestamp)
                else:
                    row.append(self._cache.get(column, NA))

            self._writer.writerow(row)
            self._csv_file.flush()
            self._row_count += 1
            return True

    # ---------------------------------------------------------------
    # Introspection (for the GUI status bar / tests)
    # ---------------------------------------------------------------

    @property
    def path(self) -> Optional[Path]:
        """Full path of the current session file, or None if not open."""
        return self._path

    @property
    def row_count(self) -> int:
        """Number of data rows written so far (header not counted)."""
        return self._row_count

    @property
    def is_open(self) -> bool:
        """True if the CSV file is currently open for writing."""
        return self._csv_file is not None


# =========================================================================
# Self-test (runs only when executed directly, never on import)
# =========================================================================

if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        logger = DataLogger(output_dir=tmp)
        path = logger.open()
        print(f"Opened session file: {path}")

        logger.update({
            "load_voltage_v": "12.34",
            "load_current_a": "0.56",
            "load_function":  "CC",
            "flow_rate_ln_per_min": "1.234",
        })
        logger.snapshot()

        logger.update({
            "fuelcell_voltage_mv": "750",
            "fuelcell_current_ma": "120",
            "fuelcell_temp_c":     "60",
            "fuelcell_pressure_mbar": "1013",
            "fuelcell_error":      "0",
        })
        logger.snapshot()

        # Unknown key must be ignored
        logger.update({"not_a_column": "should_be_ignored"})
        logger.snapshot()

        logger.close()

        with open(path, "r", encoding="utf-8", newline="") as fh:
            for line in fh:
                print(line.rstrip("\n"))

        print(f"\nRows written: {logger.row_count}")
        print(f"File size: {os.path.getsize(path)} bytes")
