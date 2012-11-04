"""
This module provides functionality for tracking bridge stability metrics, using
the model introduced in [1] and implemented in [2].

[1] Karsten Loesing, An Analysis of Tor Bridge Stability. Technical Report.
The Tor Project, October 2011.
https://metrics.torproject.org/papers/bridge-stability-2011-10-31.pdf

[2] https://gitweb.torproject.org/metrics-tasks/task-4255/SimulateBridgeStability.java
"""
import logging
import bridgedb.Storage

# tunables 
weighting_factor = long(19)/long(20)
discountIntervalMillis = long(60*60*12*1000)

class BridgeHistory(object):
    """ Record Class that tracks a single Bridge
    The fields stored are:

    fingerprint, ip, port, weightedUptime, weightedTime, weightedRunLength,
    totalRunWeights, lastSeenWithDifferentAddressAndPort,
    lastSeenWithThisAddressAndPort, lastDiscountedHistoryValues.

    fingerprint         The Bridge Fingerprint (unicode)
    ip                  The Bridge IP (unicode)
    port                The Bridge orport (integer)

    weightedUptime      Weighted uptime in seconds (long int)
    weightedTime        Weighted time in seconds (long int)
    weightedRunLength   Weighted run length of previous addresses or ports in
                        seconds. (long int)
    totalRunWeights     Total run weights of previously used addresses or
                        ports. (float)

    lastSeenWithDifferentAddressAndPort
        Timestamp in milliseconds when this
        bridge was last seen with a different address or port. (long int)

    lastSeenWithThisAddressAndPort
        Timestamp in milliseconds when this bridge was last seen
        with this address and port. (long int)

    lastDiscountedHistoryValues:
        Timestamp in milliseconds when this bridge was last discounted. (long int)
    """
    def __init__(self, fingerprint, ip, port,
            weightedUptime, weightedTime, weightedRunLength, totalRunWeights,
            lastSeenWithDifferentAddressAndPort, lastSeenWithThisAddressAndPort,
            lastDiscountedHistoryValues=None):
        self.fingerprint = fingerprint
        self.ip = ip 
        self.port = port
        self.weightedUptime = long(weightedUptime)
        self.weightedTime = long(weightedTime)
        self.weightedRunLength = float(weightedRunLength)
        self.totalRunWeights = float(totalRunWeights)
        self.lastSeenWithDifferentAddressAndPort = \
                long(lastSeenWithDifferentAddressAndPort)
        self.lastSeenWithThisAddressAndPort = long(lastSeenWithThisAddressAndPort)
        if lastDiscountedHistoryValues:
            self.lastDiscountedHistoryValues = long(lastDiscountedHistoryValues)
        else:
            self.lastDiscountedHistoryValues = long(lastSeenWithThisAddressAndPort)

    def discountWeightedFractionalUptimeAndWeightedTime(self, discountUntilMillis):
        """ discount weighted times """
        rounds = self.numDiscountRounds(discountUntilMillis)
        if rounds > 0:
            discount = lambda x: (weighting_factor**rounds)*x
            self.weightedUptime = discount(self.weightedUptime)
            self.weightedTime = discount(self.weightedTime)
            self.weightedRunLength = discount(self.weightedRunLength)
            self.totalRunWeights = discount(self.totalRunWeights)

            self.lastDiscountedHistoryValues += discountIntervalMillis * rounds
        return rounds

    def numDiscountRounds(self, discountUntilMillis):
        """ return the number of rounds of discounting needed to bring this
        history element current """
              
        result = discountUntilMillis - self.lastDiscountedHistoryValues
        result = int(result/discountIntervalMillis)
        return max(result,0)

    @property
    def weightedFractionalUptime(self):
        """Weighted Fractional Uptime"""
        if self.weightedTime <0.0001: return long(0)
        return long(10000) * self.weightedUptime / self.weightedTime

    @property
    def tosa(self):
        """the Time On Same Address (TOSA)"""
        return ( self.lastSeenWithThisAddressAndPort - \
                    self.lastSeenWithDifferentAddressAndPort ) / 1000

    @property
    def familiar(self):
        """
        A bridge is 'familiar' if 1/8 of all active bridges have appeared
        more recently than it, or if it has been around for a Weighted Time of 8 days.
        """
        # if this bridge has been around longer than 8 days
        if self.weightedTime >= long(8 * 24 * 60 * 60):
            return True

        # return True if self.weightedTime is greater than the weightedTime
        # of the > bottom 1/8 all bridges, sorted by weightedTime
        db = bridgedb.Storage.getDB()
        allWeightedTimes = [ bh.weightedTime for bh in db.getAllBridgeHistory()]
        numBridges = len(allWeightedTimes)
        logging.debug("Got %d weightedTimes", numBridges)
        allWeightedTimes.sort(lambda x,y: cmp(x.weightedTime, y.weightedTime))
        if self.weightedTime > allWeightedTimes[numBridges/8].weightedTime:
            return True
        return False

    @property
    def wmtbac(self):
        """Weighted Mean Time Between Address Change"""
        totalRunLength = self.weightedRunLength + \
                ((self.lastSeenWithThisAddressAndPort -
                self.lastSeenWithDifferentAddressAndPort) / long(1000))

        totalWeights = self.totalRunWeights + 1.0
        if totalWeights <  0.0001: return long(0)
        assert(isinstance(long,totalRunLength))
        assert(isinstance(long,totalWeights))
        return totalRunlength / totalWeights

def addOrUpdateBridgeHistory(bridge, timestamp):
    db = bridgedb.Storage.getDB()
    bhe = db.getBridgeHistory(bridge.fingerprint)
    if not bhe:
        # This is the first status, assume 60 minutes.
        secondsSinceLastStatusPublication = long(60*60)
        lastSeenWithDifferentAddressAndPort = timestamp * long(1000)
        lastSeenWithThisAddressAndPort = timestamp * long(1000)
    
        bhe = BridgeHistory(
                bridge.fingerprint, bridge.ip, bridge.orport, 
                0,#weightedUptime
                0,#weightedTime
                0,#weightedRunLength
                0,# totalRunWeights
                lastSeenWithDifferentAddressAndPort, # first timestamnp
                lastSeenWithThisAddressAndPort
                )
    
    # Calculate the seconds since the last parsed status.  If this is
    # the first status or we haven't seen a status for more than 60
    # minutes, assume 60 minutes.
    statusPublicationMillis = long(timestamp * 1000)
    if (statusPublicationMillis - bhe.lastSeenWithThisAddressAndPort) > 60*60*1000:
        secondsSinceLastStatusPublication = long(60*60)
    # otherwise, roll with it
    else:
        secondsSinceLastStatusPublication = \
                (statusPublicationMillis - bhe.lastSeenWithThisAddressAndPort)/1000
    if statusPublicationMillis - bhe.lastSeenWithThisAddressAndPort < 0:
        # old descriptor, bail
        logging.warn("Received old descriptor for bridge %s with timestamp %d",
                bhe.fingerprint, statusPublicationMillis/1000)
        return bhe
    
    # iterate over all known bridges and apply weighting factor
    discountAndPruneBridgeHistories(statusPublicationMillis)
    
    # add or update the descriptor in history
    db.updateIntoBridgeHistory(bhe)
    bhe = None
    
    # Increment total weighted time for all bridges by seconds since the last
    # status was published. Note, capped at 1 hour
    for bh in db.getAllBridgeHistory():
        bh.weightedTime += secondsSinceLastStatusPublication
        db.updateIntoBridgeHistory(bh)

    # For Running Bridges only:
    # compare the stored history against the descriptor and see if the
    # bridge has changed its address or port
    bhe = db.getBridgeHistory(bridge.fingerprint)
    if not bridge.running:
        log.notice("%s is not running" % bridge.fingerprint)
        return bhe

    # Parse the descriptor and see if the address or port changed
    # If so, store the weighted run time
    if bridge.orport != bhe.port or bridge.ip != bhe.ip:
        bhe.totalRunWeights += 1.0;
        bhe.weightedRunLength += bhe.tosa
        bhe.lastSeenWithDifferentAddressAndPort =\
                bhe.lastSeenWithThisAddressAndPort

    # Regardless of whether the bridge is new, kept or changed
    # its address and port, raise its WFU times and note its
    # current address and port, and that we saw it using them.
    bhe.weightedUptime += secondsSinceLastStatusPublication
    bhe.lastSeenWithThisAddressAndPort = statusPublicationMillis

    bhe.ip = str(bridge.ip)
    bhe.port = bridge.orport
    return db.updateIntoBridgeHistory(bhe)

def discountAndPruneBridgeHistories(discountUntilMillis):
    db = bridgedb.Storage.getDB()
    bhToRemove = []
    # Just check the first item to see if we're anywhere close yet
    sample = None
    for y in db.getAllBridgeHistory():
        sample = y
        break
    if not sample: return 0

    if discountUntilMillis - sample.lastDiscountedHistoryValues < discountIntervalMillis:
        return 0
    for bh in db.getAllBridgeHistory():
        # discount previous values by factor of 0.95 every 12 hours
        bh.discountWeightedFractionalUptimeAndWeightedTime(discountUntilMillis)

        if (bh.weightedTime != 0 and (bh.weightedUptime * 10000 / bh.weightedTime) < 1):
            bhToRemove.append(k)
        else:
            db.updateIntoBridgeHistory(bh)

    # prune items
    for k in bhToRemove: db.delBridgeHistory(k)