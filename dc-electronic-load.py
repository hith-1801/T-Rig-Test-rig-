import serial
import time

PORT = "/dev/ttyACM0"   # or /dev/ttyUSB1 — whichever your working script used
BAUDRATE = 19200        # keep what worked

def query(ser, command, delay=0.1):
    """Send a SCPI command and return the stripped response."""
    ser.write(command.encode("ascii") + b"\n")
    time.sleep(delay)
    return ser.readline().decode("ascii", errors="ignore").strip()

def main():
    with serial.Serial(PORT, BAUDRATE, timeout=1) as ser:
        time.sleep(0.5)
        ser.reset_input_buffer()
        ser.reset_output_buffer()

        # Identify device once
        idn = query(ser, "*IDN?")
        print(f"Connected to: {idn}\n")
        print(f"{'Time (s)':>10} | {'Voltage (V)':>12} | {'Current (A)':>12} | {'Function':>10}")
        print("-" * 55)

        start_time = time.time()

        try:
            while True:
                voltage = query(ser, ":MEAS:VOLT?")
                current = query(ser, ":MEAS:CURR?")
                function = query(ser, ":FUNC?")

                t = time.time() - start_time
                print(f"{t:10.2f} | {voltage:>12} | {current:>12} | {function:>10}")

                time.sleep(0.5)  # polling interval

        except KeyboardInterrupt:
            print("\nStopped by user.")
        finally:
            print("Closing serial port.")

if __name__ == "__main__":
    main()
