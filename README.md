# Python Script: TestBackups.py

This script is used to test backups in a Proxmox environment. It performs several operations such as restoring resources, stopping resources, destroying resources, and testing agents. It also sends an email report of the test results.

## Libraries Used

- os
- re
- csv
- time
- proxmoxer
- smtplib
- datetime
- collections
- email
- urllib3

## Environment Variables

The script requires the following environment variables to be set:

- `SMTP_SERVER`: The SMTP server to use for sending emails.
- `SENDER`: The email address to send the report from.
- `DESTINATION`: The email address to send the report to.
- `REALM`: The realm for the Proxmox environment.
- `PROXMOX_USERNAME`: The username for the Proxmox environment.
- `PROXMOX_PASSWORD`: The password for the Proxmox environment.
- `RECOVERY_NODE_FQDN`: The fully qualified domain name of the recovery node in the Proxmox environment.
- `STORAGE_NAME`: The name of the storage in the Proxmox environment.

## Functions

1. `send_report(attachment_path)`: This function sends an email report with the results of the backup testing script.

2. `find_latest_backup(strings)`: This function extracts the date and finds the backup with the latest date.

3. `restore_resource(volid, temp_vmid, proxmox, proxmox_config)`: This function restores a resource in the Proxmox environment.

4. `stop_resource(temp_vmid, proxmox, proxmox_config)`: This function stops a resource in the Proxmox environment.

5. `destroy_resource(temp_vmid, proxmox, proxmox_config)`: This function destroys a resource in the Proxmox environment.

6. `test_agent(temp_vmid, proxmox, proxmox_config)`: This function tests the agent of a resource in the Proxmox environment.

7. `get_free_vmid(proxmox, proxmox_config)`: This function gets the next available vmid to use for restoring VMs.

8. `main()`: This is the main function that orchestrates the execution of the script.

## Execution

To execute the script, run the following command:

```bash
python3 TestBackups.py
```

## To-Do

- Implement dynamic time conversion(time to restore)
- Allow for list of attatched storages
- Account for long running restores(Not just having a long timeout)

