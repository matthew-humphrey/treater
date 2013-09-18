#!/usr/bin/python

# treater/history.py

"""Tracks treat history and time since last treat"""

import pickle
import os
import threading
from datetime import datetime, timedelta
import logging

LOGGER = logging.getLogger("history")

class TreatEvent:
    def __init__(self, treatTime, treatCount):
        self.treatTime = treatTime
        self.treatCount = treatCount

class TreatHistory:
    
    def __init__(self, path=None):
        self.treatEvents = []
        self.path = path
        self.lock = threading.Lock()
        if path is not None:
            self.load(path)

    def __str__(self):
        return "TreatHistory"
            
    def load(self, path):
        if os.path.isfile(path):
            try:
                # Lock to prevent two threads loading  at the same time
                with self.lock, open(path, "r") as f:
                    treatEvents = pickle.load(f)
                if treatEvents:
                    if isinstance(treatEvents[0], datetime):
                        # Old format history file - convert it
                        LOGGER.info("Converting from old treat history format to new format")
                        te = []
                        for tt in treatEvents:
                            te.append(TreatEvent(tt,3))
                        self.treatEvents = te
                    else:
                        self.treatEvents = treatEvents
                    self.updateLast24Hours()
            except Exception as x:
                LOGGER.exception("Error loading event history from path: %s. History will be lost." % path)          
                self.treatEvents = []
        else:
            LOGGER.warn("Treat history not present at path: %s" % path)          
            self.treatEvents = []
        
    def save(self, path):
        try:
            # Lock to prevent two threads trying to update the file at the same time
            with self.lock, open(path, "w") as f:
                pickle.dump(self.treatEvents, f)
        except:
            LOGGER.error("Unable to write treat history to: %s" % path)
        
    def autoSave(self):
        if (self.path is not None):
            self.save(self.path)
        
    def treatsDispensed(self, treatCount):
        dt = datetime.now()
        self.treatEvents.append(TreatEvent(dt, treatCount))
        self.updateLast24Hours()
        self.autoSave()

    def getTreatStats(self):
        self.updateLast24Hours()
        if not self.treatEvents:
            return (0, 0, None)
        cycleCount = len(self.treatEvents)
        treatCount = 0
        for te in self.treatEvents:
            treatCount += te.treatCount
        return (cycleCount, treatCount, self.treatEvents[-1].treatTime)
        
    def updateLast24Hours(self):
        n = datetime.now()
        td24hours = timedelta(days=1)
        while len(self.treatEvents) > 0:
            if ( (n - self.treatEvents[0].treatTime) > td24hours):
                self.treatEvents.pop(0)
            else:
                # Assumes treat events are in order
                break
        
    def numTreatsInLast24Hours(self):
        self.updateLast24Hours()
        return len(self.treatEvents)

def formatTimeSinceLastTreat(td):
    if td is None:
        return "Last: > 24h"
    return "Last: %dh %dm" % (td.days * 24 + td.seconds / 3600, (td.seconds % 3600) / 60)
        
if __name__ == "__main__":
       
    th = TreatHistory("history")
    print("Num in 24h: %d" % th.numTreatsInLast24Hours())
    print(formatTimeSinceLastTreat(th.timedeltaSinceLastTreat()))
    dt = datetime.now() - timedelta(hours=4, minutes=30) 
    print("Dispensing treat at %s" % dt)
    th.treatDispensed(dt)
    print("Num in 24h: %d" % th.numTreatsInLast24Hours())
    print(formatTimeSinceLastTreat(th.timedeltaSinceLastTreat()))

