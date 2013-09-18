

# treater/seriallcd.py

import time
import serial
import logging

LOGGER = logging.getLogger("seriallcd")

class SerialLCD:

    NoteCodes = { 
        'A' : b'\xDC', 'A#' : b'\xDD', 'B' : b'\xDE', 'C' : b'\xDF', 
        'C#' : b'\E0', 'D' : b'\xE1', 'D#' : b'\xE2', 'E' : b'\xE3', 
        'F' : b'\xE4', 'F#' : b'\xE5', 'G' : b'\xE6', 'G#' : b'\xE7', 
        ' ' : b'\xE8' } 

    NoteLengthCodes = {
        '1/64' : b'\xD0', '1/32' : b'\xD1', '1/16' : b'\xD2', '1/8' : b'\xD3',
        '1/4' : b'\xD4', '1/2' : b'\xD5', '1' : b'\xD6' }

    NoteScaleCodes = {
        3 : b'\xD7', 4 : b'\xD8', 5 : b'\xD9', 6 : b'\xDA', 7 : b'\xDB' } 

    def __init__(self, baud, device='/dev/ttyAMA0'):
        self.ser = serial.Serial(device, 9600, timeout=2)

    def __enter__(self):
        pass    
    
    def __exit__(self, type, value, traceback):
        self.close()

    def close(self):
        if self.ser is not None:
            self.ser.close()
            self.ser = None

    def flush(self):
        self.ser.flush()

    def clear(self):
        self.write(b'\x0C')
        self.flush()
        time.sleep(0.01)

    def setDisplayMode(self, display = True, cursor = True, blink = False):
        if display:
            if cursor:
                if blink:
                    code = b'\x19'
                else:
                    code = b'\x18'
            else:
                if blink:
                    code = b'\x17'
                else:
                    code = b'\x16'
        else:
            code = b'\x15'
        self.write(code)
        self.flush()
		
    def enableBacklight(self, enabled):
        if (enabled):
            self.write(b'\x11')
        else:
            self.write(b'\x12')
        self.flush()
        
    def home(self):
        self.write(b'\x80')

    def nextLine(self):
        self.write(b'\x0D')

    def write(self, msg):
        self.ser.write(msg)

    def writeLine(self, msg):
        paddedMsg = (msg + b' '*16)[:16]
        self.write(paddedMsg)
        self.nextLine()

    def writeBothLines(self, line1, line2 = ''):
        paddedLine1 = (line1 + b' '*16)[:16]
        paddedLine2 = (line2 + b' '*16)[:16]
        self.home()
        self.write(paddedLine1 + paddedLine2)

    def playNote(self, scale, note, length):
        scaleCode = self.NoteScaleCodes[int(scale)]
        note = self.NoteCodes[note]
        lengthCode = self.NoteLengthCodes[length]
        self.write(scaleCode + lengthCode + note)

if __name__ == '__main__':
    lcd = SerialLCD(9600)
    lcd.clear()
    lcd.writeLine("1234567890123456")
    lcd.home()
    lcd.writeLine("AAAA")
