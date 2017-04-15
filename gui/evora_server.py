#!/usr/bin/env python2

# For Python 3 like functionality
from __future__ import print_function
from __future__ import division
from __future__ import absolute_import

# Comment on documentation:
# When reading the doc strings if "Pre:" is present then this stands for "precondition", or the conditions in order to invoke something.
# Oppositely, "Post:" stands for "postcondition" and states what is returned by the method.

__author__ = "Tristan J. Hillis"

## Imports
import subprocess
import sys
import time
import Queue
import thread
import threading
from datetime import datetime
from datetime import date

import andor
import numpy as np
from astropy.io import fits
import AddLinearSpacer as als
import MyLogger

from twisted.protocols import basic
from twisted.internet import protocol, reactor, threads

# ftp server imports
from twisted.protocols.ftp import FTPFactory
from twisted.protocols.ftp import FTPRealm
from twisted.cred.portal import Portal
from twisted.cred.checkers import AllowAnonymousAccess


# For filter controls
#from FilterMotor import filtermotor

# port for evora is 5502
# port for filter wheel is 5503
# port for ftp server is 5504

# Global Variables
acquired = None
t = None
isAborted = None  # tracks globally when the abort has been called.  Every call to the parser
                  # is an new instance
logger = MyLogger.myLogger("evora_server.py", "server")
# Get gregorian date, local
#d = date.today()
#logFile = open("/home/mro/ScienceCamera/gui/logs/log_server_" + d.strftime("%Y%m%d") + ".log", "a")


class EvoraServer(basic.LineReceiver):
    """
    This is the Evora camera server code using Twisted's convienience object of basic.LineReceiver.
    When a line is recieved from the client it is sent to the parser to execute the camera commands
    and the resulting data is sent back to the client.  This a threaded server so that long
    running functions in the parser don't hang the whole server.
    """
    
    def connectionMade(self):
        """
        If you send more than one line then the callback to start the gui will completely fail.
        """
        self.factory.clients.append(self)
        ep = EvoraParser(self)
        command = ep.parse("status") 
        self.sendMessage(str(command)) # activate the callback to give full control to the camera.

    def connectionLost(self, reason):
        """
        Adds connecting client to the list of existing clients.
        """
        self.factory.clients.remove(self)

    def lineReceived(self, line):
        """
        Called when server recieves a line. Runs the line through the parser and then
        sends the resulting data off.
        """
        logger.debug("received " + line)
        ep = EvoraParser(self)
        d = threads.deferToThread(ep.parse, line)
        d.addCallback(self.sendData)

    def sendData(self, data):
        """
        Decorator method to self.sendMessage(...) so that it
        sends the resulting data to every connected client.
        """
        if data is not None:
            self.sendMessage(str(data))

    def sendMessage(self, message):
        """
        Sends message to every connect client.
        """
        for client in self.factory.clients:
            client.sendLine(message)


class EvoraClient(protocol.ServerFactory):
    """
    This makes up the twistedPython factory that defines the protocol and stores
    a list of the clients connect.
    """
    protocol = EvoraServer
    clients = []

## Evora Parser commands sent here from server where it envokes the camera commands.
class EvoraParser(object):
    """
    This object parses incoming data lines from the client and executes the respective hardware
    driver code.
    """
    
    def __init__(self, protocol):
        """
        Trickles down the protocol for potential usage as well as defines an instance of Evora (the object
        that holds the driver code).
        """
        self.e = Evora()
        self.protocol = protocol

    def parse(self, input=None):
        """
        Receive an input and splits it up and based on the first argument will execute the right method 
        (e.g. input=connect will run the Evora startup routine).
        """
        input = input.split()
        if input[0] == 'connect':
            """
            Run Evora initialization routine.
            """
            return self.e.startup()

        if input[0] == 'temp':
            """
            Get the current temperature and more of the camera.
            """
            return self.e.getTemp()

        if input[0] == 'tempRange':
            """
            Used to see the cooler temperature range from the camera itself.
            """
            return self.e.getTempRange()

        if input[0] == 'setTEC':
            """
            Set Thermo-electric cooler target temperature with an input.  Excepts values of -10 to -100 within
            specifications.  Cooler may not be able to push to the furthest end with high ambient temperature.
            """
            return self.e.setTEC(input[1])

        if input[0] == 'getTEC':
            """
            Get the status of the thermo-electric cooler.
            """
            return self.e.getTEC()

        if input[0] == 'warmup':
            """
            Run Evora camera warmup routine.
            """
            return self.e.warmup()

        if input[0] == 'shutdown':
            """
            Run Evora shutdown routine.
            """
            return self.e.shutdown()

        if input[0] == "status":
            """
            Gets the current status of the camera.  For example, it will return an integer code saying it is uninitialized 
            or, perhaps, currently acquisitioning.
            """
            return self.e.getStatus()
        
        if input[0] == "timings":
            """
            This retrieves the timings for the current Evora settings.  May not work since every new call of the parser
            is a new Evora instance variable.
            """
            return self.e.getTimings()
        
        if input[0] == "vertStats":
            """
            Specify and index as the input. See the Andor SDK documentation for more information.
            """
            return self.e.verticalSpeedStats(int(input[1]))
        
        if input[0] == "horzStats":
            """
            Specify channel, type, and an index as the inputs.  See the Andor SDK documentation for more information.
            """
            return self.e.horizontalSpeedStats(int(input[1]), int(input[2]), int(input[3]))
        
        if input[0] == "abort":
            """
            Calls the Evora abort command to stop an exposure.  Appears there is no way to then readout the 
            CCD partially.
            """
            return self.e.abort()
        
        if input[0] == 'expose':
            """
            This if entry exectues a single exposure command.  The required arguements to define (i.e.
            when using Telnet) are image type, such as bias, the number of exposures (should be one), the integration time, the
            binning type (1x1 or 2x2), and a readoutIndex (0, 1, 2, or 4). Filter type should be specified but is not
            required and is the last arguement.

            Example line: expose object 1 20 2 3 g
            """
            
            # Note to self: get rid of expNum, a different method handles getting multiple images.
            imType = input[1]
            # exposure attributes
            expnum = int(input[2])
            itime = float(input[3])  # why int?
            binning = int(input[4])
            readoutIndex = int(input[5])
            filter = ""
            try:
                filter = str(input[6])
            except IndexError:
                pass
            
            return self.e.expose(imType, expnum, itime, binning, readTime=readoutIndex, filter=filter)
        
        if input[0] == 'real':
            """
            This if entry handles the real time series exposure where the camera runs in RunTillAbort mode.
            The arguements to give (i.e. using Telnet) are image type (e.g. bias), exposure number, integration time,
            and binning type (1x1 or 2x2).

            Example: real object 1 5 2
            """
            # command real flat 1 10 2
            imType = input[1]
            # exposure attributes
            expnum = int(input[2])  # don't need this
            itime = float(input[3])
            binning = int(input[4])
            return self.e.realTimeExposure(self.protocol, imType, itime, binning)
        
        if input[0] == 'series':
            """
            This handles taking multiple images in one go.  The arguements to sepcify (ie when using Telnes) are
            image type (eg bias), exposure number (>1), integration time, binning type (1x1 or 2x2), the readout index
            (0, 1, 2, or 3).  The last arguement is the filter name which isn't required but is recommended to include.

            Example: series object 5 20 2 3 g
            """
            # series bias 1 10 2
            imType = input[1]
            # exposure attributes
            expnum = int(input[2])
            itime = float(input[3])
            binning = int(input[4])
            readoutIndex = int(input[5])
            filter = ""
            try:
                filter = str(input[6])
            except IndexError:
                pass
            return self.e.kseriesExposure(self.protocol, imType, itime, readTime=readoutIndex, filter=filter,
                                          numexp=expnum, binning=binning)


class Evora(object):

    """
    This class executes the driver code through the "andor" import which is "swigged" C++ code.

    Replace all the prints with a safe call method.
    """
    
    def __init__(self):
        self.num = 0

    def getStatus(self):
        """
        No input needed. Returns an integer value representing the camera status.  E.g. 20075 means
        the camera is uninitialized.
        """
        # if the first status[0] is 20075 then the camera is not initialized yet and
        # one needs to run the startup method.
        status = andor.GetStatus()
        return "status " + str(status[0]) + "," + str(status[1])

    def startup(self):
	"""
        20002 is the magic number.  Any different number and it didn't work.
        """
        logger.debug(str(andor.GetAvailableCameras()))
        camHandle = andor.GetCameraHandle(0)
        logger.debug(str(camHandle))
        
        logger.debug('set camera: ' + str(andor.SetCurrentCamera(camHandle[1])))

        init = andor.Initialize("/usr/local/etc/andor")

        logger.debug('Init: ' + str(init))

        state = andor.GetStatus()

        logger.debug('Status: ' + str(state)) 

        logger.debug('SetAcquisitionMode: ' + str(andor.SetAcquisitionMode(1)))

        logger.debug('SetShutter: ' + str(andor.SetShutter(1,0,50,50)))

        # make sure cooling is off when it first starts
        logger.debug('SetTemperature: ' + str(andor.SetTemperature(0)))
        logger.debug('SetFan ' + str(andor.SetFanMode(0)))
        logger.debug('SetCooler ' + str(andor.CoolerOFF()))

        return "connect " + str(init)

    def getTEC(self):
        """
        Gets the TEC status by calling andor.GetTemperatureF
        """
        # index on [result[0] - andor.DRV_TEMPERATURE_OFF]
        coolerStatusNames = ('Off', 'NotStabilized', 'Stabilized',
                             'NotReached', 'OutOfRange', 'NotSupported',
                             'WasStableNowDrifting')

        # 20037 is NotReached
        # 20035 is NotStabalized
        # 20036 is Stabalized
        # 20034 is Off

        result = andor.GetTemperatureF()
        res = coolerStatusNames[result[0] - andor.DRV_TEMPERATURE_OFF]
        logger.debug(str(coolerStatusNames[result[0] - andor.DRV_TEMPERATURE_OFF]) + " " + str(result[1]))
        return_res = "getTEC " + str(result[0]) + "," + str(result[1])
        return return_res

    def setTEC(self, setPoint=None):
        """
        Turns on TEC and sets the temperature with andor.SetTemperature
        """
        result = self.getTEC().split(" ")[1].split(",")
        result = [int(result[0]), float(result[1])]
        logger.debug(str(result))

        logger.debug(str(setPoint))

        if setPoint is not None:
            if result[0] == andor.DRV_TEMPERATURE_OFF:
                andor.CoolerON()
            logger.debug(str(andor.SetTemperature(int(setPoint))))
            self.getTEC()
        return "setTEC " + str(setPoint)

    def warmup(self):
	"""
        Pre: Used to warmup camera.
        Post: Sets the temperature to 0 and turns the fan to 0 then turns the cooler off and
        returns 1 that everything worked.
        """
        setTemp = andor.SetTemperature(0)
        setFan = andor.SetFanMode(0)
        setCooler = andor.CoolerOFF()

        results = 1
        if(setFan != andor.DRV_SUCCESS or setCooler != andor.DRV_SUCCESS):
            results = 0
        return "warmup " + str(results)

    def getTemp(self):
        """
        Used to get the temperature as well as other status.
        """
        # 20037 is NotReached
        # 20035 is NotStabalized
        # 20036 is Stabalized
        # 20034 is Off
        result = andor.GetTemperatureStatus()
        mode = andor.GetTemperatureF()
        txt = "" + str(mode[0])
        logger.debug(str(result))
        for e in result:
            txt = txt+","+str(e)
        return "temp " + txt

    def getTempRange(self):
        """
        Used to get the range of temperature, in C, that the hardware allows.
        """
        stats = andor.GetTemperatureRange()
        result = stats[0]
        mintemp = stats[1]
        maxtemp = stats[2]
        return "tempRange " + "%s,%s,%s" % (result, mintemp, maxtemp)

    def shutdown(self):
        """
        Warms up camera by turning off the cooler and then shuts down the camera.
        Future versions should have it wait till the camera is warmed up to 0 C at least.
        """

        self.warmup()
        res = self.getTemp()
        res = res.split(" ")[1].split(",")
        """
        while float(res[2]) < 0:
            time.sleep(5)
            res = self.getTemp()
            res = res.split(" ")[1].split(",")
            print('waiting: %s' % str(res[2]))
        """
        logger.info('closing down camera connection')
        andor.ShutDown()
        return "shutdown 1"

    def getTimings(self):
        """
        Used to get the actual time in seconds the exposure will take.
        """
        #retval, width, height = andor.GetDetector()
        #print retval, width, height
        expTime, accTime, kTime = andor.GetAcquisitionTimings()
        logger.debug(str(expTime) + " " + str(accTime) + " " + str(kTime))
        
        return "timings"

    def verticalSpeedStats(self, index):
        """
        Gets the vertical readout speed stats.
        """
        logger.debug("GetNumberVSSpeeds: " + str(andor.GetNumberVSSpeeds()))
        logger.debug("GetNumberVSAmplitudes: " + str(andor.GetNumberVSAmplitudes()))
        logger.debug("GetVSSpeed: " + str(andor.GetVSSpeed(index)))
        logger.debug("GetFastestRecommendedVSSpeed: " + str(andor.GetFastestRecommendedVSSpeed()))

    def horizontalSpeedStats(self, channel, type, index):
        """
        Gets the stats of the horizontal readout speed.
        """
        logger.debug("GetNumberHSSpeeds: " + str(andor.GetNumberHSSpeeds(channel, type)))
        logger.debug("GetHSSpeed: " + str(andor.GetHSSpeed(channel, type, index)))


    def abort(self):
        """
        This will abort the exposure and throw it out.
        """
        global isAborted
        isAborted = True
        self.isAbort = True
        logger.debug("Aborted: " + str(andor.AbortAcquisition()))
        return 'abort 1'

    def getHeader(self, attributes):
        """
        Pre: Takes in a list of attributes: [imType, binning, itime]
        Post: Returns an AstroPy header object to be used for writing to.
        """
        imType, binning, itime, filter = attributes[0], attributes[1], attributes[2], attributes[3]
        # make new fits header object
        header = fits.Header()
        ut_time = time.gmtime() # get UT time
        dateObs = time.strftime("%Y-%m-%dT%H:%M:%S", ut_time)
        ut_str = time.strftime("%H:%M:%S", ut_time)
        header.append(card=("DATE-OBS", dateObs, "Time at start of exposure"))
        header.append(card=("UT", ut_str, "UT time at start of exposure"))
        header.append(card=("OBSERVAT", "mro", "per the iraf list"))
        header.append(card=("IMAGETYP", imType))
        header.append(card=("FILTER", filter))
        header.append(card=("BINX", binning, "Horizontal Binning"))
        header.append(card=("BINY", binning, "Vertical Binning"))
        header.append(card=("EXPTIME", itime, "Total exposure time"))
        header.append(card=("ACQMODE", "Single Scan", "Acquisition mode"))
        header.append(card=("READMODE", "Image", "Readout mode"))
        header.append(card=("INSTRUME", "evora", "Instrument used for imaging"))
        header.append(card=("LATITUDE", 120.744466667, "Decimal degrees of MRO latitude"))
        header.append(card=("LONGITUD", 46.9528, "Decimal degress of MRO longitude"))

        # get readout time and temp
        temp = andor.GetTemperatureStatus()[1]
        readTime = andor.GetAcquisitionTimings()[3] - itime
        header.append(card=("TEMP", temp, "Temperature"))
        header.append(card=("READTIME", readTime, "Pixel readout time"))

        return header

    def getHeader2(self, attributes):
        """
        Pre: Takes in a list of attributes: [imType, binning, itime]
        Post: Returns an AstroPy header object to be used for writing to.
        """
        imType, binning, itime, filter = attributes[0], attributes[1], attributes[2], attributes[3]
        # make new fits header object
        header = fits.Header()
        ut_time = time.gmtime() # get UT time
        dateObs = time.strftime("%Y-%m-%dT%H:%M:%S", ut_time)
        ut_str = time.strftime("%H:%M:%S", ut_time)
        header.append(card=("DATE-OBS", dateObs, "Time at start of exposure"))
        header.append(card=("UT", ut_str, "UT time at start of exposure"))
        header.append(card=("OBSERVAT", "mro", "per the iraf list"))
        header.append(card=("IMAGETYP", imType))
        header.append(card=("FILTER", filter))
        header.append(card=("BINX", binning, "Horizontal Binning"))
        header.append(card=("BINY", binning, "Vertical Binning"))
        header.append(card=("EXPTIME", itime, "Total exposure time"))
        header.append(card=("ACQMODE", "Single Scan", "Acquisition mode"))
        header.append(card=("READMODE", "Image", "Readout mode"))
        header.append(card=("INSTRUME", "evora", "Instrument used for imaging"))
        header.append(card=("LATITUDE", 120.744466667, "Decimal degrees of MRO latitude"))
        header.append(card=("LONGITUD", 46.9528, "Decimal degress of MRO longitude"))

        # get readout time and temp
        temp = andor.GetTemperatureStatus()[1]
        readTime = andor.GetAcquisitionTimings()[3] - itime
        header.append(card=("TEMP", temp, "Temperature"))
        header.append(card=("READTIME", readTime, "Pixel readout time"))

        # NEEDED header keywords
        # RA / Right Ascension
        # DEC / Declination
        # EPOCH / Epoch for RA and Dec (years)
        # ST / local sidereal time (hours)
        # HA / Hour Angle
        # ZD / Zenith Angle
        # AIRMASS
        # UTMIDDLE
        # JD
        # HJD
        # LJD
        
        return header

    
    def expose(self, imType=None, expnum=None, itime=2, binning=1, filter="", readTime=3):
        """
        expNum is deprecated and should be removed.
        This handles a single exposure and no more.  Inputs are the image type integration time, binning type
        filter type, as a string, and the index for the specified horizontal readout time.
        """
        if expnum is None:
            self.num += 1
            expnum = self.num
        else:
            self.num = expnum

        if imType is None: # if the image type is not specified it defaults to object
            imType = "object"

        retval, width, height = andor.GetDetector()
        logger.debug('GetDetector: ' + str(retval) + " " + str(width) + " " + str(height))
        # print 'SetImage:', andor.SetImage(1,1,1,width,1,height)
        logger.debug('SetReadMode: ' + str(andor.SetReadMode(4)))
        logger.debug('SetAcquisitionMode: ' + str(andor.SetAcquisitionMode(1)))
        logger.debug('SetImage: ' + str(andor.SetImage(binning,binning,1,width,1,height)))
        logger.debug('GetDetector (again): ' + str(andor.GetDetector()))

        if(imType == "bias"):
            andor.SetShutter(1,2,0,0) # TLL mode high, shutter mode Permanently Closed, 0 millisec open/close
            logger.debug('SetExposureTime: ' + str(andor.SetExposureTime(0)))
        else:
            if(imType in ['flat', 'object']):
                andor.SetShutter(1,0,5,5)
            else:
                andor.SetShutter(1,2,0,0)
            logger.debug('SetExposureTime: ' + str(andor.SetExposureTime(itime)))  # TLL mode high, shutter mode Fully Auto, 5 millisec open/close

        # set Readout speeds 0, 1, 2, or 3
        #print("SetVSSpeed:", andor.SetVSSpeed(3))
        logger.debug("SetHSSpeed: " + str(andor.SetHSSpeed(0, readTime)))  # default readTime is index 3 which is 0.5 MHz or ~6 sec

        results, expTime, accTime, kTime = andor.GetAcquisitionTimings()
        logger.debug("Adjusted Exposure Time: " + str([results, expTime, accTime, kTime]))

        attributes = [imType, binning, itime, filter]
        header = self.getHeader(attributes)

        logger.debug('StartAcquisition: ' + str(andor.StartAcquisition()))

        status = andor.GetStatus()
        logger.debug(str(status))
        while status[1] == andor.DRV_ACQUIRING:
            status = andor.GetStatus()

        data = np.zeros(width//binning*height//binning, dtype='uint16')
        logger.debug(str(data.shape))
        result = andor.GetAcquiredData16(data)

        success = None
        if(result == 20002):
            success = 1 # for true
        else:
            success = 0 # for false

        logger.debug(str(result) + 'success={}'.format(result == 20002))
        filename = None
        if success == 1:
            data=data.reshape(width//binning,height//binning)
            logger.debug(str(data.shape) + " " + str(data.dtype))
            hdu = fits.PrimaryHDU(data,do_not_scale_image_data=True,uint=True, header=header)
            #filename = time.strftime('/data/forTCC/image_%Y%m%d_%H%M%S.fits')
            filename = als.getImagePath('expose')
            hdu.writeto(filename,clobber=True)
            logger.debug("wrote: {}".format(filename))
        return "expose " + str(success) + ","+str(filename) + "," + str(itime)

    def realTimeExposure(self, protocol, imType, itime, binning=1):
        """
        Inputs are the Evora server protocol, the image type, the integration time, and the binning size.
        Runs camera in RunTillAbort mode.
        """
        #global acquired
        retval,width,height = andor.GetDetector()
        logger.debug('GetDetector: ' + str(retval) + " " + str(width) + " " + str(height))

        logger.debug("SetAcquisitionMode: " + str(andor.SetAcquisitionMode(5)))
        logger.debug('SetReadMode: ' + str(andor.SetReadMode(4)))

        logger.debug('SetImage: ' + str(andor.SetImage(binning,binning,1,width,1,height)))
        logger.debug('GetDetector (again): ' + str(andor.GetDetector()))

        logger.debug('SetExposureTime: ' + str(andor.SetExposureTime(itime)))
        logger.debug('SetKineticTime: ' + str(andor.SetKineticCycleTime(0)))


        if(imType == "bias"):
            andor.SetShutter(1,2,0,0) # TLL mode high, shutter mode Permanently Closed, 0 millisec open/close
            logger.debug('SetExposureTime: ' + str(andor.SetExposureTime(0)))
        else:
            if(imType in ['flat', 'object']):
                andor.SetShutter(1,0,5,5)
            else:
                andor.SetShutter(1,2,0,0)
            logger.debug('SetExposureTime: ' + str(andor.SetExposureTime(itime))) # TLL mode high, shutter mode Fully Auto, 5 millisec open/close
            
        data = np.zeros(width//binning*height//binning, dtype='uint16')
        logger.debug("SetHSSpeed: " + str(andor.SetHSSpeed(0, 1)))  # read time on real is fast because they aren't science images
        logger.debug('StartAcquisition: ' + str(andor.StartAcquisition()))

        
        status = andor.GetStatus()
        logger.debug(str(status))
        workingImNum = 1
        start = time.time()
        end = 0
        while(status[1]==andor.DRV_ACQUIRING):
           
            progress = andor.GetAcquisitionProgress()
            currImNum = progress[2] # won't update until an acquisition is done
            status = andor.GetStatus()

            if(status[1] == andor.DRV_ACQUIRING and currImNum == workingImNum):
                logger.debug("Progress: " + str(andor.GetAcquisitionProgress()))
                results = andor.GetMostRecentImage16(data) # store image data
                logger.debug(str(results) + 'success={}'.format(results == 20002)) # print if the results were successful
                
                if(results == andor.DRV_SUCCESS): # if the array filled store successfully
                    data=data.reshape(width//binning,height//binning) # reshape into image
                    logger.debug(str(data.shape) + " " + str(data.dtype))
                    hdu = fits.PrimaryHDU(data,do_not_scale_image_data=True,uint=True)
                    #filename = time.strftime('/tmp/image_%Y%m%d_%H%M%S.fits') 
                    filename = als.getImagePath('real')
                    hdu.writeto(filename,clobber=True)
                    logger.debug("wrote: {}".format(filename))
                    data = np.zeros(width//binning*height//binning, dtype='uint16')

                    protocol.sendData("realSent " + filename)
                    workingImNum += 1
                    end = time.time()
                    logger.debug("Took %f seconds" % (end-start))
                    start = time.time()

        return "real 1" # exits with 1 for success

    def kseriesExposure(self, protocol, imType, itime, filter="", readTime=3, numexp=1, binning=1, numAccum=1, accumCycleTime=0, kCycleTime=0):
        """
        This handles multiple image acquisition using the camera kinetic series capability.  The basic arguements are
        the passed in protocol, the image type, integration time, filter type, readout index, number of exposures, and binning type.

        In the future this function could be modified to include accumulations or add time the kinetic cycle time.  Accumulations 
        are how many images should be readout as one, and kCycleTime can add time between each exposure that is taken.
        """
        global isAborted
        isAborted = False
        retval,width,height = andor.GetDetector()
        logger.debug('GetDetector: ' + str(retval) + " " + str(width) + " " + str(height))

        logger.debug("SetAcquisitionMode: " + str(andor.SetAcquisitionMode(3)))
        logger.debug('SetReadMode: ' + str(andor.SetReadMode(4)))

        logger.debug('SetImage: ' + str(andor.SetImage(binning,binning,1,width,1,height)))
        logger.debug('GetDetector (again): ' + str(andor.GetDetector()))

        if(imType == "bias"):
            itime = 0
            andor.SetShutter(1,2,0,0) # TLL mode high, shutter mode Permanently Closed, 0 millisec open/close
            logger.debug('SetExposureTime: ' + str(andor.SetExposureTime(0)))
        else:
            if(imType in ['flat', 'object']):
                andor.SetShutter(1,0,5,5)
            else:
                andor.SetShutter(1,2,0,0)
            logger.debug('SetExposureTime: ' + str(andor.SetExposureTime(itime))) # TLL mode high, shutter mode Fully Auto, 5 millisec open/close

        logger.debug("SetNumberOfAccumulations: " + str(andor.SetNumberAccumulations(numAccum))) # number of exposures to be combined
        logger.debug("SetAccumulationTime: " + str(andor.SetAccumulationCycleTime(accumCycleTime)))
        logger.debug("SetNumberOfKinetics: " + str(andor.SetNumberKinetics(numexp))) # this is the number of exposures the user wants
        logger.debug('SetKineticTime: ' + str(andor.SetKineticCycleTime(accumCycleTime)))
        logger.debug("SetTriggerMode: " + str(andor.SetTriggerMode(0)))

        logger.debug("Timings: " + str(andor.GetAcquisitionTimings()))

        logger.debug("SetHSSpeed: " + str(andor.SetHSSpeed(0, readTime)))  # default readTime is index 3 which is 0.5 MHz or ~6 sec

        # write headers
        attributes = [imType, binning, itime, filter]
        header = self.getHeader(attributes)

        logger.debug('StartAcquisition: ' + str(andor.StartAcquisition()))

        status = andor.GetStatus()
        logger.debug(str(status))

        imageAcquired = False

        counter = 1
        while(status[1] == andor.DRV_ACQUIRING):
            status = andor.GetStatus()
            progress = andor.GetAcquisitionProgress()

            runtime = 0
            if(progress[2] == counter or (not isAborted and progress[2] == 0 and imageAcquired)):
                runtime -= time.clock()
                data = np.zeros(width//binning*height//binning, dtype='uint16')  # reserve room for image
                results = andor.GetMostRecentImage16(data)  # store image data
                logger.debug(str(results) + " " + 'success={}'.format(results == 20002))  # print if the results were successful
                logger.debug('image number: ' + str(progress[2]))

                if(results == andor.DRV_SUCCESS):  # if the array filled store successfully
                    data=data.reshape(width//binning,height//binning)  # reshape into image
                    logger.debug(str(data.shape) + " " + str(data.dtype))
                    
                    hdu = fits.PrimaryHDU(data,do_not_scale_image_data=True,uint=True, header=header)
                    #filename = time.strftime('/data/forTCC/image_%Y%m%d_%H%M%S.fits') 
                    filename = als.getImagePath('series')
                    hdu.writeto(filename,clobber=True)

                    logger.debug("wrote: {}".format(filename))
                    
                    protocol.sendData("seriesSent"+str(counter)+" "+str(counter)+","+str(itime)+","+filename)
                    # make a new header and write time to it for new exposure.
                    header = self.getHeader(attributes)

                    if(counter == numexp):
                        logger.info("entered abort")
                        isAborted = True

                    imageAcquired = True
                    counter += 1
                runtime += time.clock()
                logger.debug("Took %f seconds to write." % runtime)
        return "series 1,"+str(counter) # exits with 1 for success


    # deprecated to kseriesExposure
    """
    def seriesExposure(self, protocol, imType, itime, numexp=1, binning=1):
        global isAborted
        isAborted = False
        
        This will start and exposure, likely the run till abort setting, and keep reading out images for the specified time.
        
        retval,width,height = andor.GetDetector()
        print('GetDetector:', retval,width,height)

        print("SetAcquisitionMode:", andor.SetAcquisitionMode(5))
        print('SetReadMode:', andor.SetReadMode(4))

        print('SetImage:', andor.SetImage(binning,binning,1,width,1,height))
        print('GetDetector (again):', andor.GetDetector())

        print('SetExposureTime:', andor.SetExposureTime(itime))
        print('SetKineticTime:', andor.SetKineticCycleTime(0))

        if(imType == "bias"):
            itime = 0
            andor.SetShutter(1,2,0,0) # TLL mode high, shutter mode Permanently Closed, 0 millisec open/close
            print('SetExposureTime:', andor.SetExposureTime(0))
        else:
            andor.SetShutter(1,0,5,5)
            print('SetExposureTime:', andor.SetExposureTime(itime)) # TLL mode high, shutter mode Fully Auto, 5 millisec open/close

        data = np.zeros(width/binning*height/binning, dtype='uint16') # reserve room for image

        print('StartAcquisition:', andor.StartAcquisition())

        status = andor.GetStatus()

        print(status)
        counter = 1
        
        while(status[1]==andor.DRV_ACQUIRING and counter <= numexp):
            status = andor.GetStatus()
            
            progress = andor.GetAcquisitionProgress()
            status = andor.GetStatus()

            if(status[1] == andor.DRV_ACQUIRING and progress[2] == counter):
                results = andor.GetMostRecentImage16(data) # store image data
                print(results, 'success={}'.format(results == 20002)) # print if the results were successful
                
                if(results == andor.DRV_SUCCESS): # if the array filled store successfully
                    data=data.reshape(width/binning,height/binning) # reshape into image
                    print(data.shape,data.dtype)

                    hdu = fits.PrimaryHDU(data,do_not_scale_image_data=True,uint=True)
                    #filename = time.strftime('/data/forTCC/image_%Y%m%d_%H%M%S.fits') 
                    filename = als.getImagePath('series')
                    hdu.writeto(filename,clobber=True)

                    print("wrote: {}".format(filename))
                    
                    protocol.sendData("seriesSent"+str(counter)+" "+str(counter)+","+itime+","+filename)

                counter += 1
        print("Aborting", andor.AbortAcquisition())
        return "series 1,"+str(counter) # exits with 1 for success
    """

    
class Logger(object):
    """
    This class when assigned to sys.stdout or sys.stderr it will write to a file that is opened everytime a new GUI session is started.
    It also writes to the terminal window.
    """
    def __init__(self, stream):
        self.terminal = stream

    def write(self, message):
        self.terminal.flush()
        self.terminal.write(message)
        logFile.write(self.stamp() + message) # This prints weirdly but works for now

    def stamp(self):
        d = datetime.today()
        string = d.strftime(" [%b %m, %y, %H:%M:%S] ")
        return string

class FTPThread(threading.Thread):
    def __init__(self):
        threading.Thread.__init__(self)

    def run(self):
        print("Creating FTP Server")
        p = Portal(FTPRealm("/home/mro/data/raw/"), [AllowAnonymousAccess()])
        f = FTPFactory(p)
        f.timeOut = None
        reactor.listenTCP(5504, f)

class FilterThread(threading.Thread):
    def __init__(self):
        threading.Thread.__init__(self)
        self.on = True # This handles whether the Filter Server is gets shutdown on or not
    def run(self):
        print("Starting server")
        server_pipe = subprocess.Popen('ssh -xtt mro@192.168.1.30', stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
        server_pipe.stdin.write("./FilterServer\n")
        while self.on:
            print("Filter Server on")
            time.sleep(1)
        server_pipe.stdin.close()
        server_pipe.wait()
        time.sleep(10)

if __name__ == "__main__":
    filter_server = None
    try:
        #sys.stdout = Logger(sys.stdout)
        #sys.stderr = Logger(sys.stderr)

        #ep = Evora()
        #ep.startup()
        reactor.suggestThreadPoolSize(30)
        reactor.listenTCP(5502, EvoraClient())

        # Once the camera server starts start the ftp server
        ftp_server = FTPThread()
        ftp_server.daemon = True
        ftp_server.run()

        filter_server = FilterThread()
        #filter_server.daemon = True
        filter_server.start()
        print("Server ready.")
        reactor.run()
    except KeyboardInterrupt:
        filter_server.on = False
        filter_server.stop()
        sys.exit(0)
