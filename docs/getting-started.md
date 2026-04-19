# Getting Started

This guide walks you through provisioning the Azure infrastructure and deploying your Python application from scratch.

---

## 1. Prerequisites

### Tools

Install these on your local machine before continuing.

**Terraform ≥ 1.7**

```bash
brew install terraform           # macOS
# or download from https://developer.hashicorp.com/terraform/downloads
terraform -version
```

**Azure CLI ≥ 2.60**

```bash
brew install azure-cli           # macOS
az --version
```

**SSH key pair**

```bash
# Generate a key pair if you don't have one
ssh-keygen -t rsa -b 4096 -C "azure-vm" -f ~/.ssh/id_rsa

# Confirm both files exist
ls ~/.ssh/id_rsa ~/.ssh/id_rsa.pub
```

---

## 2. Authenticate to Azure

```bash
az login
```

If you work in multiple subscriptions, set the target explicitly:

```bash
az account list --output table
az account set --subscription "<subscription-id-or-name>"
```

Verify the correct subscription is active:

```bash
az account show --query "{name:name, id:id}" --output table
```

### CI / non-interactive environments

Export service principal credentials instead of running `az login`:

```bash
export ARM_CLIENT_ID="<client-id>"
export ARM_CLIENT_SECRET="<client-secret>"
export ARM_TENANT_ID="<tenant-id>"
export ARM_SUBSCRIPTION_ID="<subscription-id>"
```

---

## 3. Configure Variables

Open `terraform/terraform.tfvars` and set the required value:

```hcl
# Required — your Python app's Git repository URL
app_repo_url = "https://github.com/<org>/<repo>.git"
```

Recommended changes for production:

```hcl
environment      = "prod"
vm_size          = "Standard_B4ms"       # larger SKU
ssh_allowed_cidr = "1.2.3.4/32"          # your public IP only
```

> If your repository is private, add a deploy key to GitHub/Azure Repos and supply the SSH clone URL.
> See the [private repo section](#private-repositories) below.

---

## 4. Initialise Terraform

```bash
make init
# equivalent: cd terraform && terraform init
```

This downloads the AzureRM and Null providers and creates `.terraform/` locally.

---

## 5. Preview the Plan

```bash
make plan
# equivalent: cd terraform && terraform plan -out=tfplan
```

Review the output. You should see approximately **7 resources** to be created:

| # | Resource |
|---|---------|
| 1 | `azurerm_resource_group.main` |
| 2 | `azurerm_virtual_network.main` |
| 3 | `azurerm_subnet.app` |
| 4 | `azurerm_network_security_group.app` |
| 5 | `azurerm_subnet_network_security_group_association.app` |
| 6 | `azurerm_public_ip.app` |
| 7 | `azurerm_network_interface.app` |
| 8 | `azurerm_linux_virtual_machine.app_vm` |
| 9 | `null_resource.wait_for_app` |

---

## 6. Apply (Provision + Deploy)

```bash
make apply
# equivalent: cd terraform && terraform apply tfplan
```

What happens during `terraform apply`:

1. All Azure resources are created in order.
2. The VM starts up; Azure injects the rendered cloud-init script as `custom_data`.
3. cloud-init runs on first boot (takes 3–8 minutes):
   - Upgrades packages
   - Installs Python 3.11, git, nginx
   - Creates `appuser` system user
   - Clones your repository to `/opt/app`
   - Creates a virtualenv and installs `requirements.txt`
   - Writes and enables the `app.service` systemd unit
   - Configures nginx as a reverse proxy on port 80
4. The `null_resource.wait_for_app` SSHes in and runs `cloud-init status --wait`.
5. Once cloud-init exits successfully and `systemctl is-active app` confirms the service is running, `terraform apply` completes.

Expected terminal output at the end:

```
null_resource.wait_for_app (remote-exec): ✓ app service is active
null_resource.wait_for_app: Creation complete

Apply complete! Resources: 9 added.

Outputs:
  app_url     = "http://20.1.2.3:8000"
  ssh_command = "ssh azureuser@20.1.2.3"
  vm_public_ip = "20.1.2.3"
```

---

## 7. Verify the Application

```bash
# Check the app URL from Terraform output
make output

# Hit the health endpoint
curl http://$(cd terraform && terraform output -raw vm_public_ip):8000/health
# → {"status":"healthy"}

# Hit the root endpoint
curl http://$(cd terraform && terraform output -raw vm_public_ip):8000/
# → {"app":"azure-vm-python","version":"1.0.0","environment":"dev", ...}
```

Or open `http://<public_ip>:8000/docs` in a browser for the Swagger UI.

---

## 8. SSH Access

```bash
make ssh
# equivalent: ssh -i ~/.ssh/id_rsa azureuser@<public_ip>
```

Useful commands once inside:

```bash
# Check app service status
sudo systemctl status app

# Stream live logs
journalctl -u app -f

# View the cloud-init bootstrap log
sudo cat /var/log/cloud-init-output.log

# Check nginx status
sudo systemctl status nginx
```

---

## Private Repositories

If your app repository requires authentication:

1. **Generate a deploy key on the VM** (or create one locally and add it to GitHub):

   ```bash
   ssh-keygen -t ed25519 -C "deploy-key" -f deploy_key -N ""
   ```

2. Add the **public key** (`deploy_key.pub`) as a read-only deploy key in your repo settings.

3. Pass the **private key** to the VM via an additional `write_files` entry in `scripts/cloud-init.yaml`:

   ```yaml
   write_files:
     - path: /home/appuser/.ssh/id_ed25519
       permissions: "0600"
       owner: appuser:appuser
       content: |
         <paste private key here>
   ```

4. Change the `git clone` line to use the SSH URL:

   ```yaml
   runcmd:
     - git clone git@github.com:<org>/<repo>.git /opt/app
   ```

> For production, store the key in Azure Key Vault and retrieve it during cloud-init instead of embedding it in the template.

---

## Destroying Resources

```bash
make destroy
```

This destroys **all** Azure resources in the resource group. There is a 5-second pause before it runs.

---

## Next Steps

- [Code-Only Updates](code-only-updates.md) — update the app without reprovisioning
- [Troubleshooting](troubleshooting.md) — fix common errors
