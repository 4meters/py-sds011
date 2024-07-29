"""This module provides an abstraction for the SDS011 air particulate density sensor.
"""
import struct
import serial

#TODO: Commands against the sensor should read the reply and return success status.

class SDS011(object):
    """Provides method to read from a SDS011 air particulate density sensor
    using UART.
    """

    HEAD = b'\xaa'
    TAIL = b'\xab'
    CMD_ID = b'\xb4'

    # The sent command is a read or a write
    READ = b"\x00"
    WRITE = b"\x01"

    REPORT_MODE_CMD = b"\x02"
    ACTIVE = b"\x00"
    PASSIVE = b"\x01"

    QUERY_CMD = b"\x04"

    # The sleep command ID
    SLEEP_CMD = b"\x06"
    # Sleep and work byte
    SLEEP = b"\x00"
    WORK = b"\x01"

    # The work period command ID
    WORK_PERIOD_CMD = b'\x08'

    FIRMWARE_VERSION_CMD = b'\x07'
    
    def __init__(self, serial_port, baudrate=9600, timeout=2,
                 use_query_mode=True):
        """Initialise and open serial port.
        """
        self.port = serial_port
        self.baudrate = baudrate
        self.timeout = timeout
        self.use_query_mode = use_query_mode
        self.ser = serial.Serial(port=serial_port,
                                 baudrate=baudrate,
                                 timeout=timeout)
        self.ser.flush()
        self.set_report_mode(query=use_query_mode)

    def __del__(self):
        try:
            if not self.is_serial_open():
                self.open_serial()
                self.sleep()
            self.ser.close()
        except serial.SerialException as e:
            print("Serial Exception when destructing SDS011 class")
        except Exception as e:
            print("Exception when destructing SDS011 class")

    def is_serial_open(self):
        return self.ser.isOpen()

    def close_serial(self):
        self.ser.close()

    def open_serial(self):
        self.ser = serial.Serial(port=self.port,
                                 baudrate=self.baudrate,
                                 timeout=self.timeout)
        self.ser.flush()
        self.set_report_mode(query=self.use_query_mode)

    def _execute(self, cmd_bytes):
        """Writes a byte sequence to the serial.
        """
        if not self.is_serial_open():
            self.open_serial()
        self.ser.write(cmd_bytes)

    def _get_reply(self):
        """Read reply from device."""
        if not self.is_serial_open():
            self.open_serial()
        raw = self.ser.read(size=10)
        data = raw[2:8]
        if len(data) == 0:
            return None
        if (sum(d for d in data) & 255) != raw[8]:
            return None  #TODO: also check cmd id
        return raw

    def cmd_begin(self):
        """Get command header and command ID bytes.
        @rtype: list
        """
        return self.HEAD + self.CMD_ID

    def set_report_mode(self, read=False, query=True):
        """Get sleep command. Does not contain checksum and tail.
        @rtype: list
        """
        self.use_query_mode = query
        cmd = self.cmd_begin()
        cmd += (self.REPORT_MODE_CMD
                + (self.READ if read else self.WRITE)
                + (self.PASSIVE if query else self.ACTIVE)
                + b"\x00" * 10)
        cmd = self._finish_cmd(cmd)
        self._execute(cmd)
        raw = self._get_reply()
        if raw is None:
            return None
        data = struct.unpack('B', raw[4:5])
        return data[0] # passive(query) 1, active reporting 0

    def query(self):
        """Query the device and read the data.

        @return: Air particulate density in micrograms per cubic meter.
        @rtype: tuple(float, float) -> (PM2.5, PM10)
        """
        cmd = self.cmd_begin()
        cmd += (self.QUERY_CMD
                + b"\x00" * 12)
        cmd = self._finish_cmd(cmd)
        self._execute(cmd)

        raw = self._get_reply()
        if raw is None:
            if self.use_query_mode == 0:
                print("SDS011 is in active reporting mode, use read()")
            return None
        data = struct.unpack('<HH', raw[2:6])
        pm25 = data[0] / 10.0
        pm10 = data[1] / 10.0
        return (pm25, pm10)

    def sleep(self, read=False, sleep=True):
        """Sleep/Wake up the sensor.

        @param sleep: Whether the device should sleep or work.
        @type sleep: bool
        """
        cmd = self.cmd_begin()
        cmd += (self.SLEEP_CMD
                + (self.READ if read else self.WRITE)
                + (self.SLEEP if sleep else self.WORK)
                + b"\x00" * 10)
        cmd = self._finish_cmd(cmd)
        self._execute(cmd)
        raw = self._get_reply()
        if raw is None:
            return 0
        data = struct.unpack('B', raw[4:5]) #1=work, 0=sleep
        return data[0]

    def set_work_period(self, read=False, work_time=0):
        """Get work period command. Does not contain checksum and tail.
        @rtype: list
        """
        assert work_time >= 0 and work_time <= 30
        cmd = self.cmd_begin()
        cmd += (self.WORK_PERIOD_CMD
                + (self.READ if read else self.WRITE)
                + bytes([work_time])
                + b"\x00" * 10)
        cmd = self._finish_cmd(cmd)
        self._execute(cmd)
        self._get_reply()

    def _finish_cmd(self, cmd, id1=b"\xff", id2=b"\xff"):
        """Add device ID, checksum and tail bytes.
        @rtype: list
        """
        cmd += id1 + id2
        checksum = sum(d for d in cmd[2:]) % 256
        cmd += bytes([checksum]) + self.TAIL
        return cmd

    def _process_frame(self, data):
        """Process a SDS011 data frame.

        Byte positions:
            0 - Header
            1 - Command No.
            2,3 - PM2.5 low/high byte
            4,5 - PM10 low/high
            6,7 - ID bytes
            8 - Checksum - sum of bytes 2-7
            9 - Tail
        """
        raw = struct.unpack('<HHxxBBB', data[2:])
        checksum = sum(v for v in data[2:8]) % 256
        if checksum != data[8]:
            return None
        pm25 = raw[0] / 10.0
        pm10 = raw[1] / 10.0
        return (pm25, pm10)

    def read(self):
        """Read sensor data - only used in active reporting mode.

        @return: PM2.5 and PM10 concetration in micrograms per cude meter.
        @rtype: tuple(float, float) - first is PM2.5.
        """
        if not self.is_serial_open():
            self.open_serial()

        byte = 0
        while byte != self.HEAD:
            byte = self.ser.read(size=1)
            d = self.ser.read(size=10)
            if d[0:1] == b"\xc0":
                data = self._process_frame(byte + d)
                if data is None and self.use_query_mode is True:
                    print("SDS011 is in query reporting mode, use query()")
                return data

    def check_firmware_version(self):
        """
        @return: Current firwmware version, YEAR-MONTH-DAY
        @rtype: string
        """
        cmd = self.cmd_begin()
        cmd += (self.FIRMWARE_VERSION_CMD
                + b"\x00" * 12)

        cmd = self._finish_cmd(cmd)
        self._execute(cmd)
        raw = self._get_reply()
        year = raw[2]
        month =raw[3]
        day = raw[4]

        return f"{year}-{month}-{day}"
