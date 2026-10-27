"""
main_window.py
==============
Top-level window for the Unified Device Monitor.

Responsibilities
----------------
1.  Build the three device panels (ElectronicLoadPanel, FlowMeterPanel,
    FuelCellPanel) in a horizontal QGridLayout.
2.  Build the bottom control bar: three port dropdowns, an output-folder
    chooser, a Start button, a Stop button, and a status line.
3.  Own the three driver threads and the DataLogger.
4.  Wire each driver's four signals to the corresponding panel's four
    slots, AND to a central `_on_data` router that feeds the DataLogger.
5.  Run a QTimer at config.CSV_WRITE_INTERVAL_MS that calls
    logger.snapshot() once per tick.
6.  On closeEvent: stop drivers (cooperatively, then join), stop the
    timer, flush and close the logger.

Design rules that this file obeys
---------------------------------
1.  Only this module imports drivers.py, data_logger.py, and panels.py.
    None of those import each other or this file.
2.  The GUI thread never blocks on serial I/O. All I/O is inside the
    driver QThreads.
3.  Start / Stop are idempotent: pressing Start twice is safe, and
    pressing Stop twice is safe.
4.  Stopping waits for each thread with a timeout. If a thread does not
    stop in time, we log a warning but still proceed to close the
    logger, so the user never loses already-recorded rows.
5.  A CSV row is written ONLY while the app is in the "running" state.
    Pressing Start opens a new session file; pressing Stop closes it.
    This matches the intuitive mental model of a "record" button.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Dict, Optional

from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

import config
from data_logger import DataLogger
from drivers import ElectronicLoadDriver, FlowMeterDriver, FuelCellDriver
from panels import ElectronicLoadPanel, FlowMeterPanel, FuelCellPanel


# How long to wait for each driver thread to exit on Stop / close.
_DRIVER_JOIN_TIMEOUT_MS = 3000


class MainWindow(QMainWindow):

    # =====================================================================
    # Construction
    # =====================================================================

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"{config.APP_NAME} v{config.APP_VERSION}")
        self.setMinimumSize(config.WINDOW_MIN_WIDTH, config.WINDOW_MIN_HEIGHT)

        # --- runtime state ------------------------------------------------
        self._logger = DataLogger()
        self._load_driver: Optional[ElectronicLoadDriver] = None
        self._flow_driver: Optional[FlowMeterDriver] = None
        self._fuelcell_driver: Optional[FuelCellDriver] = None
        self._running = False

        # --- panels -------------------------------------------------------
        self._load_panel = ElectronicLoadPanel()
        self._flow_panel = FlowMeterPanel()
        self._fuelcell_panel = FuelCellPanel()

        # --- CSV write timer ---------------------------------------------
        self._csv_timer = QTimer(self)
        self._csv_timer.setInterval(config.CSV_WRITE_INTERVAL_MS)
        self._csv_timer.timeout.connect(self._on_csv_tick)

        # --- build UI -----------------------------------------------------
        self._build_ui()
        self._refresh_port_dropdowns()

    # =====================================================================
    # UI construction
    # =====================================================================

    def _build_ui(self) -> None:
        central = QWidget(self)
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)

        # --- three panels side by side ------------------------------------
        panels_row = QGridLayout()
        panels_row.setHorizontalSpacing(12)
        panels_row.addWidget(self._load_panel,     0, 0)
        panels_row.addWidget(self._flow_panel,     0, 1)
        panels_row.addWidget(self._fuelcell_panel, 0, 2)
        for col in range(3):
            panels_row.setColumnStretch(col, 1)
        outer.addLayout(panels_row, stretch=1)

        # --- control bar --------------------------------------------------
        controls = QHBoxLayout()

        # Port selectors (three)
        self._load_port_combo = QComboBox()
        self._flow_port_combo = QComboBox()
        self._fuelcell_port_combo = QComboBox()
        for combo, label_text in (
            (self._load_port_combo,      "Load port:"),
            (self._flow_port_combo,      "Flow port:"),
            (self._fuelcell_port_combo,  "Fuel cell port:"),
        ):
            combo.setMinimumWidth(160)
            controls.addWidget(QLabel(label_text))
            controls.addWidget(combo)

        # Refresh button for the port list
        self._refresh_ports_btn = QPushButton("Refresh ports")
        self._refresh_ports_btn.clicked.connect(self._refresh_port_dropdowns)
        controls.addWidget(self._refresh_ports_btn)

        # Output folder chooser
        self._output_dir_btn = QPushButton("Choose CSV folder…")
        self._output_dir_btn.clicked.connect(self._choose_output_folder)
        controls.addWidget(self._output_dir_btn)

        # Start / Stop
        self._start_btn = QPushButton("Start recording")
        self._start_btn.clicked.connect(self._on_start)
        controls.addWidget(self._start_btn)

        self._stop_btn = QPushButton("Stop recording")
        self._stop_btn.clicked.connect(self._on_stop)
        self._stop_btn.setEnabled(False)
        controls.addWidget(self._stop_btn)

        outer.addLayout(controls)

        # --- status line --------------------------------------------------
        self._status_label = QLabel("Idle.")
        self._status_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        outer.addWidget(self._status_label)

    # =====================================================================
    # Port dropdown management
    # =====================================================================

    def _list_serial_ports(self) -> list:
        """Return a list of device paths. Empty list on any import error."""
        try:
            import serial.tools.list_ports  # local import: only needed here
        except Exception:
            return []
        return [p.device for p in serial.tools.list_ports.comports()]

    def _refresh_port_dropdowns(self) -> None:
        """
        Repopulate the three port dropdowns from the OS port list.

        Preserves the user's current selection if it still exists.
        Applies the config.py default as a *suggestion* only.
        """
        ports = self._list_serial_ports()

        suggestions = {
            self._load_port_combo:     config.DEFAULT_LOAD_PORT,
            self._flow_port_combo:     config.DEFAULT_FLOW_PORT,
            self._fuelcell_port_combo: config.DEFAULT_SUSY_PORT,
        }

        for combo, suggestion in suggestions.items():
            current = combo.currentText()
            combo.blockSignals(True)
            combo.clear()

            if not ports:
                combo.addItem(config.PORT_PLACEHOLDER)
                combo.setEnabled(False)
                combo.blockSignals(False)
                continue

            combo.addItems(ports)
            combo.setEnabled(True)

            # Prefer the previously selected port, then the config
            # suggestion, then the first entry.
            if current in ports:
                combo.setCurrentText(current)
            elif suggestion in ports:
                combo.setCurrentText(suggestion)
            else:
                combo.setCurrentIndex(0)

            combo.blockSignals(False)

    # =====================================================================
    # Output folder
    # =====================================================================

    def _choose_output_folder(self) -> None:
        if self._running:
            QMessageBox.warning(
                self,
                "Recording in progress",
                "Stop recording before changing the CSV folder.",
            )
            return

        chosen = QFileDialog.getExistingDirectory(
            self, "Choose folder for session CSV files", str(Path.cwd()),
        )
        if chosen:
            self._logger = DataLogger(output_dir=chosen)
            self._status_label.setText(f"CSV folder: {chosen}")

    # =====================================================================
    # Start / Stop
    # =====================================================================

    @Slot()
    def _on_start(self) -> None:
        if self._running:
            return

        load_port = self._selected_port(self._load_port_combo)
        flow_port = self._selected_port(self._flow_port_combo)
        fuel_port = self._selected_port(self._fuelcell_port_combo)

        if load_port is None or flow_port is None or fuel_port is None:
            QMessageBox.critical(
                self,
                "Missing port",
                "Select a valid port for all three devices before starting.",
            )
            return

        if len({load_port, flow_port, fuel_port}) != 3:
            QMessageBox.critical(
                self,
                "Duplicate port",
                "Each device must use a different serial port.",
            )
            return

        # --- open the CSV first (so we fail before spinning threads) -----
        try:
            csv_path = self._logger.open()
        except Exception as exc:                    # noqa: BLE001
            QMessageBox.critical(
                self, "Could not open CSV",
                f"Failed to create session file:\n{exc}",
            )
            return

        # --- construct and start the three drivers -----------------------
        self._load_driver = ElectronicLoadDriver(load_port)
        self._flow_driver = FlowMeterDriver(flow_port)
        self._fuelcell_driver = FuelCellDriver(fuel_port)

        self._wire_driver(
            self._load_driver, self._load_panel,
            self._on_load_data,
        )
        self._wire_driver(
            self._flow_driver, self._flow_panel,
            self._on_flow_data,
        )
        self._wire_driver(
            self._fuelcell_driver, self._fuelcell_panel,
            self._on_fuelcell_data,
        )

        self._load_driver.start()
        self._flow_driver.start()
        self._fuelcell_driver.start()

        self._csv_timer.start()
        self._running = True

        self._start_btn.setEnabled(False)
        self._stop_btn.setEnabled(True)
        self._refresh_ports_btn.setEnabled(False)
        self._output_dir_btn.setEnabled(False)
        self._load_port_combo.setEnabled(False)
        self._flow_port_combo.setEnabled(False)
        self._fuelcell_port_combo.setEnabled(False)

        self._status_label.setText(f"Recording → {csv_path}")

    @Slot()
    def _on_stop(self) -> None:
        if not self._running:
            return
        self._stop_everything()
        self._status_label.setText(
            f"Stopped. {self._logger.row_count} rows written."
        )

    def _stop_everything(self) -> None:
        """
        Stop timer, join threads, close logger. Safe to call twice.
        """
        # 1. Stop the CSV timer first: no more snapshot() calls.
        self._csv_timer.stop()

        # 2. Ask drivers to stop.
        for driver in (
            self._load_driver, self._flow_driver, self._fuelcell_driver,
        ):
            if driver is not None:
                driver.stop()

        # 3. Join them with a timeout so a hung device can't freeze close.
        for driver in (
            self._load_driver, self._flow_driver, self._fuelcell_driver,
        ):
            if driver is not None and driver.isRunning():
                if not driver.wait(_DRIVER_JOIN_TIMEOUT_MS):
                    self._status_label.setText(
                        "Warning: a device thread did not stop in time."
                    )

        # 4. Close the CSV.
        try:
            self._logger.close()
        except Exception as exc:                    # noqa: BLE001
            self._status_label.setText(f"Error closing CSV: {exc}")

        # 5. Reset state
        self._load_driver = None
        self._flow_driver = None
        self._fuelcell_driver = None
        self._running = False

        self._start_btn.setEnabled(True)
        self._stop_btn.setEnabled(False)
        self._refresh_ports_btn.setEnabled(True)
        self._output_dir_btn.setEnabled(True)
        self._load_port_combo.setEnabled(True)
        self._flow_port_combo.setEnabled(True)
        self._fuelcell_port_combo.setEnabled(True)

    # =====================================================================
    # Signal wiring helpers
    # =====================================================================

    def _wire_driver(self, driver, panel, data_slot) -> None:
        """
        Connect a driver's four signals to:
            * the matching panel slot,
            * the per-device data router on this window.
        """
        driver.data_ready.connect(panel.update_values)
        driver.data_ready.connect(data_slot)

        driver.connected.connect(panel.update_connected)
        driver.connected.connect(self._make_connected_logger(driver))

        driver.error.connect(panel.update_error)
        driver.error.connect(self._make_error_logger(driver))

        driver.disconnected.connect(panel.mark_disconnected)

    def _make_connected_logger(self, driver):
        @Slot(str)
        def _slot(identity: str) -> None:
            name = self._driver_name(driver)
            self._status_label.setText(f"{name} connected: {identity}")
        return _slot

    def _make_error_logger(self, driver):
        @Slot(str)
        def _slot(message: str) -> None:
            name = self._driver_name(driver)
            self._status_label.setText(f"{name} error: {message}")
        return _slot

    @staticmethod
    def _driver_name(driver) -> str:
        if isinstance(driver, ElectronicLoadDriver):
            return "Load"
        if isinstance(driver, FlowMeterDriver):
            return "Flow"
        if isinstance(driver, FuelCellDriver):
            return "Fuel cell"
        return "Device"

    # =====================================================================
    # Data routing: driver -> DataLogger
    # =====================================================================

    @Slot(dict)
    def _on_load_data(self, values: Dict[str, object]) -> None:
        self._logger.update(values)

    @Slot(dict)
    def _on_flow_data(self, values: Dict[str, object]) -> None:
        self._logger.update(values)

    @Slot(dict)
    def _on_fuelcell_data(self, values: Dict[str, object]) -> None:
        self._logger.update(values)

    # =====================================================================
    # CSV tick
    # =====================================================================

    @Slot()
    def _on_csv_tick(self) -> None:
        if not self._running:
            return
        try:
            self._logger.snapshot()
        except Exception as exc:                    # noqa: BLE001
            # A failing snapshot must not crash the app. Stop recording
            # and surface the error.
            self._status_label.setText(f"CSV write error: {exc}")
            self._on_stop()

    # =====================================================================
    # Helpers
    # =====================================================================

    @staticmethod
    def _selected_port(combo: QComboBox) -> Optional[str]:
        """Return the selected port string, or None if placeholder / empty."""
        text = combo.currentText().strip()
        if not text or text == config.PORT_PLACEHOLDER:
            return None
        return text

    # =====================================================================
    # Shutdown
    # =====================================================================

    def closeEvent(self, event) -> None:            # noqa: N802 (Qt name)
        """
        Stop drivers, stop timer, close CSV. Then let Qt close the window.
        """
        if self._running:
            try:
                self._stop_everything()
            except Exception:
                # Never block window close on cleanup errors.
                pass
        else:
            # Even if never started, make sure the logger is closed.
            try:
                self._logger.close()
            except Exception:
                pass
        super().closeEvent(event)
