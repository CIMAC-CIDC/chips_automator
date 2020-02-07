import os
import sys
import time
from optparse import OptionParser

import googleapiclient.discovery

from instance import wait_for_operation

def create(compute, disk_name, size, project="cidc-biofx", zone="us-east1-b"):
    """Given a XX, YYY...
    Tries to create an disk according to the given params using 
    googeapi methods"""

    disk_config = {'name': "", "sizeGb": "", "zone": ""}

    #set the config
    disk_config['name'] = disk_name
    disk_config['sizeGb'] = size
    disk_config['zone'] = zone
    #print(disk_config)

    #create disk
    operation = compute.disks().insert(
        project=project,
        zone=zone,
        body=disk_config).execute()
    wait_for_operation(compute, project, zone, operation['name'])
    #print(operation)
    return operation

def delete(compute, disk_name, project="cidc-biofx", zone="us-east1-b"):
    #based on From google tutorial!
    operation = compute.disks().delete(
        project=project,
        zone=zone,
        disk=disk_name).execute()
    wait_for_operation(compute, project, zone, operation['name'])
    #print(operation)
    return operation

def get_disk(comput, project, zone, disk_name):
    """Get the disk resource"""
    operation = compute.disks().get(
        project=project,
        zone=zone,
        disk=disk_name).execute()
    return operation

def attach_disk(compute, instance_name, disk_name, project="cidc-biofx", zone="us-east1-b"):

    #get the disk resource
    operation = compute.disks().get(
        project=project,
        zone=zone,
        disk=disk_name).execute()
    diskLink = operation['selfLink']
    attached_disk_body = {'source':diskLink}

    #attach disk
    operation = compute.instances().attachDisk(
        project=project,
        zone=zone,
        instance=instance_name,
        body=attached_disk_body).execute()
    wait_for_operation(compute, project, zone, operation['name'])
    #print(operation)
    return operation

#TODO:
def detach_disk(compute, instance_name, disk_name, project="cidc-biofx", zone="us-east1-b"):
    print("detach_disk is not implemented!")
    return
    # #get the disk resource
    # operation = compute.disks().get(
    #     project=project,
    #     zone=zone,
    #     disk=disk_name).execute()
    # #print(operation)
    # #sys.exit()
    # diskLink = operation['selfLink']

    # #attached_disk_body = {'source':diskLink}
    # attached_disk_body = {"source": "zones/%s/disks/%s" % (zone, disk_name)}

    # #attach disk
    # operation = compute.instances().detachDisk(
    #     project=project,
    #     zone=zone,
    #     instance=instance_name,
    #     #body=attached_disk_body).execute()
    #     deviceName='wes-auto-disk').execute()
    # wait_for_operation(compute, project, zone, operation['name'])
    # #print(operation)
    # return operation
    
def main():
    compute = googleapiclient.discovery.build('compute', 'v1')
    #TODO: update this!
    usage = "USAGE: %prog -n [disk name] -s [disk size in Gb] -z [zone (us-east-1b]"
    optparser = OptionParser(usage=usage)
    optparser.add_option("-n", "--disk_name", help="disk name")
    optparser.add_option("-s", "--size", help="disk size in Gb ")
    optparser.add_option("-p", "--project", default="cidc-biofx", help="google project")
    optparser.add_option("-z", "--zone", default="us-east1-b", help="zone")
    optparser.add_option("-c", "--create", action="store_true", default=False, help="create an instance")
    optparser.add_option("-d", "--delete", action="store_true", default=False, help="create an instance")

    (options, args) = optparser.parse_args(sys.argv)

    if not options.disk_name:
        print("ERROR: an unique instance name is required")
        optparser.print_help()
        sys.exit(-1)
    elif (not options.create and not options.delete) or (options.create and options.delete):
        print("ERROR: must specify whether to create or delete an instance")
        optparser.print_help()
        sys.exit(-1)
    elif options.create and not options.size:
        print("ERROR: an disk size is required")
        optparser.print_help()
        sys.exit(-1)


    if options.create:
        response = create(compute, options.disk_name, options.size, 
                          options.project, options.zone)
        #NOTE: the instance link would be "response['targetLink']" or 
        print(response['targetId'], response['targetLink'])

    if options.delete:
        response = delete(compute, options.disk_name, options.project,
                          options.zone)
        print(response['targetId'], response['targetLink'])

if __name__=='__main__':
    main()
