'''Python implementation of the export of FSL results into NI-DM

@author: Camille Maumet <c.m.j.maumet@warwick.ac.uk>
@copyright: University of Warwick 2013-2014
'''

from HTMLParser import HTMLParser
from htmlentitydefs import name2codepoint
import re
from prov.model import ProvBundle, ProvRecord, ProvExceptionCannotUnifyAttribute, graph, ProvEntity
import prov.model.graph
import os
import numpy as np
import nibabel as nib
from NIDMStat import NIDMStat

# Parse an FSL result directory to extract the pieces information stored in NI-DM (for statistical results)
class FSL_NIDM():

    def __init__(self, *args, **kwargs):
        self.featDir = None
        self.nidm = NIDMStat();
        if 'featDir' in kwargs:
            self.featDir = kwargs.pop('featDir')
            self.parse_feat_dir()

    # Main function: parse a feat directory and build the corresponding NI-DM graph
    def parse_feat_dir(self):
        self.add_report_file(os.path.join(self.featDir, 'report_poststats.html'))
        self.add_model_fitting()
        self.maskFile = os.path.join(self.featDir, 'mask.nii.gz')
        self.add_search_space()

        for file in os.listdir(self.featDir):
            if file.startswith("thresh_zstat"):
                if file.endswith(".nii.gz"):
                    s = re.compile('zstat\d+')
                    zstatnum = s.search(file)
                    zstatnum = zstatnum.group()
                    self.add_contrast(zstatnum.replace('zstat', ''))
                    self.add_clusters_peaks(os.path.join(self.featDir, 'cluster_'+zstatnum+'.txt'))
                # FIXME: For now do only 1 zstat
                # break; 
        

        

    # Add model fitting, residuals map
    def add_model_fitting(self):
        residualsFile = os.path.join(self.featDir, 'stats', 'sigmasquareds.nii.gz')
        self.nidm.create_model_fitting(residualsFile)

    # For a given contrast, create the contrast map, contrast variance map, contrast and statistical map emtities
    def add_contrast(self, contrastNum):
        contrastFile = os.path.join(self.featDir, 'stats', 'cope'+str(contrastNum)+'.nii.gz')
        varContrastFile = os.path.join(self.featDir, 'stats', 'varcope'+str(contrastNum)+'.nii.gz')
        statMapFile = os.path.join(self.featDir, 'stats', 'zstat'+str(contrastNum)+'.nii.gz')

        designFile = open(os.path.join(self.featDir, 'design.con'), 'r')
        designTxt = designFile.read()
        # FIXME: to do only once (and not each time we load a new contrast)
        contrastNameSearch = re.compile(r'.*/ContrastName'+str(contrastNum)+'\s+(?P<contrastName>\w+)\s.*')
        extractedData = contrastNameSearch.search(designTxt) 

        # FIXME: to do only once (and not each time we load a new contrast)
        dofFile = open(os.path.join(self.featDir, 'stats', 'dof'), 'r')
        dof = float(dofFile.read())

        self.nidm.create_contrast_map(contrastFile, varContrastFile, statMapFile, extractedData.group('contrastName'), dof)

    # Create the search space entity generated by an inference activity
    def add_search_space(self):
        searchSpaceFile = os.path.join(self.featDir, 'mask.nii.gz')
        smoothnessFile = os.path.join(self.featDir, 'stats', 'smoothness')

        # Load DLH, VOLUME and RESELS
        smoothness = np.loadtxt(smoothnessFile, usecols=[1])
        self.nidm.create_search_space(searchSpaceFile=searchSpaceFile, searchVolume=smoothness[1], reselSizeInVoxels=smoothness[2])

    # Create the thresholding information for an inference activity (height threshold and extent threshold)
    def add_report_file(self, myReportFile):
        self.reportFile = myReportFile
        parser = MyFSLReportParser();
        file = open(myReportFile, 'r')
        parser.feed(file.read());

        self.nidm.create_thresholds( voxelThreshold=parser.get_voxelThreshValue(), 
            voxelPUncorr=parser.get_voxelPUncorr(), 
            voxelPCorr=parser.get_voxelPCorr(), 
            extent=parser.get_extentValue(),
            extentPUncorr=parser.get_extentPUncorr(), 
            extentPCorr=parser.get_extentPCorr())

    # Create excursion set, clusters and peaks entities
    def add_clusters_peaks(self, myZstatFile):

        # Excursion set
        zFileImg = myZstatFile.replace('cluster_', 'thresh_').replace('.txt', '.nii.gz')
        self.nidm.create_excursion_set(zFileImg=zFileImg)

        # Clusters
        self.zstatFile = myZstatFile
        clusterTable = np.loadtxt(myZstatFile, skiprows=1, ndmin=2)

        # FIXME: could be nicer (do not repeat for std)
        clusters = []
        for row in clusterTable:
            cluster = Cluster(int(row[0]))
            cluster.sizeInVoxels(row[1])
            cluster.set_pGRF(row[2])
            cluster.set_COG1(row[8])
            cluster.set_COG2(row[9])
            cluster.set_COG3(row[10])
            clusters.append(cluster)
            
        myStdZstatFile = myZstatFile.replace('.txt', '_std.txt')
        clusterStdTable = np.loadtxt(myStdZstatFile, skiprows=1, ndmin=2)
        clustersStd = []
        for row in clusterStdTable:
            cluster = Cluster(int(row[0]))
            cluster.sizeInVoxels(row[1])
            cluster.set_pGRF(row[2])
            cluster.set_COG1(row[8])
            cluster.set_COG2(row[9])
            cluster.set_COG3(row[10])
            clustersStd.append(cluster)

        # Peaks
        peakTable = np.loadtxt(myStdZstatFile.replace('cluster', 'lmax'), skiprows=1, ndmin=2)
        peaks = []
        for row in peakTable:
            peak = Peak(int(row[0]))
            peak.set_equivZStat(row[1])
            peak.set_x(row[2])
            peak.set_y(row[3])
            peak.set_z(row[4])
            peaks.append(peak)

        peakStdTable = np.loadtxt(myStdZstatFile.replace('cluster', 'lmax'), skiprows=1, ndmin=2)
        peaksStd = []
        for row in peakTable:
            peak = Peak(int(row[0]))
            peak.set_equivZStat(row[1])
            peak.set_x(row[2])
            peak.set_y(row[3])
            peak.set_z(row[4])
            peaksStd.append(peak)

        clusIdx = -1
        if clusters is not None:
            for cluster in clusters:               
                clusIdx = clusIdx + 1
                self.nidm.create_cluster(id=cluster.get_id(), size=cluster.get_SizeInVoxels(), pGRF=cluster.get_pGRF(),
                    COG1=cluster.get_COG1(),COG2=cluster.get_COG2(),COG3=cluster.get_COG3(),
                    COG1_std=clustersStd[clusIdx-1].get_COG1(),COG2_std=clustersStd[clusIdx-1].get_COG2(),COG3_std=clustersStd[clusIdx-1].get_COG3())
        
        if peaks is not None:
            peakIndex = 1;
            for peak in peaks:      

                self.nidm.create_peak(id=peakIndex, x=peak.get_x(), y=peak.get_y(), z=peak.get_z(), 
                    std_x=peaksStd[peakIndex-1].get_x(), std_y=peaksStd[peakIndex-1].get_y(), std_z=peaksStd[peakIndex-1].get_z(),
                    equivZ=peak.get_equivZStat(), clusterId=peak.get_cluster_id())
                peakIndex = peakIndex + 1
        
    # Create a graph as a png file, a provn and a json serialisations
    def save_prov_to_files(self):
        self.nidm.save_prov_to_files()


'''HTML parser for FSL report files: extract the thresholding information

'''
# TODO: check if the thresholding information is stored elsewhere in FSL files
class MyFSLReportParser(HTMLParser):

    def __init__(self, *args, **kwargs):
        HTMLParser.__init__(self, *args, **kwargs)
        self.descriptions = []
        self.inside_a_element = 0
        self.hyperlinks = []
        self.foundIntro = False;
        self.featVersion = ''
        self.pValue = []
        self.threshType = ''

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            for name, value in attrs:
                if name == "href":
                    self.hyperlinks.append(value)
                    self.inside_a_element = 1

    def handle_endtag(self, tag):
        if tag == 'a':
            self.inside_a_element = 0
    def handle_data(self, data):
        if self.inside_a_element:
            self.descriptions.append(data)
        elif not self.foundIntro:
            # Look for p-value, type of thresholding and feat version in introductory text
            patternVoxelThresh = re.compile(r'.*Version (?P<featversion>\d+\.\d+),.* thresholded using (?P<threshtype>.*) thresholding .* P=(?P<pvalue>\d+\.\d+)')

            extractedData = patternVoxelThresh.search(data) 
            
            if extractedData is not None:
                self.featVersion = extractedData.group('featversion')
                self.voxelThreshValue = None;
                self.voxelPCorr = extractedData.group('pvalue')
                self.voxelPUncorr = None
                self.extentValue = 0;
                self.extentPCorr = 1
                self.extentPUncorr = 1
                # self.threshType = extractedData.group('threshtype')
                self.foundIntro = True;
            else:
                patternClusterThresh = re.compile(r'.*Version (?P<featversion>\d+\.\d+),.* thresholded using (?P<threshtype>.*) determined by Z\>(?P<zvalue>\d+\.\d+) and a .* P=(?P<pvalue>\d+\.\d+) .*')
                extractedData = patternClusterThresh.search(data) 

                if extractedData is not None:
                    self.featVersion = extractedData.group('featversion')
                    self.voxelThreshValue = extractedData.group('zvalue')
                    self.voxelPCorr = None
                    self.voxelPUncorr = None
                    self.extentValue = None;
                    self.extentPCorr = extractedData.group('pvalue');
                    self.extentPUncorr = None
                    # self.threshType = extractedData.group('threshtype')
                    self.foundIntro = True;

    def get_threshold_p_value(self):
        return self.pValue

    def get_voxelThreshValue(self):
        return self.voxelThreshValue

    def get_voxelPCorr(self):
        return self.voxelPCorr

    def get_voxelPUncorr(self):
        return self.voxelPUncorr

    def get_extentValue(self):
        return self.extentValue

    def get_extentPCorr(self):
        return self.extentPCorr

    def get_extentPUncorr(self):
        return self.extentPUncorr

'''Peak class stored the information related to a given peak

'''
# TODO: check if indeed useful to have a class for this
class Peak():
    def __init__(self, clusterId, *args, **kwargs):
        self.cluster_id = clusterId
        self.equivZStat = None
        self.x = None
        self.y = None
        self.z = None

    def set_equivZStat(self,value):
        self.equivZStat = value

    def get_cluster_id(self):
        return self.cluster_id    

    def get_equivZStat(self):
        return self.equivZStat    

    def set_x(self,value):
        self.x = value
    def set_y(self,value):
        self.y = value
    def set_z(self,value):
        self.z = value

    def get_x(self):
        return self.x  
    def get_y(self):
        return self.y  
    def get_z(self):
        return self.z                  

'''Cluster class stores the information related to a given cluster

'''
# TODO: check if indeed useful to have a class for this
class Cluster():
    def __init__(self, clusterId, *args, **kwargs):
        self.cluster_id = clusterId
        self.clusterSizeInVoxels = None
        self.equivZStat = None
        self.pGRF = None
        self.COG1 = None
        self.COG2 = None
        self.COG3 = None

    def sizeInVoxels(self,value):
        self.clusterSizeInVoxels = value

    

    def set_COG1(self,value):
        self.COG1 = value   
    def set_COG2(self,value):
        self.COG2 = value   
    def set_COG3(self,value):
        self.COG3 = value   

    def get_COG1(self):
        return self.COG1
    def get_COG2(self):
        return self.COG2 
    def get_COG3(self):
        return self.COG3            

    def set_pGRF(self,value):
        self.pGRF = value        

    def get_id(self):
        return self.cluster_id

    def get_SizeInVoxels(self):
        return self.clusterSizeInVoxels



    def get_pGRF(self):
        return self.pGRF



