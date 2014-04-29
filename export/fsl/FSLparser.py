'''Export of FSL results into NI-DM

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

# TODO:
# - Deal with F-contrasts


# Parse an FSL result directory to extract the pieces information stored in NI-DM (for statistical results)
class FSL_NIDM():

    def __init__(self, *args, **kwargs):
        self.feat_dir = kwargs.pop('feat_dir')
        self.export_dir = os.path.join(self.feat_dir, 'nidm')
        self.nidm = NIDMStat(export_dir=self.export_dir);

        self.parse_feat_dir()

    # Main function: parse a feat directory and build the corresponding NI-DM graph
    def parse_feat_dir(self):
        self.add_report_file(os.path.join(self.feat_dir, 'report_poststats.html'))
        self.add_model_fitting()
        self.maskFile = os.path.join(self.feat_dir, 'mask.nii.gz')
        self.add_search_space()

        # Find parameter estimates
        for file in os.listdir(os.path.join(self.feat_dir, 'stats')):
            if file.startswith("pe"):
                if file.endswith(".nii.gz"):
                    s = re.compile('pe\d+')
                    penum = s.search(file)
                    penum = penum.group()
                    penum = penum.replace('pe', '')
                    self.add_parameter_estimate(os.path.join(self.feat_dir, 'stats', file), penum)

        # Find excursion sets (in a given feat directory we have one excursion set per contrast)
        for file in os.listdir(self.feat_dir):
            if file.startswith("thresh_zstat"):
                if file.endswith(".nii.gz"):
                    s = re.compile('zstat\d+')
                    zstatnum = s.search(file)
                    zstatnum = zstatnum.group()
                    statnum = zstatnum.replace('zstat', '')
                    self.add_contrast(statnum)
                    self.add_clusters_peaks(statnum)        

    # Add model fitting, residuals map
    def add_model_fitting(self):
        residuals_file = os.path.join(self.feat_dir, 'stats', 'sigmasquareds.nii.gz')
        design_matrix_file = open(os.path.join(self.feat_dir, 'design.mat'), 'r')
        design_matrix = np.loadtxt(design_matrix_file, skiprows=5, ndmin=2)

        self.nidm.create_model_fitting(residuals_file, design_matrix)

    # For a parameter estimate, create the parameter estimate map emtity
    def add_parameter_estimate(self, pe_file, pe_num):
        self.nidm.create_parameter_estimate(pe_file, pe_num)

    # For a given contrast, create the contrast map, contrast variance map, contrast and statistical map emtities
    def add_contrast(self, contrastNum):
        contrastFile = os.path.join(self.feat_dir, 'stats', 'cope'+str(contrastNum)+'.nii.gz')
        varContrastFile = os.path.join(self.feat_dir, 'stats', 'varcope'+str(contrastNum)+'.nii.gz')
        statMapFile = os.path.join(self.feat_dir, 'stats', 'tstat'+str(contrastNum)+'.nii.gz')
        zStatMapFile = os.path.join(self.feat_dir, 'stats', 'zstat'+str(contrastNum)+'.nii.gz')

        # designFile = open(os.path.join(self.feat_dir, 'design.con'), 'r')
        # designTxt = designFile.read()
        # # FIXME: to do only once (and not each time we load a new contrast)
        # contrastNameSearch = re.compile(r'.*/ContrastName'+str(contrastNum)+'\s+(?P<contrastName>[\w\s><]+)\s*[\n\r]')
        # extractedData = contrastNameSearch.search(designTxt) 

        designFile = open(os.path.join(self.feat_dir, 'design.fsf'), 'r')
        designTxt = designFile.read()
        contrastNameSearch = re.compile(r'.*set fmri\(conname_real\.'+contrastNum+'\) "(?P<contrastName>[\w\s><]+)".*')
        extractedDataNew = contrastNameSearch.search(designTxt) 

        contrastWeightSearch = re.compile(r'.*set fmri\(con_real'+contrastNum+'\.\d+\) (?P<contrastWeight>\d+)')
        contrastWeights = str(re.findall(contrastWeightSearch, designTxt)).replace("'", '')

        # FIXME: to do only once (and not each time we load a new contrast)
        dofFile = open(os.path.join(self.feat_dir, 'stats', 'dof'), 'r')
        dof = float(dofFile.read())

        self.nidm.create_contrast_map(contrastFile, varContrastFile, statMapFile, zStatMapFile,
            extractedDataNew.group('contrastName').strip(), contrastNum, dof, contrastWeights)

    # Create the search space entity generated by an inference activity
    def add_search_space(self):
        searchSpaceFile = os.path.join(self.feat_dir, 'mask.nii.gz')
        smoothnessFile = os.path.join(self.feat_dir, 'stats', 'smoothness')

        # Load DLH, VOLUME and RESELS
        smoothness = np.loadtxt(smoothnessFile, usecols=[1])
        self.nidm.create_search_space(searchSpaceFile=searchSpaceFile, searchVolume=int(smoothness[1]), reselSizeInVoxels=float(smoothness[2]), dlh=float(smoothness[0]))

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

        self.nidm.create_software(parser.get_feat_version())

    # Create excursion set, clusters and peaks entities
    def add_clusters_peaks(self, statNum):
        myClusterFile = os.path.join(self.feat_dir, 'cluster_zstat'+statNum+'.txt')

        visualisation = os.path.join(self.feat_dir, 'rendered_thresh_zstat'+statNum+'.png')

        # Excursion set
        zFileImg = myClusterFile.replace('cluster_', 'thresh_').replace('.txt', '.nii.gz')
        self.nidm.create_excursion_set(excusionSetFile=zFileImg, statNum=statNum, visualisation=visualisation)

        # Clusters



        self.zstatFile = myClusterFile
        clusterTable = np.loadtxt(myClusterFile, skiprows=1, ndmin=2)

        # # FIXME: could be nicer (do not repeat for std)
        # clusters = []
        # for row in clusterTable:
        #     print "cluster "+str(row[0])
        #     cluster = Cluster(int(row[0]))
        #     cluster.sizeInVoxels(int(row[1]))
        #     cluster.set_pFWER(float(row[2]))
        #     print row[8]
        #     cluster.set_COG1(float(row[8]))
        #     cluster.set_COG2(float(row[9]))
        #     cluster.set_COG3(float(row[10]))
        #     clusters.append(cluster)
            
        myStdZstatFile = myClusterFile.replace('.txt', '_std.txt')
        clusterStdTable = np.loadtxt(myStdZstatFile, skiprows=1, ndmin=2)
        # clustersStd = []
        # for row in clusterStdTable:
        #     print "cluster "+str(row[0])
        #     cluster = Cluster(int(row[0]))
        #     cluster.sizeInVoxels(int(row[1]))
        #     cluster.set_pFWER(float(row[2]))
        #     print row[8]
        #     cluster.set_COG1(float(row[8]))
        #     cluster.set_COG2(float(row[9]))
        #     cluster.set_COG3(float(row[10]))
        #     clustersStd.append(cluster)

        clustersJoinTable = np.column_stack((clusterTable, clusterStdTable))

        # Peaks
        peakTable = np.loadtxt(myClusterFile.replace('cluster', 'lmax'), skiprows=1, ndmin=2)
        # peaks = []

        # peakIndex = 1;
        # for row in peakTable:
        #     # FIXME: Find a more efficient command to find row number
        #     peak = Peak(peakIndex, int(row[0]))
        #     peak.set_equivZStat(float(row[1]))
        #     peak.set_x(int(row[2]))
        #     peak.set_y(int(row[3]))
        #     peak.set_z(int(row[4]))
        #     peaks.append(peak)
        #     peakIndex = peakIndex + 1;

        peakStdTable = np.loadtxt(myStdZstatFile.replace('cluster', 'lmax'), skiprows=1, ndmin=2)
        # peaksStd = []
        # peakIndex = 1;
        # for row in peakStdTable:
        #     peak = Peak(peakIndex, int(row[0]))
        #     peak.set_equivZStat(float(row[1]))
        #     peak.set_x(float(row[2]))
        #     peak.set_y(float(row[3]))
        #     peak.set_z(float(row[4]))
        #     peaksStd.append(peak)
        #     peakIndex = peakIndex + 1;
        peaksJoinTable = np.column_stack((peakTable, peakStdTable))

        for cluster_row in clustersJoinTable:               
            self.nidm.create_cluster(id=int(cluster_row[0]), size=int(cluster_row[1]), pFWER=float(cluster_row[2]),
                COG1=float(cluster_row[8]),COG2=float(cluster_row[9]),COG3=float(cluster_row[10]),
                COG1_std=float(cluster_row[24]),COG2_std=float(cluster_row[25]),COG3_std=float(cluster_row[26]),
                statNum=statNum)
        
        prevCluster = -1
        for peak_row in peaksJoinTable:    
            clusterId = int(peak_row[0])  
            if clusterId is not prevCluster:
                peakIndex = 1;

            self.nidm.create_peak(id=peakIndex, x=int(peak_row[2]), y=int(peak_row[3]), z=int(peak_row[4]), 
                std_x=float(peak_row[7]), std_y=float(peak_row[8]), std_z=float(peak_row[9]),
                equivZ=float(peak_row[1]), clusterId=clusterId, statNum=statNum)
            prevCluster = clusterId

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
                self.voxelPCorr = float(extractedData.group('pvalue'))
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
                    self.voxelThreshValue = float(extractedData.group('zvalue'))
                    self.voxelPCorr = None
                    self.voxelPUncorr = None
                    self.extentValue = None;
                    self.extentPCorr = float(extractedData.group('pvalue'));
                    self.extentPUncorr = None
                    # self.threshType = extractedData.group('threshtype')
                    self.foundIntro = True;
    def get_feat_version(self):
        return self.featVersion

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


