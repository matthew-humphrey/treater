#!/usr/bin/python

# treater/camera.py


"""Background task that controls the motion service. Motion is a daemon that streams video and captures images from a webcam"""

from twisted.internet import protocol, utils, reactor, defer
from twisted.python.failure import Failure
from twisted.internet.inotify import INotify, IN_CREATE, humanReadableMask
from twisted.web.client import Agent
from twisted.internet.defer import Deferred
from twisted.python.filepath import FilePath
from twisted.python import failure
from twisted.python.constants import NamedConstant, Names
from logging import getLogger
from os import path, remove, rename, symlink, getcwd
from glob import glob
from datetime import datetime, timedelta

LOGGER = getLogger("camera")

class TreatCamConfig:
    SECTION_NAME = "camera"

    def __init__(self, config = None):
        self.capturesToRetain = 100
        self.captureDir = 'captures'
        self.motionControlPort = 8001
        self.motionStreamPort = 8002
        if config:
            self.load(config)

    def load(self, config):
        sec = TreatCamConfig.SECTION_NAME
        self.capturesToRetain = config.getint(sec, "capturesToRetain")
        self.captureDir = config.get(sec, "captureDir")
        self.motionControlPort = config.getint(sec, "motionControlPort")
        self.motionStreamPort = config.getint(sec, "motionStreamPort")
                        
class TreatCam:
    CAPTURE_GLOB = "capture-*.jpg"
    CAPTURE_DATETIME_FORMAT = "%Y%m%d-%H%M%S"
    LAST_CAPTURE_LINK_NAME = "lastsnap.jpg"

    def __init__(self, reactor, config):
        LOGGER.info("Initializing TreatCam") 
        self.config = config
        self.reactor = reactor
        self.agent = Agent(reactor)
        self.defers = []
        self.snapshotActionUrl = "http://localhost:%d/0/action/snapshot" % self.config.motionControlPort

        self.capturePath = FilePath(config.captureDir)
        self.lastCaptureLink = self.capturePath.child(TreatCam.LAST_CAPTURE_LINK_NAME)
        self.lastCaptureTime = None
        self.lastCaptureName = None
        self.findPreExistingLastCapture()
        
        self.notifier = INotify()
        self.notifier.startReading()
        self.notifier.watch(self.capturePath, mask=IN_CREATE, callbacks=[self.notifyCallback])

    def __str__(self):
        return "TreatCam"

    def capturePhoto(self):
        LOGGER.debug("Received request to capture a photo")
        if not self.defers:
            LOGGER.debug("Sending HTTP GET request to motion daemon")
            httpRequestDefer = self.agent.request('GET', self.snapshotActionUrl)
            httpRequestDefer.addCallbacks(self.httpResponseCallback, self.httpResponseErrback)
        d = Deferred()
        self.addTimeout(d, 2)
        self.defers.append(d)
        return d

    def httpResponseCallback(self, ignored):
        LOGGER.debug("Received response from HTTP GET snapshot request to motion")

    def httpResponseErrback(self, failure):
        LOGGER.error("Error in HTTP GET snapshot request to motion")
        self.errbackDefers(failure)

    def errbackDefers(self, failure):
        defers = self.defers
        self.defers = []
        for d in defers:
            if not d.called:
                d.errback(Failure())

    def notifyCallback(self, ignored, filepath, mask):
        LOGGER.debug("Notify event %s on %s" % (humanReadableMask(mask), filepath.basename()))
        if mask & IN_CREATE and filepath == self.lastCaptureLink:
            capture = filepath.realpath().basename()
            LOGGER.info("New capture detected: %s" % capture)
            try:
                self.lastCaptureTime = self.extractDateTimeFromCaptureName(capture)
                self.lastCaptureName = capture
            except ValueError:
                self.errbackDefers(Failure())

            if self.defers:
                defers = self.defers
                self.defers = []
                for d in defers:
                    if not d.called:
                        d.callback(capture)

    def getLastCaptureTime(self):
        return self.lastCaptureTime

    def getLastCaptureName(self):
        return self.lastCaptureName

    def addTimeout(self, d, duration):
        timeout = reactor.callLater(duration, d.cancel)
        def cancelTimeout(result):
            if timeout.active():
                timeout.cancel()
            return result
        d.addBoth(cancelTimeout)

    def extractDateTimeFromCaptureName(self, name):
        datetimeStr = name.split('-',1)[-1].rsplit('-',1)[0]
        return datetime.strptime(datetimeStr, TreatCam.CAPTURE_DATETIME_FORMAT)

    def findPreExistingLastCapture(self):
        captures = sorted(self.capturePath.globChildren(TreatCam.CAPTURE_GLOB))
        if captures:
            lastCapturePath = captures[-1]
            name = lastCapturePath.basename()
            try:
                self.lastCaptureTime = self.extractDateTimeFromCaptureName(name)
                self.lastCaptureName = name
                LOGGER.info("Recovering %s at startup as last capture file" % self.lastCaptureName)
            except ValueError:
                LOGGER.exception("Unable to determine last capture file")
                pass

    def trimExcessCaptureFiles(self):
        captures = sorted(self.capturePath.globChildren(TreatCam.CAPTURE_GLOB))
        excessCaptures = len(captures) - self.config.capturesToRetain
        if (excessCaptures > 0):
            for i in range(excessCaptures):
                LOGGER.info("Trimming: %s" % captures[i].basename())
                captures[i].remove()


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
    
    LOGGER.debug( "Video stream URL for host=treater: %s" % cam.getVideoStreamUrl("treater"))
    d = cam.capturePhoto()

    def testCaptureErrback(failure):
        LOGGER.error("Got capture errback: %s" % failure)
        reactor.stop()

    def testCaptureCallback(capture):
        LOGGER.debug("Got capture callback. Capture name is %s" % capture)
        reactor.callLater(5, reactor.stop)

    d.addCallbacks(testCaptureCallback, testCaptureErrback)

    reactor.run()


