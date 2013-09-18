#!/usr/bin/python

# treater/camera.py

"""Background task that captures images via the Raspberry Pi camera if motion is detected"""

from twisted.internet import protocol, utils, reactor, defer
from twisted.python import failure
from twisted.python.constants import NamedConstant, Names
from cStringIO import StringIO
from PIL import Image
from logging import getLogger
from os import path, remove, rename, symlink, getcwd
from glob import glob
from datetime import datetime, timedelta

LOGGER = getLogger("camera")

class TreatCamConfig:
    SECTION_NAME = "camera"
    RASPISTILL = '/usr/bin/raspistill'    
    MAX_RES_HORIZONTAL = 2592
    MAX_RES_VERTICAL = 1944
    ASPECT_RATIO = MAX_RES_HORIZONTAL / MAX_RES_VERTICAL

    def __init__(self, config = None):
        self.motionIntervalSeconds = 0.5
        self.motionCaptureProgram = TreatCamConfig.RASPISTILL
        self.motionCaptureProgramArgs = "-w 100 -h 75 -t 0 -n -e bmp -o -"
        self.motionAutoDisableSeconds = 600
        self.motionThreshold = 10
        self.motionSensitivity = 30
        self.captureProgram = TreatCamConfig.RASPISTILL
        self.captureProgramArgs = "-w 648 -h 486 -t 0 -n -e jpg -q 15 -o" 
        self.capturesToRetain = 100
        self.captureDir = getcwd()
        if config:
            self.load(config)

    def load(self, config):
        sec = TreatCamConfig.SECTION_NAME
        self.motionIntervalSeconds = config.getfloat(sec, "motionIntervalSeconds")
        self.motionCaptureProgram = config.get(sec, "motionCaptureProgram")
        self.motionCaptureProgramArgs = config.get(sec, "motionCaptureProgramArgs")
        self.motionAutoDisableSeconds = config.getint(sec, "motionAutoDisableSeconds")
        self.motionThreshold = config.getint(sec, "motionThreshold")
        self.motionSensitivity = config.getint(sec, "motionSensitivity")
        self.captureProgram = config.get(sec, "captureProgram")
        self.captureProgramArgs = config.get(sec, "captureProgramArgs")
        self.capturesToRetain = config.getint(sec, "capturesToRetain")
        self.captureDir = config.get(sec, "captureDir")
                        
class TreatCam:

    IDLE = 0
    PENDING_MOTION_CAPTURE = 21
    PENDING_FULL_CAPTURE = 2

    CAPTURE_PREFIX = "capture-"
    CAPTURE_FORMAT = CAPTURE_PREFIX + "%Y%m%d-%H%M%S.jpg"

    def __init__(self, reactor, config):
        LOGGER.info("Initializing TreatCam") 
        self.reactor = reactor
        self.config = config

        self.motionCaptureRunning = False
        self.motionCaptureStartTime = None
        self.state = TreatCam.IDLE
    
        self.lastImage = None
        self.lastBuffer = None

        self.lastCaptureTime = None
        self.lastCaptureName = None
        self.findPreExistingLastCapture()
        self.forceCapture = False
        
    def __str__(self):
        return "TreatCam"

    def isMotionCaptureRunning(self):
        return self.motionCaptureRunning

    def startMotionCapture(self):
        self.motionCaptureStartTime = datetime.now()
        if self.motionCaptureRunning:
            return
        LOGGER.info("Enabling camera motion capture")
        self.motionCaptureRunning = True
        self.initiateMotionCaptureCycle()

    def stopMotionCapture(self):
        if not self.motionCaptureRunning:
            return
        LOGGER.info("Disabling camera capture")
        self.motionCaptureRunning = False
        self.motionCaptureStartTime = None

    def forceImageCapture(self):
        LOGGER.debug("Received request to force image capture")
        if self.state == TreatCam.PENDING_FULL_CAPTURE:
            LOGGER.debug("Full image capture in progress; force capture not necessary")
            return
        self.forceCapture = True
        if self.state == TreatCam.IDLE:
            LOGGER.debug("Force capture initiating full capture cycle")
            self.initiateFullCaptureCycle()
        else:
            LOGGER.DEBUG("Setting force capture flag; full capture will occcur after in-progress motion capture")

    def getLastCaptureTime(self):
        return self.lastCaptureTime

    def getLastCaptureName(self):
        return self.lastCaptureName

    def findPreExistingLastCapture(self):
        capturePattern = path.join(self.config.captureDir, TreatCam.CAPTURE_PREFIX + "*")
        captures = sorted(glob(capturePattern))
        if captures:
            lastCapturePath = captures[-1]
            (pth, name) = path.split(lastCapturePath)
            try:
                self.lastCaptureTime = datetime.strptime(name, TreatCam.CAPTURE_FORMAT)
                self.lastCaptureName = name
                LOGGER.info("Recovering %s at startup as last capture file" % self.lastCaptureName)
            except ValueError:
                pass

    def initiateMotionCaptureCycle(self):
        if self.state != TreatCam.IDLE:
            return
        LOGGER.debug("Initiating motion capture cycle")
        self.state = TreatCam.PENDING_MOTION_CAPTURE
        deferred = utils.getProcessOutputAndValue(executable=self.config.motionCaptureProgram, args=self.config.motionCaptureProgramArgs.split(' '), reactor=self.reactor)
        deferred.addCallbacks(self.motionCapture, self.motionCaptureError)

    def motionCapture(self, result):
        LOGGER.debug("In motionCapture callback")

        self.state = TreatCam.IDLE
        if self.forceCapture:
            self.initiateFullCaptureCycle()            

        (out, err, code) = result

        changedPixels = 0
        if code == 0:
            s = StringIO(out)
            image = Image.open(s)
            buffer = image.load()
            s.close()
    
            # Count changed pixels
            if self.lastImage is not None:
                (width, height) = image.size
                for x in xrange(0, width):
                    for y in xrange(0, height):
                        # Use green channel only as it is the highest quality channel due to Bayer filter
                        GREEN = 1
                        pixdiff = abs(self.lastBuffer[x,y][GREEN] - buffer[x,y][GREEN])
                        if pixdiff >= self.config.motionThreshold:
                            changedPixels += 1
                LOGGER.debug("changedPixels = %d" % changedPixels)

            # Save image for next comparison
            self.lastImage = image
            self.lastBuffer = buffer

        else:
            LOGGER.error("Image capture process returned error %s: %s" % (code, err))

        # If motion capture is still enabled, we either capture a full image or schedule the next motion capture
        if self.motionCaptureRunning:
            # Queue an image capture operation if pixels changed
            if changedPixels > self.config.motionSensitivity:
                LOGGER.info("Motion detected. Will capture image")
                self.initiateFullCaptureCycle()
            # Otherwise queue next motion capture
            else:
                if self.motionCaptureRunning:
                    if (datetime.now() - self.motionCaptureStartTime) > timedelta(seconds=self.config.motionAutoDisableSeconds):
                        self.motionCaptureRunning = False
                    else:
                        self.reactor.callLater(self.config.motionIntervalSeconds, self.initiateMotionCaptureCycle)

    def motionCaptureError(self, err):
        LOGGER.error("Error response to motion capture process: %s" % err)
        self.state = TreatCam.IDLE
        return err

    def initiateFullCaptureCycle(self):
        LOGGER.debug("Initiating full capture cycle")
        self.state = TreatCam.PENDING_FULL_CAPTURE
        self.forceCapture = False
        time = datetime.now()
        captureName = time.strftime(TreatCam.CAPTURE_FORMAT)
        capturePath = path.join(self.config.captureDir, captureName)
        cmdLine = self.config.captureProgramArgs + " " + capturePath
        LOGGER.debug("Preparing to spawn capture process: %s %s" % (self.config.captureProgram, cmdLine))
        args = cmdLine.split(' ')
        deferred = utils.getProcessOutputAndValue(executable=self.config.captureProgram, args=args, reactor=self.reactor)
        deferred.addCallbacks(callback = self.fullCapture, errback = self.fullCaptureError, 
                              callbackKeywords = {"captureName" : captureName, "captureTime" : time})

    def fullCapture(self, result, *args, **kwargs):
        LOGGER.debug("In full capture callback")
        
        self.state = TreatCam.IDLE

        (out, err, code) = result

        if code == 0:
            self.lastCaptureTime = kwargs["captureTime"]
            self.lastCaptureName =  kwargs["captureName"]
            LOGGER.info("Captured %s" % self.lastCaptureName)
            self.trimExcessCaptureFiles()
        else:
            LOGGER.error("Image capture process returned error %s: %s" % (code, err))

        # If motion capture enabled, start the next motion capture cycle
        if self.motionCaptureRunning:
            self.reactor.callLater(self.config.motionIntervalSeconds, self.initiateMotionCaptureCycle)

    def fullCaptureError(self, err):
        LOGGER.error("Error response to full image capture process: %s" % err)
        self.state = TreatCam.IDLE
        return err

    def trimExcessCaptureFiles(self):
        captures = sorted(glob(path.join(self.config.captureDir, TreatCam.CAPTURE_PREFIX + "*")))
        excessCaptures = len(captures) - self.config.capturesToRetain
        if (excessCaptures > 0):
            for i in range(excessCaptures):
                LOGGER.info("Trimming: %s" % captures[i])
                remove(captures[i])

if __name__=="__main__":
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

    cam = TreatCam(reactor, TreatCamConfig())
    cam.startMotionCapture()
    reactor.run()

