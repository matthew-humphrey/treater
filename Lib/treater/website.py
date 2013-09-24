# treater/website.py

"""Twisted set-up for Treater web site and REST API"""

import json
import datetime
import time
from os import getcwd, path
from logging import getLogger
from twisted.web.server import Site, NOT_DONE_YET
from twisted.web.static import File
from twisted.web.resource import Resource, IResource
from twisted.web.proxy import ReverseProxyResource
from twisted.internet import defer
from zope.interface import implements
from twisted.cred import portal, checkers, credentials, error as credError
from twisted.web.guard import HTTPAuthSessionWrapper
from twisted.web.guard import DigestCredentialFactory
from twisted.web.guard import BasicCredentialFactory

LOGGER = getLogger("webapi")

def getRequestHostName(request):
    hostHeaders = request.requestHeaders.getRawHeaders(b"Host")
    if not hostHeaders:
        return None
    return str(hostHeaders[0])
    

class TreatWebConfig:
    SECTION_NAME = "web"

    def __init__(self, config = None):
        self.capturePath = path.join(getcwd(), "/captures")
        self.port = 8000
        if config:
            self.load(config)

    def load(self, config):
        sec = TreatWebConfig.SECTION_NAME
        self.capturePath = config.get(sec, "capturePath")
        self.port = config.getint(sec, "port")

class TreatWeb:
    def __init__(self, reactor, machine, camera, config):
        self.config = config
        self.reactor = reactor
        self.machine = machine
        self.camera = camera

        root = Resource()
        api = Resource()
        api.putChild("getStatus", ApiGetStatus(config, machine, camera))
        api.putChild("capturePhoto", ApiCapturePhoto(config, machine, camera))
        api.putChild("dispenseTreat", ApiDispenseTreat(config, machine, camera))
        api.putChild("getVideoStreamUrl", ApiGetVideoStreamUrl(config, machine, camera))
        root.putChild("api", api)

        site = Site(root)
        reactor.listenTCP(self.config.port, site)
 
def datetimeToJsonStr(dt):
    if not dt:
            return ""
    return time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(time.mktime(dt.timetuple())))

class ApiResource(Resource):
    jsonContentType = b"application/json"

    def __init__(self, config, machine, camera):
        self.config = config
        self.machine = machine
        self.camera = camera
        self.isLeaf = True

    def makeCapturePath(self, capture):
        if not capture:
            return ""
        return path.join(self.config.capturePath,capture)

    def getLastCapturePath(self):
        capture = self.camera.getLastCaptureName()
        return self.makeCapturePath(capture)

    def getStatus(self):
        (cycleCount, treatCount, lastTreatTime) = self.machine.history.getTreatStats()
        if lastTreatTime:
            td = datetime.datetime.now() - lastTreatTime
            (hours, minutes) = (int(td.total_seconds()/3600), int(td.total_seconds()%60))
        else:
            (hours, minutes) = (-1, -1)
        result = {
            "lastTreat" : datetimeToJsonStr(lastTreatTime),
            "numTreatsInLast24Hours" : treatCount, 
            "numCyclesInLast24Hours" : cycleCount,
            "timeSinceLastTreat" : { "hours" : hours, "minutes" : minutes },
            "machineState" : self.machine.getCurrentStateName(), 
            "captureTime" : datetimeToJsonStr(self.camera.getLastCaptureTime()),
            "capturePath" : self.getLastCapturePath()}
        return result


class ApiGetStatus(ApiResource):
    def __init__(self, config, machine, camera):
        ApiResource.__init__(self, config, machine, camera)

    def render_GET(self, request):
        request.defaultContentType = ApiResource.jsonContentType
        result = json.dumps(self.getStatus())
        return result

class ApiGetVideoStreamUrl(ApiResource):
    def __init__(self, config, machine, camera):
        ApiResource.__init__(self, config, machine, camera)

    def render_GET(self, request):
        request.defaultContentType = ApiResource.jsonContentType
        result = json.dumps({"videoStreamUrl" : "/video"})
        return result

class ApiCapturePhoto(ApiResource):
    def __init__(self, config, machine, camera):
        ApiResource.__init__(self, config, machine, camera)

    def render_POST(self, request):
        LOGGER.info("Camera capture request from web")
        d = self.camera.capturePhoto()
        if not d:
            LOGGER.error("Error requesting photo capture from web API")
            request.setResponseCode(500)
            return "Error capturing photo"
        d.addCallbacks(lambda x: self.captureCallback(x, request), lambda x: self.captureErrback(x, request))
        return NOT_DONE_YET

    def captureCallback(self, capture, request):
        LOGGER.info("Received capture callback. Capture: %s" % capture)
        request.defaultContentType = ApiResource.jsonContentType
        result = json.dumps({"capturePath" : self.makeCapturePath(capture)})
        request.write(result)
        request.finish()

    def captureErrback(self, failure, request):
        LOGGER.error("Error (errback) requesting photo capture from web API")
        request.setResponseCode(500)
        request.write("Error capturing photo")
        request.finish()

class ApiDispenseTreat(ApiResource):
    def __init__(self, config, machine, camera):
        ApiResource.__init__(self, config, machine, camera)

    def render_POST(self, request):
        LOGGER.info("Treat dispense request from web")
        success = self.machine.dispenseTreat()
        if not success:
            request.setResponseCode(429) # Too many requests
            return "Treat machine is busy. Please allow 60 seconds between treat dispense requests"
        request.defaultContentType = ApiResource.jsonContentType
        return json.dumps(self.getStatus())

