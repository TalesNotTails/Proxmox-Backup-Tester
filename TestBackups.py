import os
import re
import csv
import time
import proxmoxer
from smtplib import SMTP
from datetime import datetime
from proxmoxer.tools import Tasks
from collections import defaultdict

# Email Libraries
from email import encoders
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# added to suppress insecure request warning
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def send_report(attachment_path):

    email_vars = [
        'SMTP_SERVER',
        'SENDER',
        'DESTINATION'
    ]

    email_config = {var: os.getenv(var, 'Not Set') for var in email_vars}

    content = """\
    The backup testing script has finished running. Attached are the results    
    """

    msg = MIMEMultipart()
    msg['Subject'] = 'Backup Test Results'
    msg['From'] = email_config['SENDER']
    msg['To'] = email_config['DESTINATION']

    msg.attach(MIMEText(content, 'plain'))

    # Attach file
    with open(attachment_path, 'rb') as attachment:
        part = MIMEBase('application', 'octet-stream')
        part.set_payload(attachment.read())

    # Encode file in ASCII characters to send by email
    encoders.encode_base64(part)

    # Add header as key:value pair to attachment part
    part.add_header('Content-Disposition', f'attachment; filename= {attachment_path}')

    # Attach the attachment to the MIMEMultipart object
    msg.attach(part)

    with SMTP(email_config['SMTP_SERVER']) as server:
        server.sendmail(email_config['SENDER'], email_config['DESTINATION'], msg.as_string())
        print('Email sent')


# Function to extract the date and find the backup with the latest date
def find_latest_backup(strings):
    date_pattern = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
    latest_backup = None
    latest_backup_string = None

    for string in strings:
        match = date_pattern.search(string)

        if match:
            date_str = '-'.join(match.groups())
            date_obj = datetime.strptime(date_str, "%Y-%m-%d")

            # Comparing to find the latest date
            if latest_backup is None or date_obj > latest_backup:
                latest_backup = date_obj
                latest_backup_string = string

    return latest_backup_string


def restore_resource(volid, temp_vmid, proxmox, proxmox_config):
    try:
        proxmox.nodes(proxmox_config['RECOVERY_NODE']).qemu.post(
            node=proxmox_config['RECOVERY_NODE'],
            vmid=temp_vmid,
            archive=volid,
            # To-Do: make restore storage implementation specific/variable
            storage="local-zfs",
            net0="model=virtio,link_down=1",
            cores=2,
            start=1
        )

    except Exception as e:
        print(e)
        return False

    # Find task for restore and wait on it
    for task in proxmox.cluster.tasks.get():
        print(task)
        if task.get('type') == 'qmrestore' and task.get('status') is None:
            Tasks.blocking_status(proxmox, task.get('upid'), timeout=6000)
            break

    while True:
        # Find task for start and fail if not in regular state
        for task in proxmox.cluster.tasks.get():
            if task.get('type') == 'qmstart' and task.get('status') not in ['started', 'stopped']:
                return False
            elif task.get('type') == 'qmstart' and task.get('status') == 'started':
                time.sleep(10)
                break
            else:
                return True


def stop_resource(temp_vmid, proxmox, proxmox_config):
    try:
        proxmox.nodes(proxmox_config['RECOVERY_NODE']).qemu(temp_vmid).status.stop.post(
            node=proxmox_config['RECOVERY_NODE'],
            vmid=temp_vmid,
            skiplock=1
        )
    except Exception as e:
        print(e)

    # Keep checking vm status until stopped
    while True:
        status = proxmox.nodes(proxmox_config['RECOVERY_NODE']).qemu(temp_vmid).status.current.get(
            node=proxmox_config['RECOVERY_NODE'],
            vmid=temp_vmid
        )

        if status.get('status') == 'stopped':
            break

        time.sleep(10)


def destroy_resource(temp_vmid, proxmox, proxmox_config):
    proxmox.nodes(proxmox_config['RECOVERY_NODE']).qemu(temp_vmid).delete(
        node=proxmox_config['RECOVERY_NODE'],
        vmid=temp_vmid,
        skiplock=1,
        purge=1
    )

    print("destroyed vm")


def test_agent(temp_vmid, proxmox, proxmox_config):
    result = None
    for i in range(10):
        time.sleep(30)
        try:
            result = proxmox.nodes(proxmox_config['RECOVERY_NODE']).qemu(temp_vmid).agent.post(
                node=proxmox_config['RECOVERY_NODE'],
                vmid=temp_vmid,
                command="get-osinfo"
            )

            break
        except proxmoxer.core.ResourceException as e:
            print(f'{e} {i}')

    if result is None:
        return False
    else:
        return True


# Get the next available vmid to use for restoring vms to
def get_free_vmid(proxmox, proxmox_config):
    lxc_list = proxmox.nodes(proxmox_config['RECOVERY_NODE']).lxc.get()
    qemu_list = proxmox.nodes(proxmox_config['RECOVERY_NODE']).qemu.get()

    vmid_list = []

    for res in lxc_list:
        vmid_list.append(int(res['vmid']))

    for res in qemu_list:
        vmid_list.append(int(res['vmid']))

    if 100 not in vmid_list:
        return 100

    vmid_list.sort()

    for i in range(len(vmid_list) - 1):
        if vmid_list[i + 1] - vmid_list[i] > 1:
            return vmid_list[i] + 1

    return vmid_list[-1] + 1


def main():
    results = []
    restore_list = []
    grouped_backups = defaultdict(list)

    #
    proxmox_vars = [
        'REALM',
        'PROXMOX_USERNAME',
        'PROXMOX_PASSWORD',
        'RECOVERY_NODE_FQDN',
        'STORAGE_NAME'
    ]

    proxmox_config = {var: os.getenv(var, 'Not Set') for var in proxmox_vars}

    proxmox_config['RECOVERY_NODE'] = proxmox_config['RECOVERY_NODE_FQDN'].split('.')[0]

    proxmox = proxmoxer.ProxmoxAPI(
        proxmox_config['RECOVERY_NODE_FQDN'],
        user=f"{proxmox_config['PROXMOX_USERNAME']}@{proxmox_config['REALM']}",
        password=proxmox_config['PROXMOX_PASSWORD'],
        verify_ssl=False,
        timeout=60
    )

    free_vmid = get_free_vmid(proxmox, proxmox_config)

    # Get all VMs backups for selected storage
    # Stores all volids in a dictionary where the vmid is the key
    for backup in proxmox.nodes(proxmox_config['RECOVERY_NODE']).storage(proxmox_config['STORAGE_NAME']).content.get():
        if backup.get('vmid') is not None and 'lxc' not in backup.get('volid'):
            grouped_backups[backup.get('vmid')].append(backup['volid'])

    # Unpack and get the latest backup for the vmid
    # Store all the latest backups in a list to be tested
    for vmid, backups in grouped_backups.items():
        latest_volid = find_latest_backup(backups)
        restore_list.append(latest_volid)

    # Test all backups in restore list
    for resource in restore_list:
        res_record = []

        # Gets info from storage about current backup
        res_info = proxmox.nodes(proxmox_config['RECOVERY_NODE']).storage(proxmox_config['STORAGE_NAME']).content(
            resource).get(node=proxmox_config['RECOVERY_NODE'],volume=resource)

        # Sets name of vm in report
        # Assumes VM name is in backup notes
        res_record.append(res_info.get('notes'))

        print(f'Restoring {res_info.get("notes")}')
        start = time.perf_counter()

        # Set path if restore and start is successful
        if restore_resource(resource, free_vmid, proxmox, proxmox_config):
            stop = time.perf_counter()
            res_record.append('Success')
            print(f'Successfully restored {res_info.get("notes")}')

            # Test guest agent. If not able to, determine why
            if test_agent(free_vmid, proxmox, proxmox_config):
                print(f'Successfully tested guest agent for: {res_info.get("notes")}')
                res_record.append('Success')
            else:
                res_record.append('Failure')
                res_status = proxmox.nodes(proxmox_config['RECOVERY_NODE']).qemu(free_vmid).status.current.get(
                    node=proxmox_config['RECOVERY_NODE'],
                    vmid=free_vmid
                )
                if res_status.get('status') == 'stopped':
                    print(f'Proxmox failed to start: {res_info.get("notes")}')
                elif res_status.get('status') == 'running':
                    print(f'Guest agent not running on: {res_info.get("notes")}')
                else:
                    print(f'Failed to test guest agent for: {res_info.get("notes")}')

            results.append(res_record)

            stop_resource(free_vmid, proxmox, proxmox_config)

            destroy_resource(free_vmid, proxmox, proxmox_config)

            time.sleep(30)
        # Set path if restore or start was unsuccessful
        else:
            stop = time.perf_counter()
            res_record.append('Failure')
            res_record.append('N/A')
            print(f'Failed to restore {res_info.get("notes")}')
            stop_resource(free_vmid, proxmox, proxmox_config)
            destroy_resource(free_vmid, proxmox, proxmox_config)

        # Calculate total restore time in minutes
        time_minutes = (stop - start) / 60

        res_record.append(f'{round(time_minutes)} minutes')

        print(res_record)

    with open('out.csv', 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['name', 'recover_result', 'guest_agent_result', 'time_to_restore'])
        writer.writerows(results)

    # Email report
    send_report('out.csv')

    # Clean up files
    os.remove('out.csv')


if __name__ == "__main__":
    main()
