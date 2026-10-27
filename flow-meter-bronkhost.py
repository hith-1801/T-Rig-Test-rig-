#!/usr/bin/env python3
"""
Bronkhorst EL-FLOW F-111B Mass Flow Meter Reader
Simplified continuous reader - shows timestamp and actual flow rate until Ctrl+C
"""

import propar
import serial
import serial.tools.list_ports
import time
from datetime import datetime
import argparse
import sys
import signal


class BronkhorstFlowReader:
    """Class to handle communication with Bronkhorst EL-FLOW mass flow meter"""
    
    # Parameter addresses based on ProPar protocol
    # Process number 33: Extended Variables  
    PARAM_FMEASURE = (33, 0)       # Actual flow as FLOAT (engineering units)
    
    # Process number 37: Device Information
    PARAM_PRODUCT_CODE = (37, 1)   # Product code (STRING)
    PARAM_SERIAL_NUMBER = (37, 2)  # Serial number (STRING)
    
    # Device address - default is usually 0x80 for local instrument
    DEVICE_ADDRESS = 0x80
    
    def __init__(self, port, baudrate=38400, address=None):
        """
        Initialize connection to Bronkhorst flow meter
        
        Args:
            port: Serial port (e.g., '/dev/ttyUSB0' or 'COM3')
            baudrate: Communication baud rate (default 38400)
            address: Device address (default 0x80)
        """
        self.port = port
        self.baudrate = baudrate
        self.address = address or self.DEVICE_ADDRESS
        self.instrument = None
        self._running = False
        
    def connect(self):
        """Establish connection with the flow meter"""
        try:
            self.instrument = propar.instrument(
                self.port, 
                baudrate=self.baudrate, 
                address=self.address
            )
            print(f"✓ Connected to {self.port} at {self.baudrate} baud")
            return True
        except Exception as e:
            print(f"✗ Connection failed: {e}")
            return False
    
    def get_device_info(self):
        """Retrieve device information"""
        info = {}
        try:
            info['product_code'] = self.instrument.read(
                self.PARAM_PRODUCT_CODE[0], 
                self.PARAM_PRODUCT_CODE[1], 
                propar.PP_TYPE_STRING
            )
            
            info['serial_number'] = self.instrument.read(
                self.PARAM_SERIAL_NUMBER[0],
                self.PARAM_SERIAL_NUMBER[1],
                propar.PP_TYPE_STRING
            )
        except Exception as e:
            print(f"Warning: Could not read device info: {e}")
            info['product_code'] = "Unknown"
            info['serial_number'] = "Unknown"
            
        return info
    
    def get_actual_flow(self):
        """
        Read actual flow rate in engineering units (e.g., ln/min, g/h)
        
        Returns:
            float: Current flow rate, or None if read fails
        """
        try:
            flow = self.instrument.read(
                self.PARAM_FMEASURE[0],
                self.PARAM_FMEASURE[1],
                propar.PP_TYPE_FLOAT
            )
            return flow
        except Exception as e:
            print(f"Error reading flow: {e}")
            return None
    
    def start_continuous_readings(self):
        """
        Continuously read and display flow data until interrupted
        """
        self._running = True
        
        # Set up signal handler for graceful shutdown
        def signal_handler(sig, frame):
            print("\n\nStopping data collection...")
            self._running = False
        signal.signal(signal.SIGINT, signal_handler)
        
        read_count = 0
        
        print("\n=== Starting Continuous Flow Monitoring ===")
        print("Press Ctrl+C to stop\n")
        
        try:
            while self._running:
                # Get current timestamp
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
                
                # Read flow data
                flow = self.get_actual_flow()
                read_count += 1
                
                # Display reading
                if flow is not None:
                    print(f"[{timestamp}] Flow: {flow:.3f} ln/min")
                else:
                    print(f"[{timestamp}] Flow: N/A")
                
                # Wait 1 second between readings
                time.sleep(1)
                
        except KeyboardInterrupt:
            print("\n\nData collection stopped by user.")
        finally:
            print(f"\nTotal readings taken: {read_count}")
    
    def disconnect(self):
        """Close the serial connection"""
        if self.instrument:
            self.instrument = None
            print("Disconnected from flow meter")


def find_bronkhorst_port():
    """
    Automatically detect Bronkhorst device on available serial ports
    
    Returns:
        str: Port name if found, None otherwise
    """
    print("Scanning for Bronkhorst device...", end="", flush=True)
    
    available_ports = serial.tools.list_ports.comports()
    
    for port in available_ports:
        print(".", end="", flush=True)
        
        # Try to connect to the port with Bronkhorst parameters
        try:
            # Quick test - attempt to read device info
            test_instr = propar.instrument(port.device, baudrate=38400, address=0x80)
            test_instr.timeout = 1.0  # Short timeout for detection
            
            # Try to read a basic parameter (Control Mode)
            result = test_instr.read(1, 4, propar.PP_TYPE_INT8)
            
            # If we get here, communication succeeded
            print(f"\n✓ Bronkhorst device found on {port.device}")
            return port.device
            
        except Exception:
            # Not a Bronkhorst device or not responding
            continue
    
    print("\n✗ No Bronkhorst device found.")
    return None


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description='Bronkhorst EL-FLOW F-111B Mass Flow Meter - Continuous Reader'
    )
    parser.add_argument(
        '-p', '--port',
        help='Serial port (e.g., /dev/ttyUSB0). Auto-detects if not specified'
    )
    parser.add_argument(
        '-b', '--baudrate',
        type=int,
        default=38400,
        help='Baud rate (default: 38400)'
    )
    parser.add_argument(
        '-a', '--address',
        type=int,
        default=0x80,
        help='Device address (default: 0x80)'
    )
    
    args = parser.parse_args()
    
    # Auto-detect port if not specified
    port = args.port
    if not port:
        port = find_bronkhorst_port()
        if not port:
            sys.exit(1)
    else:
        print(f"Using specified port: {port}")
    
    # Create reader instance
    reader = BronkhorstFlowReader(port, args.baudrate, args.address)
    
    # Connect to device
    if not reader.connect():
        sys.exit(1)
    
    try:
        # Display device info
        print("\n=== Device Information ===")
        info = reader.get_device_info()
        print(f"Product Code:    {info['product_code']}")
        print(f"Serial Number:    {info['serial_number']}")
        print("============================")
        
        # Start continuous readings
        reader.start_continuous_readings()
        
    finally:
        reader.disconnect()


if __name__ == "__main__":
    main()