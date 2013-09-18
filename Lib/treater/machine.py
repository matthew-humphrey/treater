#!/usr/bin/python

# treater/machine.py

"""State machine that mangaes interface to the Treat dispenser hardware"""

from gpiosys import GPIO
from datetime import datetime, timedelta
from twisted.internet import reactor
from history import TreatHistory
from seriallcd import SerialLCD
from os import path, getcwd
from logging import getLogger

LOGGER = getLogger("machine")

class TreatMachineConfig:
    SECTION_NAME = "machine"

    def __init__(self, config = None):
        self.maxTreatsPerCycle = 0
        self.historyFile = path.join(getcwd(), "treathist")
        self.buttonHoldForTreatSeconds = 2
        self.returnToIdleSeconds = 10
        self.treatEnabledSeconds = 10
        self.treatRecoverySeconds = 50
        self.postCycleSeconds = 1
        self.buttonPollSeconds = 0.1
        self.treatPollSeconds = 0.02
        self.gpioTreatDetector = 17
        self.gpioButton = 22
        self.gpioTreatPower = 25
        self.lcdBaud = 9600
        if config:
            self.load(config)

    def load(self, config):
        sec = TreatMachineConfig.SECTION_NAME
        self.maxTreatsPerCycle = config.getint(sec, "maxTreatsPerCycle")
        self.historyFile = config.get(sec, "historyFile")
        self.buttonHoldForTreatSeconds = config.getint(sec, "buttonHoldForTreatSeconds")
        self.treatEnabledSeconds = config.getint(sec, "treatEnabledSeconds")
        self.treatRecoverySeconds = config.getint(sec, "treatRecoverySeconds")
        self.postCycleSeconds = config.getfloat(sec, "postCycleSeconds")
        self.buttonPollSeconds = config.getfloat(sec, "buttonPollSeconds")
        self.treatPollSeconds = config.getfloat(sec, "treatPollSeconds")
        self.lcdBaud = config.getint(sec, "lcdBaud")
        self.gpioTreatDetector = config.getint(sec, "gpioTreatDetector")
        self.gpioButton = config.getint(sec, "gpioButton")
        self.gpioTreatPower = config.getint(sec, "gpioTreatPower")

class TreatMachine:

    gpio = None

    def __init__(self, reactor, config):
        self.reactor = reactor
        self.config = config
        self.history = TreatHistory(self.config.historyFile)
        self.lcd = SerialLCD(self.config.lcdBaud)
        self.lcd.clear()
        self.lcd.writeBothLines("")
        self.lcd.clear()
        self.lcd.enableBacklight(False)
        self.lcd.setDisplayMode(display = True, cursor = False, blink = False)
        self.gpio = GPIO()
        self.gpio.setupPin(self.config.gpioTreatDetector, GPIO.IN)
        self.gpio.setupPin(self.config.gpioButton, GPIO.IN)
        self.gpio.setupPin(self.config.gpioTreatPower, GPIO.OUT, 0)
        self.currentState = None
        self.lastState = None
        self.lastButtonState = False
        self.lastTreatDetectorState = False

    def __del__(self):
        self.close()

    def __enter__(self):
        return self

    def __exit__(self, type, value, traceback):
        self.close()
        return False

    def close(self):
        self.gpio.close()
        self.lcd.close()

    def __str__(self):
        return "TreatMachine"

    def stop(self):
        if not self.currentState:
            return
        LOGGER.info("TreatMachine stopping")
        self.changeState(None)
        self.setTreatDispenserPowerState(False)
        self.lcd.writeBothLines("Treater disabled")
        self.lcd.enableBacklight(False)

    def start(self):
        if self.currentState:
            return
        LOGGER.info("TreatMachine starting")
        self.lastButtonState = False
        self.changeState(IdleState())
        self.run()

    def run(self):
        if not self.currentState:
            return

        callbackInterval = self.config.buttonPollSeconds

        try:
            # Fire treat detector event
            newTreatDetectorState = self.isTreatDetectorActive()
            if newTreatDetectorState != self.lastTreatDetectorState:
                if newTreatDetectorState:
                    self.currentState.onTreatDetected(self)
                self.lastTreatDetectorState = newTreatDetectorState

            # Fire button events
            newButtonState = self.isButtonPressed() 
            if newButtonState != self.lastButtonState:
                if newButtonState:
                    LOGGER.debug("Button pressed")
                    self.currentState.onButtonPressed(self)
                else:    
                    LOGGER.debug("Button released")
                    self.currentState.onButtonReleased(self)
                self.lastButtonState = newButtonState

            # Fire timer event
            if (self.currentState):
                self.currentState.onTimerTick(self)

            if (self.currentState ):
                callbackInterval = self.currentState.pollIntervalSeconds(self)

        except Exception as e:
            LOGGER.exception(e)
        finally:
            # Queue continual callback to service state machine
            self.reactor.callLater(callbackInterval, self.run)

    def changeState(self, newState):
        self.lastState = self.currentState
        self.currentState = newState
        LOGGER.debug("Changing states, %s -> %s" % (self.lastState, self.currentState) )
        if self.currentState is not None:
            self.currentState.enterState(self)

    def getCurrentStateName(self):
        if self.currentState is None:
            return "NotRunning"
        return str(self.currentState)

    def dispenseTreat(self):
        if self.currentState is not None:
            self.currentState.onTreatDispenseRequest(self)
        return isinstance(self.currentState, DispensingState)

    def isTreatDetectorActive(self):
        return self.gpio.readPin(self.config.gpioTreatDetector) != 0

    def isButtonPressed(self):
        return self.gpio.readPin(self.config.gpioButton) == 0

    def setTreatDispenserPowerState(self, enabled):
        if enabled:
            self.gpio.writePin(self.config.gpioTreatPower, 1)
        else:
            self.gpio.writePin(self.config.gpioTreatPower, 0)

    def updateLcdTreatStats(self, forceUpdate=False):
        now = datetime.now()
        try:
            if not forceUpdate and self.lastUpdateTime is not None and (now - self.lastUpdateTime) < timedelta(minutes=1):
                return
        except AttributeError:
            pass
        self.lastUpdateTime = now
        (cycleCount, treatCount, lastTreatTime)  = self.history.getTreatStats()
        line1 = "Treats : %d/%d" % (treatCount, cycleCount)
        if lastTreatTime is None:
            line2 = "Last   : > 24h"
        else:
            td = now - lastTreatTime
            line2 = "Last   : %dh %dm" % (td.days * 24 + td.seconds / 3600, (td.seconds % 3600) / 60)
        self.lcd.writeBothLines(line1, line2)

class State:
    """Abstract class that is subclassed to handle the various states for the state machine"""
    
    def enterState(self, machine):
        pass
        
    def onTimerTick(self, machine):
        pass
        
    def onButtonPressed(self, machine):
        pass

    def onButtonReleased(self, machine):
        pass

    def onTreatDispenseRequest(self, machine):
        pass

    def onTreatDetected(self, machine):
        pass

    def pollIntervalSeconds(self, machine):
        return machine.config.buttonPollSeconds

class IdleState(State):
    def __str__(self):
        return "Idle"
        
    def enterState(self, machine):
        machine.lcd.enableBacklight(False)
        machine.updateLcdTreatStats(forceUpdate=True)
  
    def onButtonPressed(self, machine):
        machine.changeState(LightLcdState())
              
    def onTimerTick(self, machine):
        machine.updateLcdTreatStats()

    def onTreatDispenseRequest(self, machine):
        machine.changeState(DispensingState())
        
class LightLcdState(State):
    def __str__(self):
        return "LightLcd"
        
    def enterState(self, machine):
        machine.updateLcdTreatStats(forceUpdate=True)
        machine.lcd.enableBacklight(True)
        self.buttonInStateTime = datetime.now()
        self.lastButtonState = machine.isButtonPressed()
    
    def onButtonPressed(self, machine):
        self.buttonInStateTime = datetime.now()
        self.lastButtonState = True

    def onButtonReleased(self, machine):        
        self.buttonInStateTime = datetime.now()
        self.lastButtonState = False
        
    def onTreatDispenseRequest(self, machine):
        machine.changeState(DispensingState())
    
    def onTimerTick(self, machine):
        machine.updateLcdTreatStats()
        now = datetime.now()
        if self.lastButtonState:
            if now - self.buttonInStateTime > timedelta(seconds=machine.config.buttonHoldForTreatSeconds):
                machine.changeState(DispensingState())
        else:
            if now - self.buttonInStateTime > timedelta(seconds=machine.config.returnToIdleSeconds):
                machine.changeState(IdleState())
    
class DispensingState(State):
    def __str__(self):
        return "Dispensing"
        
    def enterState(self, machine):
        LOGGER.info("Treat dispensing")
        self.dispenseTime = datetime.now()
        self.cycleTreatCount = 0
        self.timeToStopDispensing = datetime.now() + timedelta(seconds = machine.config.treatEnabledSeconds)
        self.timeToExit = self.timeToStopDispensing + timedelta(seconds = machine.config.postCycleSeconds)
        machine.setTreatDispenserPowerState(True)
        machine.lcd.writeBothLines("Dispensing...")
        machine.lcd.enableBacklight(True)
       
    def onTimerTick(self, machine):
        if (datetime.now()  > self.timeToStopDispensing):
            machine.setTreatDispenserPowerState(False)
        if (datetime.now()  > self.timeToExit):
            LOGGER.info("Estimated treats dispensed: %d" % self.cycleTreatCount)
            machine.history.treatsDispensed(self.cycleTreatCount)
            machine.changeState(RecoveringState())

    def onTreatDetected(self, machine):
        self.cycleTreatCount = self.cycleTreatCount + 1
        if machine.config.maxTreatsPerCycle and self.cycleTreatCount >= machine.config.maxTreatsPerCycle:
            machine.setTreatDispenserPowerState(False)
            self.timeToExit = datetime.now() + timedelta(seconds = machine.config.postCycleSeconds)

    def pollIntervalSeconds(self, machine):
        # Poll at higher rate when monitoring the treat detector
        return machine.config.treatPollSeconds

class RecoveringState(State):
    def __str__(self):
        return "Recovering"

    def enterState(self, machine):
        machine.setTreatDispenserPowerState(False)
        machine.updateLcdTreatStats(forceUpdate=True)
        machine.lcd.enableBacklight(True)
        self.enterStateTime = datetime.now()
       
    def onTimerTick(self, machine):
        machine.updateLcdTreatStats()
        now = datetime.now()
        if (now - self.enterStateTime > timedelta(seconds=machine.config.treatRecoverySeconds)):
            machine.changeState(IdleState())
        
if __name__ == "__main__":
    from logging import Formatter, StreamHandler, INFO, DEBUG, getLogger
    from os import getcwd
    from twisted.python.log import PythonLoggingObserver

    logFormatter = Formatter(fmt='%(asctime)s - %(name)s - %(levelname)s - %(message)s', datefmt="%Y-%m-%d %H:%M:%S")
    rootLogger = getLogger()
    consoleHandler = StreamHandler()
    consoleHandler.setFormatter(logFormatter)
    rootLogger.addHandler(consoleHandler)
    rootLogger.setLevel(DEBUG)
    observer = PythonLoggingObserver()
    observer.start()

    with TreatMachine(reactor, TreatMachineConfig()) as machine:
        machine.start()
        reactor.run()


