#!/usr/bin/env python
import os
import sys
import time
import subprocess
from optparse import OptionParser
from string import Template

import googleapiclient.discovery

import paramiko
from paramiko import client

import ruamel.yaml

import instance
import disk
from instance import wait_for_operation

class ssh:
    client = None

    def __init__(self, address, username, key_filename):
        # Let the user know we're connecting to the server
        print("Connecting to server.")
        # Create a new SSH client
        self.client = client.SSHClient()
        # The following line is required if you want the script to be able to access a server that's not yet in the known_hosts file
        self.client.set_missing_host_key_policy(client.AutoAddPolicy())
        # Make the connection
        self.client.connect(address, username=username, key_filename=key_filename, look_for_keys=False)

    def sendCommand(self, command, timeout=None):
        # Check if connection is made previously
        #ref: https://www.programcreek.com/python/example/7495/paramiko.SSHException
        #example 3
        if(self.client):
            status = 0
            try:
                t = self.client.exec_command(command, timeout)
            except paramiko.SSHException:
                status=1

            #NOTE: reverting to python2 method of utf-8 conversion
            std_out = unicode(t[1].read(), "utf-8") #str(t[1].read(), "utf-8")
            std_err = unicode(t[2].read(), "utf-8") #str(t[2].read(), "utf-8")
            t[0].close()
            t[1].close()
            t[2].close()
            return (status, std_out, std_err)

def checkConfig(chips_auto_config):
    """Does some basic checks on the config file
    INPUT config file parsed as a dictionary
    returns True if everything is ok
    otherwise exits!
    """
    required_fields = ["instance_name", "cores", "disk_size", 
                       "google_bucket_path", "samples", "metasheet"]
    optional_fields = ['chips_commit']

    missing = []
    for f in required_fields:
        if not f in chips_auto_config or not chips_auto_config[f]:
            missing.append(f)

    #check if the sample fastq/bam files are valid
    invalid_bucket_paths = []
    print("Checking the sample file paths...")
    samples = chips_auto_config['samples']
    for sample in samples:
        for f in samples[sample]:
            cmd = [ "gsutil", "ls", f]
            print(" ".join(cmd))
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, 
                                    stderr=subprocess.PIPE)
            (out, error) = proc.communicate()
            if proc.returncode != 0:
                #print("Error %s:" % proc.returncode)
                #print(out)
                print(error)
                invalid_bucket_paths.append(f)

    if invalid_bucket_paths:
        print("Some sample file bucket files are invalid or do not exist, please correct this.")
        for f in invalid_bucket_paths:
            print(f)
        sys.exit()

    #NOTE: can add additional checks like google_bucket_path is in the form
    #of 'gs://...' etc.  but this is a start

    if missing:
        print("ERROR: Please define these required params in the automator config file:\n%s" % ", ".join(missing))
        sys.exit()
    else:
        return True

def createInstanceDisk(compute, instance_config, disk_config, ssh_config, project, zone, disk_auto_del=True):
    #create a new instance
    print("Creating instance...")
    response = instance.create(compute, instance_config['name'], 
                               instance_config['image'], 
                               instance_config['machine_type'],
                               project,
                               instance_config['serviceAcct'], 
                               zone)
    instanceLink = response['targetLink']
    instanceId = response['targetId']
    print(instanceLink, instanceId)
    #try to get the instance ip address
    ip_addr = instance.get_instance_ip(compute, instanceId, project, zone)
    
    #create a new disk
    print("Creating disk...")
    response = disk.create(compute, disk_config['name'], disk_config['size'], 
                           project, zone)
    #print(response)

    #attach disk to instance
    print("Attaching disk...")
    response = disk.attach_disk(compute, instance_config['name'], 
                                disk_config['name'], project, zone)
    #print(response)


    #try to establish ssh connection:
    # wait 30 secs
    print("Establishing connection...")
    time.sleep(60)
    connection = ssh(ip_addr, ssh_config['user'], ssh_config['key'])
    #TEST connection
    #(status, stdin, stderr) = connection.sendCommand("ls /mnt")

    #SET the auto-delete flag for the newly created disk
    print("Setting disk auto-delete flag for disk %s" % disk_config['name'])
    #NOTE: using the instance.set_disk_auto_delete fn doesn't work
    #TRY manual call
    #NOTE: the attached disk is always going to be persistent-disk-1
    cmd = [ "gcloud", "compute", "instances", "set-disk-auto-delete", instance_config['name'], "--device-name", "persistent-disk-1", "--zone", zone]
    print(" ".join(cmd))
    proc = subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    (out, error) = proc.communicate()
    if proc.returncode != 0:
        print("Error %s:" % proc.returncode)
        #print(out)
        print(error)

    return (instanceId, ip_addr, connection)

def transferRawFiles_local(samples, ssh_conn):
    """Goes through each FILE associated with each sample and issues
    a cmd from the instance to download the file to /mnt/ssd/chips/data

    RETIRNS: a dictionary of samples with their new data paths
    """

    tmp = {}
    for sample in samples:
        for fq in samples[sample]:
            #add this to the samples dictionary
            if sample not in tmp:
                tmp[sample] = []
            # get the filename, e.g. XXX.fq.gz or XXX.bsm
            filename = fq.split("/")[-1]
            tmp[sample].append("data/%s" % filename)

            #HARDCODED location of where the data files are expected--
            #no trailing /
            dst = "/mnt/ssd/chips/data"

            #MAKE the data directory
            (status, stdin, stderr) = ssh_conn.sendCommand("mkdir -p %s" % dst)
            #Can't get gsutil to work, trying to hard-code the full path
            #cmd = " ".join([ "gsutil", "-m", "cp", fq, dst]) 
            cmd = " ".join([ "/snap/bin/gsutil", "-m", "cp", fq, dst])
            print(cmd)
            (status, stdin, stderr) = ssh_conn.sendCommand(cmd)
            if stderr:
                print(stderr)
            
    return tmp

def main():
    usage = "USAGE: %prog -c [chips_automator config yaml] -u [google account username, e.g. taing] -k [google account key path, i.e. ~/.ssh/google_cloud_enging"
    optparser = OptionParser(usage=usage)
    optparser.add_option("-c", "--config", help="instance name")
    optparser.add_option("-u", "--user", help="username")
    optparser.add_option("-k", "--key_file", help="key file path")
    (options, args) = optparser.parse_args(sys.argv)

    if not options.config or not os.path.exists(options.config):
        print("Error: missing or non-existent yaml configuration file")
        optparser.print_help()
        sys.exit(-1)

    if (not options.user or not options.key_file):
        print("ERROR: missing user or google key path")
        optparser.print_help()
        sys.exit(-1)

    # PARSE the yaml file
    config_f = open(options.config)
    config = ruamel.yaml.round_trip_load(config_f.read())
    config_f.close()

    #CHECK config
    checkConfig(config)

    #SET DEFAULTS
    _commit_str = "" if not "chips_commit" in config else config['wes_commit']
    _image = "chips" if not "image" in config else config['image']
    _project = "cidc-biofx" if not "project" in config else config['project']
    _service_account = "biofxvm@cidc-biofx.iam.gserviceaccount.com"
    _zone = "us-east1-b" if not "zone" in config else config['zone']
    #dictionary of machine types based on cores
    _machine_types = {'2': 'n1-highmem-2',
                      '4': 'n1-highmem-4',
                      '8': 'n1-highmem-8',
                      '16': 'n1-highmem-16',
                      '32': 'n1-highmem-32',
                      '64': 'n1-highmem-64',
                      '96': 'n1-highmem-96'}

    #SHOULD I error check these?
    #AUTO append "chips_auto_" to instance name
    instance_name = "-".join(['chips-auto', config['instance_name']])
    #AUTO name attached disk
    disk_name = "-".join([instance_name, 'disk'])
    disk_size = config['disk_size']

    #SET machine type (default to n1-standard-8 if the core count is undefined
    machine_type = "n1-standard-8"
    if 'cores' in config and str(config['cores']) in _machine_types:
        machine_type = _machine_types[str(config['cores'])]

    #The google bucket path is in the form of gs:// ...
    #The normal_bucket path is the google bucket path but without the gs://
    google_bucket_path = config['google_bucket_path']
    normal_bucket_path = google_bucket_path.replace("gs://","") #remove gsL//

    instance_config= {'name': instance_name, 
                      'image': _image, 
                      'machine_type': machine_type, 
                      'serviceAcct': _service_account}

    disk_config= {'name': disk_name, 
                  'size': disk_size}

    ssh_config= {'user': options.user, 
                 'key': options.key_file}

    #print(instance_config)
    #print(disk_config)
    #print(ssh_config)
    compute = googleapiclient.discovery.build('compute', 'v1')
    (instanceId, ip_addr, ssh_conn) = createInstanceDisk(compute, 
                                                         instance_config, 
                                                         disk_config, 
                                                         ssh_config, 
                                                         _project, 
                                                         _zone)

    print("Successfully created instance %s" % instance_config['name'])
    print("{instanceId: %s, ip_addr: %s, disk: %s}" % (instanceId, ip_addr, disk_config['name']))
#------------------------------------------------------------------------------
    #SETUP the instance, disk, and chips directory
    print("Setting up the attached disk...")
    (status, stdin, stderr) = ssh_conn.sendCommand("/home/taing/utils/chips_automator.sh %s %s" % (options.user, _commit_str))
    if stderr:
        print(stderr)
#------------------------------------------------------------------------------
    # transfer the data to the bucket directory
    print("Transferring raw files to the bucket...")
    tmp = transferRawFiles_local(config['samples'], ssh_conn)
#------------------------------------------------------------------------------
    # Write a config (.config.yaml) and a meta (.metasheet.csv) locally
    # then upload it to the instance
    # CONFIG.yaml
    print("Setting up the config.yaml...")
    # parse the chips.config.yaml template
    #NOTE: using the local version of the config
    chips_config_f = open('chips.config.yaml')
    chips_config = ruamel.yaml.round_trip_load(chips_config_f.read())
    chips_config_f.close()
    
    # SET the config to the samples dictionary we built up
    chips_config['samples'] = tmp

    ##set transfer path
    transfer_path = normal_bucket_path
    #check if transfer_path has gs:// in front
    if not transfer_path.startswith("gs://"):
        transfer_path = "gs://%s" % transfer_path

    if transfer_path.endswith("/"):
        chips_config['transfer_path'] = transfer_path
    else:
        chips_config['transfer_path'] = transfer_path + "/"
    ##print(chips_config)

    #WRITE this to hidden file .config.yaml
    print("Setting up the metasheet...")
    out = open(".config.yaml","w")
    #NOTE: this writes the comments for the metasheet as well, but ignore it
    ruamel.yaml.round_trip_dump(chips_config, out)
    out.close()

    # METASHEET.csv
    # write the metasheet to .metasheet.csv
    out = open(".metasheet.csv","w")
    out.write("RunName,Treat1,Cont1,Treat2,Cont2\n") #NOTE: IGNORING Treat2,Cont2 cols!
    for run in config['metasheet']:
        treat = config['metasheet'][run]['treat']
        cont = config['metasheet'][run]['cont']
        out.write("%s\n" % ','.join([run, treat, cont, "",""]))
    out.close()
#------------------------------------------------------------------------------
    #UPLOAD .config.yaml and .metasheet.csv
    #NOTE: we are skip checking .ssh/known_hosts
    #really should make this a fn
    for f in ['config.yaml', 'metasheet.csv']:
        cmd = ['scp', "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null", '-i', options.key_file, ".%s" % f, "%s@%s:%s%s" % (options.user, ip_addr, "/mnt/ssd/chips/", f)]
        print(" ".join(cmd))
        proc = subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        (out, error) = proc.communicate()
        if proc.returncode != 0:
            print("Error %s:" % proc.returncode)
            print(error)

    #RUN
    print("Running...")
    #NOTE: _project and _bucket_path are not needed for local runs
    (status, stdin, stderr) = ssh_conn.sendCommand("/home/taing/utils/chips_automator_run_local.sh %s %s %s" % (_project, normal_bucket_path, str(config['cores'])))
    if stderr:
        print(stderr)

    print("The instance is running at the following IP: %s" % ip_addr)
    print("please log into this instance and to check-in on the run")
if __name__=='__main__':
    main()
