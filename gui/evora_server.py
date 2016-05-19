#!/usr/bin/python


import andor
import numpy as np
import ctypes
#import pyfits
from astropy.io import fits
import time
import Queue

from twisted.protocols import basic
from twisted.internet import protocol, reactor, threads

#import ProtoParser

# port for evora is 5502

# Global variables
image_path_queue = Queue.Queue()

class EvoraServer(basic.LineReceiver):
    def connectionMade(self):
        """
        If you send more than one line then the callback to start the gui will completely fail.
        """
        self.factory.clients.append(self)
        #self.sendMessage("Welcome to the Evora Server")
        #self.sendMessage("Starting camera")
        ep = EvoraParser()
        command = ep.parse("status") 
        self.sendMessage(str(command)) # activate the callback to give full control to the camera.
        

    def connectionLost(self, reason):
        #self.sendLine("Connection Lost")
        #if len(self.factory.clients) is 1:
        #    ep = EvoraParser()
        #    command = ep.parse("shutdown")
            #self.sendMessage(command)
        
        self.factory.clients.remove(self)            

    def lineReceived(self, line):
        print "received", line
        ep = EvoraParser()
        #command = ep.parse(line)
        d = threads.deferToThread(ep.parse, line)
        d.addCallback(self.sendData)
        #if command != None:
        #    self.sendMessage(str(command))
    
    def sendData(self, data):
        #print "Sending", data, "from server."
        if data != None:
            self.sendMessage(str(data))
           

    def sendMessage(self, message):
        for client in self.factory.clients:
            client.sendLine(message)


class EvoraClient(protocol.ServerFactory):
    protocol = EvoraServer
    clients = []

## Evora Parser commands sent here from server where it envokes the camera commands.
class EvoraParser(object):
    def __init__(self):
        self.e = Evora()

    def parse(self, input = None):
        print input
        input = input.split()
        if input[0] == 'connect':
            return self.e.startup()
        if input[0] == 'temp':
            return self.e.getTemp()
        if input[0] == 'setTEC':
            return self.e.setTEC(input[1])
        if input[0] == 'getTEC':
            return self.e.getTEC()
        if input[0] == 'warmup':
            return self.e.warmup()
        if input[0] == 'shutdown':
            print "entered shutdown"
            return self.e.shutdown()
        if input[0] == "status":
            return self.e.getStatus()
        if input[0] == "timings":
            return self.e.getTimings()
        if input[0] == "abort":
            return self.e.abort()
        if input[0] == 'clear':
            return self.e.clearImageQueue()
        if input[0] == 'realImage':
            return self.e.requestRealImage()
        if input[0] == 'expose':
            # split into different modes (single, real time, and series)
            # expose 1 flat 1 10 2
            # get the type of exposure (i.e. bias, flat, object)
            exposureSetting = int(input[1]) # this will be 1:singe, 2:real, or 3:series
            type = input[2]
            print type
            # exposure attributes
            expnum = int(input[3])
            itime = int(input[4]) # why int?
            bin = int(input[5])
            
            if(exposureSetting == 1):
                if(type == 'bias'):
                    print 'entered bias'
                    return self.e.bias_exposure(expnum, bin)
                else:
                    print 'not entered bias'
                    return self.e.expose(expnum, itime, bin)

        if input[0] == 'real':
            exposureSetting = int(input[1]) 
            type = input[2]
            print type
            # exposure attributes
            expnum = int(input[3])
            itime = int(input[4])
            binning = int(input[5])
            return self.e.realTimeExposure(itime, binning)
        if input[0] == 'series':
            exposureSetting = int(input[1]) 
            type = input[2]
            print type
            # exposure attributes
            expnum = int(input[3])
            itime = int(input[4])
            binning = int(input[5])
            return self.e.seriesExposure()

class Evora(object):

    def __init__(self):
        self.num = 0
        #self.image_path_queue = Queue.Queue()

    def getStatus(self):
        # if the first status[0] is 20075 then the camera is not initialized yet and
        # one needs to run the startup methodg.
        status = andor.GetStatus()
        return "status " + str(status[0]) + "," + str(status[1])

    def startup(self):
	"""
	20002 is the magic number.  Any different number and it didn't work.
	"""
        print andor.GetAvailableCameras()
        camHandle = andor.GetCameraHandle(0)
        print camHandle
        print 'set camera:', andor.SetCurrentCamera(camHandle[1])
	
	init = andor.Initialize("/usr/local/etc/andor")	

        print 'Init:', init

	state = andor.GetStatus()        

        print 'Status:', state
        
        print 'SetAcquisitionMode:', andor.SetAcquisitionMode(1);
        
        print 'SetShutter:', andor.SetShutter(1,0,50,50);
	
	return "connect " + str(init)

    def getTEC(self):
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
        print coolerStatusNames[result[0] - andor.DRV_TEMPERATURE_OFF], result[1]
        return_res = "getTEC " + str(result[0]) + "," + str(result[1])
        return return_res

    def setTEC(self,setPoint=None):

        result = self.getTEC().split(" ")[1].split(",")
        result = [int(result[0]), float(result[1])]
        print result

	print setPoint

        if setPoint is not None:
            if result[0] == andor.DRV_TEMPERATURE_OFF:
                andor.CoolerON()
            print andor.SetTemperature(int(setPoint))
            self.getTEC()
	return "setTEC " + str(setPoint)

    def warmup(self):
	"""
	Pre: Used to warmup camera.
	Post: Sets the temperature to 0 and turns the fan to 0 then turns the cooler off and 
	returns 1 that everything worked.
	"""
        andor.SetTemperature(0)
	andor.SetFanMode(0)
	andor.CoolerOFF()
	return "warmup 1"

    def getTemp(self):
        # 20037 is NotReached
        # 20035 is NotStabalized
        # 20036 is Stabalized
        # 20034 is Off  
        result = andor.GetTemperatureStatus()
        mode = andor.GetTemperatureF()
        txt = "" + str(mode[0])
	print result
	for e in result:
		txt = txt+","+str(e)
        return "temp " + txt

    def shutdown(self):
	self.warmup()
	res = self.getTemp()
	while res[1] < int(0):
		time.sleep(5)
		res = self.getTemp()
		print 'waiting: %s' % str(res[1])
	print 'closing down camera connection'
        andor.ShutDown()
        return "shutdown 1"

    def getTimings(self):
        retval, width, height = andor.GetDetector()
        print retval, width, height
        expTime, accTime, kTime = 1, 0, 0
        expTime,accTime,kTime = andor.GetAcquisitionTimings(expTime, accTime, kTime)
        print expTime,accTime,kTime

        return "timings"

    def requestRealImage(self):
        global image_path_queue
        #print 'returning request'
        filename = ""
        if(not image_path_queue.empty()):
            filename = image_path_queue.get()
        else:
            filename = None
        #print 'reached filename'
        return "realImage " + str(filename)
    
    def clearImageQueue(self):
        global image_path_queue
        image_path_queue.queue.clear() # clear the image path queue when client requests
        return "clear 1" # 1 for success
        
    def bias_exposure(self, expnum=None, bin=1):
        if expnum is None:
            self.num += 1
            expnum = self.num
        else:
            self.num = expnum

        retval,width,height = andor.GetDetector()
        print 'GetDetector:', retval,width,height
        # print 'SetImage:', andor.SetImage(1,1,1,width,1,height)
        print 'SetReadMode:', andor.SetReadMode(4)
        print 'SetImage:', andor.SetImage(bin,bin,1,width,1,height)
        print 'GetDetector (again):', andor.GetDetector()
    
        andor.SetShutter(1,2,0,0)

         # can't just set actual exposure.  Need to run GetAcquisitionTimings see page 42 of docs.
        print 'SetExposureTime:', andor.SetExposureTime(0)
    
        print 'StartAcquisition:', andor.StartAcquisition()

        status = andor.GetStatus()
        print status
        while(status[1]==andor.DRV_ACQUIRING):
            status = andor.GetStatus()
            # print statucs

        data = np.zeros(width/bin*height/bin, dtype='uint16')
        print data.shape
        result = andor.GetAcquiredData16(data)

        success = None
        if(result == 20002):
            success = 1 # for true
        else:
            success = 0 # for false 

        print result, 'success={}'.format(result == 20002)
        data=data.reshape(width/bin,height/bin)
        print data.shape,data.dtype
        hdu = fits.PrimaryHDU(data,do_not_scale_image_data=True,uint=True)
	filename = time.strftime('/data/forTCC/image_%Y%m%d_%H%M%S.fits')
        hdu.writeto(filename,clobber=True)
        print "wrote: {}".format(filename)
        #queue.put("expose " + filename)
        print "reached"
	return "expose "  + str(success) + "," + filename

        #print "this is a bias exposure"

    def expose(self,expnum=None, itime=2, bin=1):

        if expnum is None:
            self.num += 1
            expnum = self.num
        else:
        
            self.num = expnum

        retval,width,height = andor.GetDetector()
        print 'GetDetector:', retval,width,height
        # print 'SetImage:', andor.SetImage(1,1,1,width,1,height)
        print 'SetReadMode:', andor.SetReadMode(4)
        print 'SetAcquisitionMode:', andor.SetAcquisitionMode(1)
        print 'SetImage:', andor.SetImage(bin,bin,1,width,1,height)
        print 'GetDetector (again):', andor.GetDetector()
    
        andor.SetShutter(1,0,5,5)

         # can't just set actual exposure.  Need to run GetAcquisitionTimings see page 42 of docs.
        print 'SetExposureTime:', andor.SetExposureTime(itime)
        #expTime, accTime, kTime = ctypes.c_float(), ctypes.c_float(), ctypes.c_float()
        #expTime, accTime, kTime = andor.GetAcquisitionTimings()
        #print "Adjusted Exposure Time:", andor.GetAcquisitionTimings(expTime, accTime, kTime)
        print 'StartAcquisition:', andor.StartAcquisition()

        status = andor.GetStatus()
        print status
        while(status[1]==andor.DRV_ACQUIRING):
            status = andor.GetStatus()
            # print status

        data = np.zeros(width/bin*height/bin, dtype='uint16')
        print data.shape
        result = andor.GetAcquiredData16(data)

        success = None
        if(result == 20002):
            success = 1 # for true
        else:
            success = 0 # for false

        print result, 'success={}'.format(result == 20002)
        data=data.reshape(width/bin,height/bin)
        print data.shape,data.dtype
        hdu = fits.PrimaryHDU(data,do_not_scale_image_data=True,uint=True)
	filename = time.strftime('/data/forTCC/image_%Y%m%d_%H%M%S.fits')
        hdu.writeto(filename,clobber=True)
        print "wrote: {}".format(filename)
        #queue.put("expose " + filename)
	return "expose " + str(success) + ","+filename

    def realTimeExposure(self, itime, binning=1):
        global image_path_queue
        """
        This will start and exposure, likely the run till abort setting, and keep reading out images for the specified time.
        """
        retval,width,height = andor.GetDetector()
        print 'GetDetector:', retval,width,height

        print "SetAcquisitionMode:", andor.SetAcquisitionMode(5)
        print 'SetReadMode:', andor.SetReadMode(4)

        print 'SetImage:', andor.SetImage(binning,binning,1,width,1,height)
        print 'GetDetector (again):', andor.GetDetector()

        print 'SetExposureTime:', andor.SetExposureTime(itime)
        print 'SetKineticTime:', andor.SetKineticCycleTime(0)

        print "Shutter Success:", andor.SetShutter(1,0,5,5)

        print 'StartAcquisition:', andor.StartAcquisition()

        
        status = andor.GetStatus()
        print status
        counter = 1
        while(status[1]==andor.DRV_ACQUIRING):
            status = andor.GetStatus()
            
            print status
            acquired = andor.WaitForAcquisition()
            status = andor.GetStatus()
            if(status[1] == andor.DRV_ACQUIRING and acquired == andor.DRV_SUCCESS):
                data = np.zeros(width/binning*height/binning, dtype='uint16') # reserve room for image
                results = andor.GetMostRecentImage16(data) # store image data
                print results, 'success={}'.format(results == 20002) # print if the results were successful
                
                if(results == andor.DRV_SUCCESS): # if the array filled store successfully
                    data=data.reshape(width/binning,height/binning) # reshape into image
                    print data.shape,data.dtype
                    hdu = fits.PrimaryHDU(data,do_not_scale_image_data=True,uint=True)
                    filename = time.strftime('/tmp/image_%Y%m%d_%H%M%S.fits') 
                    hdu.writeto(filename,clobber=True)
                    print "wrote: {}".format(filename)
                    
                    # put file path in queue
                    image_path_queue.put(filename) # client will request a name from this 
                    print "Put %s in image queue"%filename
                print image_path_queue.qsize()
                counter += 1
        
        return "real 1" # exits with 1 for success
        



    def seriesExposure(self):
        return "Taking series exposure"

    def abort(self):
        """
        This will abort the exposure and throw it out.
        """
        print "Aborted:", andor.AbortAcquisition()
        return 'abort 1'
	
    def stop(self):
        """
        This will stop the exposure but read out where it stopped at, if possible.
        """
        pass

        




if __name__=="__main__":
    #ep = Evora()
    #ep.startup()
    reactor.listenTCP(5502, EvoraClient())
    reactor.run()

