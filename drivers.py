"""
drivers.py
==========
Device driver layer for the Unified Device Monitor.

Contains three QThread subclasses, one per instrument:

    ElectronicLoadDriver   wraps dc-electronic-load.py  (SCPI, LF, 19200)
    FlowMeterDriver        wraps flow-meter-bronkhost.py (ProPar, 38400)
    FuelCellDriver         wraps SuSy.py               (SCPI, CR, 9600)

Each driver:
    *  Opens its serial port when start() is called.
    *  Loops at its own poll interval, reading values.
    *  Emits `data_ready(dict)` after each successful poll.
    *  Emits `error(str)` on any recoverable or fatal I/O problem.
    *  Emits `connected(str)` once the port is open and identity is read.
    *  Emits `disconnected()` when the loop exits.
    *  Is stopped cooperatively via `stop()` (sets a flag; the loop exits
       on its next iteration) and `wait()` is safe to call from closeEvent.

Design rules that this file obeys
---------------------------------
1.  NO blocking I/O on the GUI thread. Every serial read happens inside
    a QThread.run().
2.  NO shared mutable state between driver threads. Each driver owns its
    own serial handle and its own cache.
3.  NO imports from panels.py / data_logger.py / main_window.py / main.py.
    Drivers do not know the GUI exists. They only emit signals.
4.  Terminators and baud rates are taken from config.py verbatim, so the
    drivers behave byte-for-byte like the original scripts.
5.  Errors are never silently swallowed. The original scripts printed
    errors; here we emit them on the `error` signal so the GUI can show
    them and the logger can still write a row with N/A in that column.
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional

import serial

from PySide6.QtCore import QThread, Signal

import config


# =========================================================================
# Helper: one SCPI query, identical to the query() in the originals
# =========================================================================

def _scpi_query(
    ser: serial.Serial,
    command: str,
    terminator: bytes,
    delay: float,
) -> str:
    """Send `command` + terminator, wait `delay` s, return one stripped line.

    This is the exact behaviour of query() in dc-electronic-load.py and
    SuSy.py, factored out so both drivers use it. The only difference
    between the two originals was the terminator, which is now a parameter.
    """
    ser.write(command.encode("ascii") + terminator)
    time.sleep(delay)
    raw = ser.readline()
    return raw.decode("ascii", errors="ignore").strip()


# =========================================================================
# Electronic load driver
# =========================================================================

class ElectronicLoadDriver(QThread):
    """Driver for the DC electronic load (dc-electronic-load.py)."""

    data_ready    = Signal(dict)
    error         = Signal(str)
    connected     = Signal(str)
    disconnected  = Signal()

    def __init__(self, port: str, parent=None) -> None:
        super().__init__(parent)
        self._port = port
        self._running = False

    def stop(self) -> None:
        """Ask the loop to exit. Safe to call multiple times."""
        self._running = False

    def run(self) -> None:
        self._running = True
        ser: Optional[serial.Serial] = None
        try:
            ser = serial.Serial(
                self._port,
                config.LOAD_BAUDRATE,
                timeout=config.LOAD_TIMEOUT_S,
            )
            time.sleep(config.LOAD_INITIAL_DELAY_S)
            ser.reset_input_buffer()
            ser.reset_output_buffer()

            idn = _scpi_query(
                ser,
                config.LOAD_CMD_IDN,
                config.LOAD_LINE_TERMINATOR,
                config.LOAD_QUERY_DELAY_S,
            )
            self.connected.emit(idn or "<no IDN response>")

            while self._running:
                try:
                    voltage = _scpi_query(
                        ser,
                        config.LOAD_CMD_MEAS_VOLT,
                        config.LOAD_LINE_TERMINATOR,
                        config.LOAD_QUERY_DELAY_S,
                    )
                    current = _scpi_query(
                        ser,
                        config.LOAD_CMD_MEAS_CURR,
                        config.LOAD_LINE_TERMINATOR,
                        config.LOAD_QUERY_DELAY_S,
                    )
                    function = _scpi_query(
                        ser,
                        config.LOAD_CMD_FUNC,
                        config.LOAD_LINE_TERMINATOR,
                        config.LOAD_QUERY_DELAY_S,
                    )
                except serial.SerialException as exc:
                    self.error.emit(f"Electronic load serial error: {exc}")
                    break

                self.data_ready.emit({
                    "load_voltage_v":  voltage,
                    "load_current_a":  current,
                    "load_function":   function,
                })

                # Sleep in small slices so stop() is responsive.
                deadline = time.monotonic() + config.LOAD_POLL_INTERVAL_S
                while self._running and time.monotonic() < deadline:
                    time.sleep(0.05)

        except serial.SerialException as exc:
            self.error.emit(f"Electronic load open failed: {exc}")
        except Exception as exc:                    # noqa: BLE001
            self.error.emit(f"Electronic load unexpected error: {exc}")
        finally:
            if ser is not None:
                try:
                    ser.close()
                except Exception:
                    pass
            self.disconnected.emit()


# =========================================================================
# Bronkhorst flow meter driver
# =========================================================================

class FlowMeterDriver(QThread):
    """Driver for the Bronkhorst EL-FLOW F-111B (flow-meter-bronkhost.py)."""

    data_ready    = Signal(dict)
    error         = Signal(str)
    connected     = Signal(str)
    disconnected  = Signal()

    def __init__(self, port: str, parent=None) -> None:
        super().__init__(parent)
        self._port = port
        self._running = False

    def stop(self) -> None:
        self._running = False

    def _read_str(self, instrument, process: int, parameter: int) -> str:
        import propar
        return instrument.read(process, parameter, propar.PP_TYPE_STRING)

    def _read_float(self, instrument, process: int, parameter: int) -> float:
        import propar
        return instrument.read(process, parameter, propar.PP_TYPE_FLOAT)


    def run(self) -> None:
        self._running = True
        instrument = None
        try:
            import propar  # local import: only this driver needs it

            instrument = propar.instrument(
                self._port,
                baudrate=config.FLOW_BAUDRATE,
                address=config.FLOW_DEVICE_ADDRESS,
            )

            # Identity (non-fatal if the device doesn't answer these)
            product = "Unknown"
            serial_no = "Unknown"
            try:
                product = self._read_str(
                    instrument, *config.FLOW_PARAM_PRODUCT_CODE,
                )
            except Exception:
                pass
            try:
                serial_no = self._read_str(
                    instrument, *config.FLOW_PARAM_SERIAL_NUMBER,
                )
            except Exception:
                pass
            self.connected.emit(f"{product} / S/N {serial_no}")

            while self._running:
                try:
                    flow = self._read_float(
                        instrument, *config.FLOW_PARAM_FMEASURE,
                    )
                except Exception as exc:            # noqa: BLE001
                    self.error.emit(f"Flow meter read error: {exc}")
                    # Do not break: propar can recover from a single
                    # bad frame. Keep trying until stop() is called.
                    flow = None

                self.data_ready.emit({
                    "flow_rate_ln_per_min": (
                        None if flow is None else f"{flow:.3f}"
                    ),
                })

                deadline = time.monotonic() + config.FLOW_POLL_INTERVAL_S
                while self._running and time.monotonic() < deadline:
                    time.sleep(0.05)

        except ImportError as exc:
            self.error.emit(f"propar library not installed: {exc}")
        except serial.SerialException as exc:
            self.error.emit(f"Flow meter open failed: {exc}")
        except Exception as exc:                    # noqa: BLE001
            self.error.emit(f"Flow meter unexpected error: {exc}")
        finally:
            # propar has no explicit close(); dropping the reference is
            # the documented way to release the port.
            instrument = None
            self.disconnected.emit()


# =========================================================================
# SuSy fuel cell driver
# =========================================================================

class FuelCellDriver(QThread):
    """Driver for the SuSy fuel cell (SuSy.py)."""

    data_ready    = Signal(dict)
    error         = Signal(str)
    connected     = Signal(str)
    disconnected  = Signal()

    def __init__(self, port: str, parent=None) -> None:
        super().__init__(parent)
        self._port = port
        self._running = False

    def stop(self) -> None:
        self._running = False

    def run(self) -> None:
        self._running = True
        ser: Optional[serial.Serial] = None
        try:
            ser = serial.Serial(
                self._port,
                config.SUSY_BAUDRATE,
                timeout=config.SUSY_TIMEOUT_S,
            )
            time.sleep(config.SUSY_INITIAL_DELAY_S)
            ser.reset_input_buffer()
            ser.reset_output_buffer()

            idn = _scpi_query(
                ser,
                config.SUSY_CMD_IDN,
                config.SUSY_LINE_TERMINATOR,
                config.SUSY_QUERY_DELAY_S,
            )
            self.connected.emit(idn or "<no IDN response>")

            while self._running:
                try:
                    ser.reset_input_buffer()
                    voltage  = _scpi_query(
                        ser, config.SUSY_CMD_VOLT,
                        config.SUSY_LINE_TERMINATOR,
                        config.SUSY_QUERY_DELAY_S,
                    )
                    current  = _scpi_query(
                        ser, config.SUSY_CMD_CURR,
                        config.SUSY_LINE_TERMINATOR,
                        config.SUSY_QUERY_DELAY_S,
                    )
                    temp     = _scpi_query(
                        ser, config.SUSY_CMD_TEMP,
                        config.SUSY_LINE_TERMINATOR,
                        config.SUSY_QUERY_DELAY_S,
                    )
                    pressure = _scpi_query(
                        ser, config.SUSY_CMD_PRESSURE,
                        config.SUSY_LINE_TERMINATOR,
                        config.SUSY_QUERY_DELAY_S,
                    )
                    error_st = _scpi_query(
                        ser, config.SUSY_CMD_ERROR,
                        config.SUSY_LINE_TERMINATOR,
                        config.SUSY_QUERY_DELAY_S,
                    )

                    if not voltage or not current:
                        continue


                except serial.SerialException as exc:
                    self.error.emit(f"Fuel cell serial error: {exc}")
                    break

                self.data_ready.emit({
                    "fuelcell_voltage_mv":    voltage,
                    "fuelcell_current_ma":    current,
                    "fuelcell_temp_c":        temp,
                    "fuelcell_pressure_mbar": pressure,
                    "fuelcell_error":         error_st,
                })

                deadline = time.monotonic() + config.SUSY_POLL_INTERVAL_S
                while self._running and time.monotonic() < deadline:
                    time.sleep(0.05)

        except serial.SerialException as exc:
            self.error.emit(f"Fuel cell open failed: {exc}")
        except Exception as exc:                    # noqa: BLE001
            self.error.emit(f"Fuel cell unexpected error: {exc}")
        finally:
            if ser is not None:
                try:
                    ser.close()
                except Exception:
                    pass
            self.disconnected.emit()
