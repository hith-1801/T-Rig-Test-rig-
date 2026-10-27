"""
panels.py
=========
Presentation-layer panels for the Unified Device Monitor.

Contains three QGroupBox subclasses, one per device:

    ElectronicLoadPanel   displays load_voltage_v, load_current_a, load_function
    FlowMeterPanel        displays flow_rate_ln_per_min
    FuelCellPanel         displays fuelcell_voltage_mv, fuelcell_current_ma,
                          fuelcell_temp_c, fuelcell_pressure_mbar,
                          fuelcell_error

Each panel exposes three public slots, called by main_window.py:

    update_values(dict)   - called on each driver's `data_ready` signal
    update_connected(str) - called on each driver's `connected` signal
    update_error(str)     - called on each driver's `error` signal
    mark_disconnected()   - called on each driver's `disconnected` signal

Design rules that this file obeys
---------------------------------
1.  NO device I/O. Panels never touch serial, propar, or drivers.
2.  NO business logic. Panels never write CSV; they only display.
3.  Keys used to look up values in `update_values` match exactly the keys
    emitted by drivers.py, which in turn match config.CSV_COLUMNS
    (minus "timestamp").
4.  Defensive coercion: every value is rendered with `str()` after a
    None-check, so any of None / str / float / int coming out of a
    driver is safe here.
5.  A "stale" indicator: if no data has arrived for a configurable
    number of seconds, the value is dimmed. This makes a silently
    hung device visible in the UI without needing an error to fire.
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFormLayout,
    QFrame,
    QGroupBox,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

import config


# Seconds after which a panel with no fresh data is shown as "stale".
# This is a UI concern only; it does not affect CSV logging.
STALE_AFTER_S = 5.0

# How often the stale-check timer fires.
STALE_CHECK_INTERVAL_MS = 1000


# =========================================================================
# Small shared widget: a label that can be styled as OK / warning / error
# =========================================================================

class _StatusLabel(QLabel):
    """A single-line label whose colour reflects a status string."""

    _STYLE_OK      = "color: #2e7d32;"   # dark green
    _STYLE_WARN    = "color: #b26a00;"   # amber
    _STYLE_ERROR   = "color: #c62828;"   # red
    _STYLE_NEUTRAL = "color: #555555;"   # grey

    def __init__(self, text: str = "", parent: Optional[QWidget] = None) -> None:
        super().__init__(text, parent)
        self.setWordWrap(True)
        self.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.setStyleSheet(self._STYLE_NEUTRAL)

    def show_ok(self, text: str) -> None:
        self.setText(text)
        self.setStyleSheet(self._STYLE_OK)

    def show_warn(self, text: str) -> None:
        self.setText(text)
        self.setStyleSheet(self._STYLE_WARN)

    def show_error(self, text: str) -> None:
        self.setText(text)
        self.setStyleSheet(self._STYLE_ERROR)

    def show_neutral(self, text: str) -> None:
        self.setText(text)
        self.setStyleSheet(self._STYLE_NEUTRAL)


# =========================================================================
# Base class shared by the three concrete panels
# =========================================================================

class _BaseDevicePanel(QGroupBox):
    """
    Common scaffolding: title, connection line, error line, stale timer,
    and the four public slots each concrete panel needs.
    """

    #: Set by subclasses: mapping of displayed field -> CSV column key.
    #: Example: {"Voltage (V)": "load_voltage_v", ...}
    _FIELDS: Dict[str, str] = {}

    def __init__(self, title: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(title, parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        # --- connection line ------------------------------------------------
        self._conn_label = _StatusLabel("<not connected>")

        # --- per-field value labels ----------------------------------------
        self._value_labels: Dict[str, QLabel] = {}
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        for display_name in self._FIELDS:
            label = QLabel(config.PORT_PLACEHOLDER if False else "--")
            label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            monospace = QFont("Monospace")
            monospace.setStyleHint(QFont.TypeWriter)
            label.setFont(monospace)
            self._value_labels[display_name] = label
            form.addRow(f"{display_name}:", label)

        # --- error line ----------------------------------------------------
        self._error_label = _StatusLabel("")
        self._error_label.setVisible(False)

        # --- layout --------------------------------------------------------
        layout = QVBoxLayout(self)
        layout.addWidget(self._conn_label)
        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setFrameShadow(QFrame.Sunken)
        layout.addWidget(separator)
        layout.addLayout(form)
        layout.addWidget(self._error_label)
        layout.addStretch(1)

        # --- stale tracking ------------------------------------------------
        self._last_update_monotonic: Optional[float] = None
        self._stale_active = False
        self._stale_timer = QTimer(self)
        self._stale_timer.setInterval(STALE_CHECK_INTERVAL_MS)
        self._stale_timer.timeout.connect(self._check_stale)
        self._stale_timer.start()

    # ---------------------------------------------------------------
    # Public slots
    # ---------------------------------------------------------------

    def update_values(self, values: Dict[str, Any]) -> None:
        """Render a dict of {column_key: value}. Unknown keys are ignored."""
        self._last_update_monotonic = time.monotonic()
        if self._stale_active:
            self._stale_active = False
            self._un_dimm_all()

        for column_key, raw in values.items():
            # Find the display name(s) that map to this column key.
            for display_name, mapped_key in self._FIELDS.items():
                if mapped_key != column_key:
                    continue
                label = self._value_labels[display_name]
                label.setText(self._format(raw))

    def update_connected(self, identity: str) -> None:
        """Show the device identity from the `connected` signal."""
        self._conn_label.show_ok(f"Connected: {identity}")

    def update_error(self, message: str) -> None:
        """Show an error from the `error` signal."""
        self._error_label.setText(message)
        self._error_label.show_error(message)
        self._error_label.setVisible(True)
        self._conn_label.show_warn("Check device")

    def mark_disconnected(self) -> None:
        """Called from the `disconnected` signal."""
        self._conn_label.show_warn("Disconnected")
        self._stale_timer.stop()

    # ---------------------------------------------------------------
    # Internals
    # ---------------------------------------------------------------

    @staticmethod
    def _format(raw: Any) -> str:
        """Turn anything a driver might emit into a single display line."""
        if raw is None:
            return "N/A"
        if isinstance(raw, str):
            stripped = raw.strip()
            return stripped if stripped else "N/A"
        if isinstance(raw, float):
            return f"{raw:.3f}"
        return str(raw)

    def _check_stale(self) -> None:
        """Dim all value labels if no data has arrived for STALE_AFTER_S."""
        if self._last_update_monotonic is None:
            return  # never received anything yet; leave labels as "--"
        age = time.monotonic() - self._last_update_monotonic
        if age >= STALE_AFTER_S and not self._stale_active:
            self._stale_active = True
            self._dimm_all()
        elif age < STALE_AFTER_S and self._stale_active:
            self._stale_active = False
            self._un_dimm_all()

    def _dimm_all(self) -> None:
        for label in self._value_labels.values():
            label.setStyleSheet("color: #999999;")

    def _un_dimm_all(self) -> None:
        for label in self._value_labels.values():
            label.setStyleSheet("")


# =========================================================================
# Concrete panels
# =========================================================================

class ElectronicLoadPanel(_BaseDevicePanel):
    """Panel for the DC electronic load."""

    _FIELDS = {
        "Voltage (V)":  "load_voltage_v",
        "Current (A)":  "load_current_a",
        "Function":     "load_function",
    }

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__("Electronic Load", parent)


class FlowMeterPanel(_BaseDevicePanel):
    """Panel for the Bronkhorst mass flow meter."""

    _FIELDS = {
        "Flow (ln/min)": "flow_rate_ln_per_min",
    }

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__("Mass Flow Meter", parent)


class FuelCellPanel(_BaseDevicePanel):
    """Panel for the SuSy fuel cell."""

    _FIELDS = {
        "Voltage (mV)":   "fuelcell_voltage_mv",
        "Current (mA)":   "fuelcell_current_ma",
        "Temperature (C)": "fuelcell_temp_c",
        "Pressure (mbar)": "fuelcell_pressure_mbar",
        "Error":          "fuelcell_error",
    }

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__("Fuel Cell (SuSy)", parent)
