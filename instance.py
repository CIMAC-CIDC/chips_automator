import os
import sys
import time
from optparse import OptionParser

import googleapiclient.discovery

###############################################################################
#STATICALLY including a template instance config
###############################################################################
config = {
    'name': "", #to be set
    'machineType': None, #to be set
    
    # Specify the boot disk and the image to use as a source.
    'disks': [
        {
            'boot': True,
            'autoDelete': True,
            'initializeParams': {
                'sourceImage': None,
            }
        }
    ],
    
    # Specify a network interface with NAT to access the public
    # internet.
    'networkInterfaces': [{
        'network': 'global/networks/default',
        'accessConfigs': [
            {'type': 'ONE_TO_ONE_NAT', 'name': 'External NAT'}
        ]
    }],

    # Allow the instance to access cloud storage and logging.
    'serviceAccounts': [{
        'email': '', #to be set
        'scopes': [
            'https://www.googleapis.com/auth/devstorage.read_write',
            'https://www.googleapis.com/auth/logging.write'
        ]
    }],

    # Metadata is readable from the instance and allows you to
    # pass configuration from deployment scripts to instances.
    'metadata': {
    }
}

def wait_for_operation(compute, project, zone, operation):
    """From google api tutorial, tries to block while performing a given
    operation"""
    print('Waiting for operation to finish...')
    while True:
        result = compute.zoneOperations().get(
            project=project,
            zone=zone,
            operation=operation).execute()

        if result['status'] == 'DONE':
            print("done.")
            if 'error' in result:
                raise Exception(result['error'])
            return result

        time.sleep(1)

def create(compute, instance_name, image, machine_type, project, serviceAcct, zone):
    """Given a XX, YYY...
    Tries to create an instance according to the given params using 
    googeapi methods"""

    #get latest image from image family
    image_response = compute.images().getFromFamily(project=project, 
                                                    family=image).execute()
    source_disk_image = image_response['selfLink']

    #set the machine type
    machineType = "zones/%s/machineTypes/%s" % (zone, machine_type)

    #set the config
    config['name'] = instance_name
    config['machineType'] = machineType
    config['disks'][0]['initializeParams']['sourceImage'] = source_disk_image
    config['serviceAccounts'][0]['email'] = serviceAcct
    #print(config)

    #create instance
    operation = compute.instances().insert(
        project=project,
        zone=zone,
        body=config).execute()
    wait_for_operation(compute, project, zone, operation['name'])
    #print(operation)
    return operation

def delete(compute, name, project, zone):
    #based on From google tutorial!
    operation = compute.instances().delete(
        project=project,
        zone=zone,
        instance=name).execute()
    wait_for_operation(compute, project, zone, operation['name'])
    #print(operation)
    return operation

def list_instances(compute, project, zone):
    result = compute.instances().list(project=project, zone=zone).execute()
    return result['items'] if 'items' in result else None

def get_instance(compute, instance_id, project, zone):
    result = compute.instances().get(project=project, zone=zone, instance=instance_id).execute()
    return result

def get_instance_from_name(compute, machine_name, project, zone):
    """Helper fn to wrap looking up the ID using the name
    may be costly b/c it calls a list all instances and then tries to pull out
    the target instance"""
    instance = None
    result = list_instances(compute, project, zone) #calling list_instances fn
    for (i,r) in enumerate(result):
        if r['name'] == machine_name:
            instance = r
    return instance
    
def get_instance_ip(compute, instance_id, project, zone):
    result = get_instance(compute, instance_id, project, zone)
    ip_addr = result['networkInterfaces'][0]['accessConfigs'][0]['natIP']
    return ip_addr

def get_instance_ip_from_name(compute, machine_name, project, zone):
    result = get_instance_from_name(compute, machine_name, project, zone)
    ip_addr = result['networkInterfaces'][0]['accessConfigs'][0]['natIP']
    return ip_addr

def get_disk_device_name(compute, instance_id, project, zone, disk_name):
    "Tries to find the disk's assigned device name"
    response = get_instance(compute, instance_id, project, zone)
    disks = response['disks'] #an array of dictionaries, key in on source field
    for d in disks:
        #check if last elm in source url == disk_name
        if d['source'].split("/")[-1] == disk_name:
            return d['deviceName']
    return None

#WARNING: THE FN below DOES NOT ACTUAKKY work--the call is correct but the 
# google api is broken!
def set_disk_auto_delete(compute, instance_name, project, zone, disk_dev_name, auto_del_flag=True):
    """GIVEN a compute resource, an instance_name, project, zone,
    disk_name, will set the auto_delete flag to the given val (default True)"""
    result = compute.instances().setDiskAutoDelete(project=project, zone=zone, instance=instance_name, autoDelete=auto_del_flag, deviceName=disk_dev_name)
    return result

def main():
    compute = googleapiclient.discovery.build('compute', 'v1')
    #TODO: update this!
    usage = "USAGE: %prog -n [instance name] -t [instance type (n1-highmem-96) -p [project (cidc-biofx)] -z [zone (us-east-1b]"
    optparser = OptionParser(usage=usage)
    optparser.add_option("-n", "--instance_name", help="instance name")
    optparser.add_option("-i", "--image", help="image family")
    optparser.add_option("-m", "--machine_type", default="n1-highmem-96", help="machine_type")
    optparser.add_option("-p", "--project", default="cidc-biofx", help="google project")
    optparser.add_option("-s", "--service_account", default="biofxvm@cidc-biofx.iam.gserviceaccount.com", help="service account (biofxvm@cidc-biofx.iam.gserviceaccount.com)")
    optparser.add_option("-z", "--zone", default="us-east1-b", help="zone")
    optparser.add_option("-c", "--create", action="store_true", default=False, help="create an instance")
    optparser.add_option("-d", "--delete", action="store_true", default=False, help="create an instance")
    (options, args) = optparser.parse_args(sys.argv)

    if not options.instance_name:
        print("ERROR: an unique instance name is required")
        optparser.print_help()
        sys.exit(-1)
    elif (not options.create and not options.delete) or (options.create and options.delete):
        print("ERROR: must specify whether to create or delete an instance")
        optparser.print_help()
        sys.exit(-1)
    elif options.create and not options.image:
        print("ERROR: an image family, e.g. 'wes' 'cidc_chips' is required")
        optparser.print_help()
        sys.exit(-1)



    if options.create:
        response = create(compute, options.instance_name, options.image, 
                          options.machine_type, options.project, 
                          options.service_account, options.zone)
        #NOTE: the instance link would be "response['targetLink']" or 
        print(response['targetId'], response['targetLink'])

    if options.delete:
        response = delete(compute, options.instance_name, options.project,
                          options.zone)
        print(response['targetId'], response['targetLink'])

if __name__=='__main__':
    main()
