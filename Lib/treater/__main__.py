#!/usr/bin/python

# treater/__main__.py

"""Main (module) entry point for Treater, a Raspberry Pi-based remotely accessible pet feeder"""

from datetime import datetime
from twisted.internet import reactor
from website import TreatWeb, TreatWebConfig
from machine import TreatMachine, TreatMachineConfig
from camera import TreatCam, TreatCamConfig
from argparse import ArgumentParser
from ConfigParser import SafeConfigParser

def initializeLogging(configFile):
    from logging.config import fileConfig
    from twisted.python.log import PythonLoggingObserver
    fileConfig(configFile)
    observer = PythonLoggingObserver()
    observer.start()

if __name__ == "__main__":
    parser = ArgumentParser(description = "Service for Raspberry Pi powered pet treat feeder")
    parser.add_argument("-C")
    args = parser.parse_args()

    config = SafeConfigParser()
    config.read(args.C)

    initializeLogging(args.C)
    from logging import getLogger
    LOGGER = getLogger("main")

    camera = TreatCam(reactor, TreatCamConfig(config))

    machine = TreatMachine(reactor, TreatMachineConfig(config))
    machine.start()

    web = TreatWeb(reactor, machine, camera, TreatWebConfig(config)) 
    
    def shutdown():
        machine.stop()
        machine.close()
        LOGGER.info("Treater exiting")
    reactor.addSystemEventTrigger('before', 'shutdown', shutdown)
    
    reactor.run()


