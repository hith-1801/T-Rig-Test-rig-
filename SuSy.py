import serial
import serial.tools.list_ports
import time
from datetime import datetime

# =========================
# USER SETTINGS
# =========================
BAUDRATE = 9600
TIMEOUT = 1           # seconds
POLL_INTERVAL = 1.0   # seconds between full polling cycles

# =========================
# PORT SELECTION
# =========================
def select_port():
    ports = list(serial.tools.list_ports.comports())
    if not ports:
        print("No serial ports found. Check that the SuSy is connected.")
        raise SystemExit(1)

    print("Available Ports:")
    for i, p in enumerate(ports):
        print(f"  {i}: {p.device} - {p.description}")

    if len(ports) == 1:
        print(f"Only one port found. Using {ports[0].device}")
        return ports[0].device

    idx = int(input("Select SuSy port index: "))
    return ports[idx].device

# =========================
# SCPI-STYLE QUERY
# =========================
def query(ser, command, delay=0.1):
    """Send a command and return the stripped ASCII response."""
    ser.reset_input_buffer()
    ser.write(command.encode("ascii") + b"\r")
    time.sleep(delay)
    raw = ser.readline().decode("ascii", errors="ignore").strip()
    return raw

# =========================
# MAIN
# =========================
def main():
    port = select_port()
    print(f"\nConnecting to SuSy on {port} at {BAUDRATE} baud...\n")

    with serial.Serial(port, BAUDRATE, timeout=TIMEOUT) as ser:
        time.sleep(0.5)
        ser.reset_input_buffer()
        ser.reset_output_buffer()

        # Identify device once
        idn = query(ser, "*idn?")
        print(f"Connected to: {idn}\n")

        header = f"{'Time':>8} | {'Voltage (mV)':>12} | {'Current (mA)':>12} | {'Temp (°C)':>10} | {'Pressure (mbar)':>15} | {'Error':>6}"
        print(header)
        print("-" * len(header))

        start_time = time.time()

        try:
            while True:
                try:
                    voltage  = query(ser, "*vol?")
                    current  = query(ser, "*cur?")
                    temp     = query(ser, "*temp?")
                    pressure = query(ser, "*pres?")   # SuSy500 only
                    error    = query(ser, "*error?")  # SuSy500 only

                    t = time.time() - start_time
                    print(f"{t:8.2f} | {voltage:>12} | {current:>12} | {temp:>10} | {pressure:>15} | {error:>6}")

                except serial.SerialException as e:
                    print(f"\nSerial error: {e}")
                    break

                time.sleep(POLL_INTERVAL)

        except KeyboardInterrupt:
            print("\nStopped by user.")
        finally:
            print("Closing serial port.")

if __name__ == "__main__":
    main()
