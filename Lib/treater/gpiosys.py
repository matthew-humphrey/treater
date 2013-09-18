#!/usr/bin/python

# treater/gpiosys.py

"""Non-root accessible wrapper around GPIO sys (user space) driver"""

import time
import os
import logging

LOGGER = logging.getLogger("gpiosys")

class GPIO:

    IN = "in"
    OUT = "out"

    NONE = "none"
    FALLING = "falling"
    RISING = "rising"
    BOTH = "both"

    LOW = 0
    HIGH = 1

    GPIO_PATH = "/sys/class/gpio/"
    EXPORT_PATH = GPIO_PATH + "export"
    UNEXPORT_PATH = GPIO_PATH + "unexport"
    PIN_PATH = GPIO_PATH + "gpio%d/"
    DIRECTION_PATH = PIN_PATH + "direction"
    EDGE_PATH = PIN_PATH + "edge"
    VALUE_PATH = PIN_PATH + "value"

    class Pin:
        def __init__(self, pinNumber, pinType):
            self.pinNumber = pinNumber
            self.pinType = pinType

    pins = {}

    def __init__(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, type, value, traceback):
        self.close()
        return False

    def close(self):
        for pinNumber in self.pins.keys():
            self.releasePin(pinNumber)
        self.pins.clear()

    def releasePin(self, pinNumber):
        pin = self.pins[pinNumber]
        self._unexportPin(pinNumber)
        del self.pins[pinNumber]

    def setupPin(self, pinNumber, pinType, initialValue = None):
        if pinNumber in self.pins:
            pin = self.pins[pinNumber]
        else:
            pin = GPIO.Pin(pinNumber, pinType)
            self.pins[pinNumber] = pin
            self._exportPin(pinNumber)
        directionWasSet = False
        retryCount = 10
        # Kludge to work around delay between creation of gpioN file and udev rule to update permissions
        while retryCount > 0 and not directionWasSet:
            try:
                with open(self.DIRECTION_PATH % pinNumber, "w") as directionFile:
                    directionFile.write(self._pinTypeAndValueToDirection(pinType, initialValue))
                    directionWasSet = True
            except IOError as ioe:
                if ioe.errno != 13:
                    raise ioe
                retryCount = retryCount - 1
                time.sleep(0.1)
        if not directionWasSet:
            raise Exception("Unable to set pin direction. Error opening or writing to: %s" % (self.DIRECTION_PATH % pinNumber))

    def writePin(self, pinNumber, value):
        if pinNumber not in self.pins:
            raise Exception("pin %s not found - did you forget to call setupPin?" % pinNumber)
        pin = self.pins[pinNumber]
        if pin.pinType != self.OUT:
            raise Exception("pin %s is not setup for output and can not be written to" % pinNumber)
        with open(self.VALUE_PATH % pinNumber, "w") as valueFile:
            valueFile.write(str(value))

    def readPin(self, pinNumber):
        if pinNumber not in self.pins:
            raise Exception("pin %s not found - did you forget to call setupPin?" % pinNumber)
        pin = self.pins[pinNumber]
        with open(self.VALUE_PATH % pinNumber, "r") as valueFile:
            return int(valueFile.read())

    def _pinTypeAndValueToDirection(self, pinType, initialValue):
        if pinType == self.IN or initialValue is None:
            return pinType
        else:
            if initialValue == 0:
                return "low"
            else:
                return "high"

    def _exportPin(self, pinNumber):
        pinPath = self.PIN_PATH % pinNumber
        if os.path.exists(pinPath):
            LOGGER.warning("GPIO pin %d is already exported. Will skip export and reconfigure it." % pinNumber)
        else:
            with open(self.EXPORT_PATH, "w") as exportFile:
                exportFile.write(str(pinNumber))

    def _unexportPin(self, pinNumber):
        pinPath = self.PIN_PATH % pinNumber
        if os.path.exists(pinPath):
            with open(self.UNEXPORT_PATH, "w") as unexportFile:
                unexportFile.write(str(pinNumber))


if __name__ == '__main__':
    with GPIO() as gpio:
        print("Setting up pin 22 as input")
        gpio.setupPin(22, GPIO.IN)
        print("Value of pin 22 is: %s" % gpio.readPin(22))
        print("Setting up pin 25 as output with default initial value (low)")
        gpio.setupPin(25, GPIO.OUT)
        print("Value of pin 25 is: %s" % gpio.readPin(25))
        print("Value of pin 22 is: %s" % gpio.readPin(22))
        print("Setting pin 25 to high")
        gpio.writePin(25, 1)
        print("Value of pin 25 is: %s" % gpio.readPin(25))
        print("Value of pin 22 is: %s" % gpio.readPin(22))
        gpio.writePin(25, 0)
        print("Value of pin 25 is: %s" % gpio.readPin(25))
        print("Value of pin 22 is: %s" % gpio.readPin(22))
