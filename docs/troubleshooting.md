# Troubleshooting

Common errors and how to resolve them.

---

## `terraform apply` Errors

### Error: Azure Monitor Agent extension provisioning failed

Example:

```
Error: creating/updating Virtual Machine Extension
Code="VMExtensionProvisioningError"
```

**Cause**: The extension image can't be reached, VM provisioning is still in progress, or the agent install script failed on first attempt.

**Diagnosis**:
```bash
# Show extension provisioning state
az vm extension list \
  --resource-group rg-vm-python \
  --vm-name vm-app-dev \
  --output table

# Get detailed extension status
az vm extension show \
  --resource-group rg-vm-python \
  --vm-name vm-app-dev \
  --name AzureMonitorLinuxAgent \
  --output json
```

**Fix**: Re-run `terraform apply`. If it still fails, verify outbound connectivity from the VM and check Azure regional service health. As a last resort, taint and recreate the VM:
```bash
cd terraform
terraform taint azurerm_linux_virtual_machine.app_vm
terraform apply
```

---

### Error: `ssh_public_key_path` file not found

```
Error: error reading SSH public key: open /Users/you/.ssh/id_rsa.pub: no such file or directory
```

**Cause**: The SSH key pair does not exist at the expected path.

**Fix**:
```bash
ssh-keygen -t rsa -b 4096 -f ~/.ssh/id_rsa -N ""
```
Or update `ssh_public_key_path` in `terraform/terraform.tfvars` to point to an existing key.

---

### Error: `app_repo_url` is required

```
Error: No value for required variable
  on variables.tf line N:
  │ var.app_repo_url
```

**Fix**: Add the variable to `terraform/terraform.tfvars`:

```hcl
app_repo_url = "https://github.com/<org>/<repo>.git"
```

Or pass it on the command line:

```bash
terraform plan -var="app_repo_url=https://github.com/<org>/<repo>.git"
```

---

### Error: Azure authorization / subscription

```
Error: building AzureRM Client: obtain subscription(…): …
```

**Fix**: Re-authenticate and confirm the correct subscription is active:

```bash
az login
az account set --subscription "<id>"
```

---

### Error: `null_resource.wait_for_app` SSH timeout

```
Error: timeout - last error: SSH authentication failed
```

**Cause**: Either the VM is still booting, the NSG is blocking port 22, or the SSH private key does not match the public key used to create the VM.

**Diagnosis**:
```bash
# Check if port 22 is reachable
nc -zv <public_ip> 22

# Check the NSG effective rules
az network nic show-effective-nsg \
  --resource-group rg-vm-python \
  --name nic-app-dev \
  --query "effectiveNetworkSecurityGroups[].securityRules" \
  --output table
```

**Fix**: Ensure `ssh_private_key_path` matches `ssh_public_key_path`. If the NSG is blocking SSH, check `ssh_allowed_cidr` — it may need to be broadened temporarily.

---

## cloud-init Failures

### `cloud-init status` reports `error`

SSH into the VM and inspect the full log:

```bash
make ssh
sudo cat /var/log/cloud-init-output.log
```

Common causes:

| Symptom | Cause | Fix |
|---------|-------|-----|
| `git clone` exits non-zero | Repo URL wrong or not accessible | Verify `app_repo_url`; check network/firewall |
| `pip install` fails | Bad `requirements.txt` | Test locally: `pip install -r app/requirements.txt` |
| `systemctl start app` fails | App crashes on startup | See [app startup failures](#app-startup-failures) |
| Package install fails | VM can't reach apt mirrors | Check outbound NSG rules; wait and retry |

To re-run cloud-init after fixing the issue, taint the VM and re-apply:

```bash
terraform taint azurerm_linux_virtual_machine.app_vm
make apply-auto
```

---

## App Startup Failures

### `systemctl status app` shows `failed` or `activating`

```bash
# SSH into the VM
make ssh

# Check the full service status
sudo systemctl status app --no-pager -l

# View the last 50 lines of the app journal
sudo journalctl -u app -n 50 --no-pager
```

Common causes:

| Error in logs | Cause | Fix |
|--------------|-------|-----|
| `ModuleNotFoundError` | Dependency not in `requirements.txt` | Add missing package, redeploy |
| `Address already in use` | Port conflict | Confirm `app_port` is not in use; restart |
| `EnvironmentFile not found` | `/opt/app/.env` missing | Check cloud-init log; file should be created in `runcmd` |
| `Permission denied` | File ownership issue | Run `sudo chown -R appuser:appuser /opt/app` |
| App exits immediately | Unhandled exception on startup | Run the app manually to see the traceback |

Run the app manually to see startup errors:

```bash
sudo -u appuser /opt/app/.venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000
```

---

## nginx Issues

### Port 80 returns `502 Bad Gateway`

The nginx reverse proxy is running but the app is not.

```bash
# Check app status
sudo systemctl status app

# Restart the app, then nginx
sudo systemctl restart app
sudo systemctl restart nginx
```

### nginx fails to start

```bash
sudo nginx -t          # test config
sudo journalctl -u nginx -n 30 --no-pager
```

Check `/etc/nginx/sites-enabled/app` for syntax errors.

---

## Terraform State Issues

### State drift (resource changed outside Terraform)

```bash
cd terraform && terraform refresh
terraform plan   # review the diff before applying
```

### State lock stuck

```bash
cd terraform && terraform force-unlock <lock-id>
```

---

## Azure Resource Quota / Limit Errors

```
Error: compute.VirtualMachinesClient#CreateOrUpdate:
  Code="OperationNotAllowed" Message="Operation could not be completed
  as it results in exceeding approved Total Regional vCPUs quota"
```

**Fix**: Request a quota increase in the Azure portal, or use a smaller VM SKU:

```hcl
vm_size = "Standard_B1s"  # 1 vCPU — free-tier eligible
```

---

## Useful Diagnostic Commands

```bash
# List all resources in the resource group
az resource list --resource-group rg-vm-python --output table

# View VM boot diagnostics (serial console output)
az vm boot-diagnostics get-boot-log \
  --resource-group rg-vm-python \
  --name vm-app-dev

# Check cloud-init status remotely
make ssh -- cloud-init status --long

# Stream app logs from your local terminal
make logs
```
