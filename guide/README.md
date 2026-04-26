# Setup and Configuration Guide

End-to-end guide for provisioning, configuring, and operating the Azure VM infrastructure and Python application.

---

## What This Project Does

Running `terraform apply` provisions a complete Azure environment and leaves your Python application **live and healthy** before the command exits — no manual post-apply steps required.

```
terraform apply
  ├── Azure resources (RG, VNet, NSG, Public IP, NIC, VM)
  ├── Azure Monitor Agent extension installed on the VM
  ├── cloud-init bootstraps the VM on first boot:
  │     installs Python 3, git, nginx
  │     clones your repo → /opt/app
  │     creates a virtualenv, installs requirements.txt
  │     writes and starts systemd units for app + generators
  │     configures nginx as reverse proxy on port 80
  └── null_resource SSHes in, waits for cloud-init, confirms services active
      → terraform apply exits ✓
      → app live at http://<public_ip>:8000
      → nginx proxy live at http://<public_ip>:80
```

For a full component diagram and infrastructure breakdown see [architecture.md](architecture.md).

---

## Guide Index

| Guide | What it covers |
|-------|----------------|
| This file | Prerequisites, authentication, tfvars setup, security |
| [deploy.md](deploy.md) | First-time provisioning, app updates, rollback, environment promotion |
| [architecture.md](architecture.md) | All Azure resources, bootstrap flow, systemd units, network layout |
| [configuration-reference.md](configuration-reference.md) | Every Terraform variable with type, default, valid values, and examples |
| [remote-state.md](remote-state.md) | Storing Terraform state in Azure Blob Storage for team or CI use |

---

## 1. Prerequisites

### Tools

| Tool | Minimum version | Install |
|------|----------------|---------|
| Terraform | 1.7 | `brew install terraform` or [hashicorp.com](https://developer.hashicorp.com/terraform/downloads) |
| Azure CLI | 2.60 | `brew install azure-cli` |
| GNU Make | any | pre-installed on macOS/Linux |
| SSH client | any | pre-installed on macOS/Linux |

Verify:

```bash
terraform -version    # Terraform v1.7.x or higher
az --version          # azure-cli 2.60.x or higher
```

### SSH Key Pair

Terraform uses your SSH public key to authorise access to the VM, and your private key to verify that cloud-init finished successfully.

```bash
# Generate a key pair if you don't have one
ssh-keygen -t rsa -b 4096 -C "azure-vm" -f ~/.ssh/id_rsa

# Confirm both files exist
ls ~/.ssh/id_rsa ~/.ssh/id_rsa.pub
```

If you use a different path, override `ssh_public_key_path` and `ssh_private_key_path` in `terraform.tfvars` (see [configuration-reference.md](configuration-reference.md)).

---

## 2. Authenticate to Azure

```bash
az login
```

For multiple subscriptions, target the right one explicitly:

```bash
# List subscriptions
az account list --output table

# Set the target subscription
az account set --subscription "<subscription-id-or-name>"

# Confirm
az account show --query "{name:name, id:id}" --output table
```

### Non-interactive / CI environments

For CI pipelines or any context where `az login` is not available, create a **service principal** and export its credentials as environment variables.

#### Step 1 — Find your Subscription ID

```bash
az account show --query "{name:name, id:id}" --output table
```

Note the `id` value — you will need it in the next step.

#### Step 2 — Create a Service Principal

This command creates a service principal named `azure-vm-deploy` and grants it **Contributor** access on your subscription. It prints `client_id`, `client_secret`, and `tenant_id` in one shot.

```bash
az ad sp create-for-rbac \
  --name "azure-vm-deploy" \
  --role Contributor \
  --scopes "/subscriptions/<subscription-id>" \
  --sdk-auth
```

Example output:

```json
{
  "clientId":       "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "clientSecret":   "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "subscriptionId": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "tenantId":       "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
}
```

> `clientSecret` is only shown once. Copy it immediately — it cannot be retrieved later.

If you prefer a narrower scope (only the resource group this project will create), run the command **after** the resource group exists:

```bash
az ad sp create-for-rbac \
  --name "azure-vm-deploy" \
  --role Contributor \
  --scopes "/subscriptions/<subscription-id>/resourceGroups/rg-vm-python"
```

#### Step 3 — Retrieve values at any time

If you need to look up the IDs later (the secret cannot be recovered, only rotated):

```bash
# List all service principals by display name
az ad sp list --display-name "azure-vm-deploy" --query "[].{appId:appId, displayName:displayName}" --output table

# Get your Tenant ID
az account show --query tenantId --output tsv

# Get your Subscription ID
az account show --query id --output tsv
```

#### Step 4 — Rotate the secret (when needed)

```bash
# List existing credentials for the service principal
az ad sp credential list --id "<client-id>" --output table

# Add a new secret (valid for 1 year by default)
az ad sp credential reset \
  --id "<client-id>" \
  --years 1 \
  --query "{clientSecret:password}"
```

#### Step 5 — Export for local use

```bash
export ARM_CLIENT_ID="<clientId>"
export ARM_CLIENT_SECRET="<clientSecret>"
export ARM_TENANT_ID="<tenantId>"
export ARM_SUBSCRIPTION_ID="<subscriptionId>"
```

Terraform and the AzureRM provider pick these up automatically — no change to `terraform.tfvars` needed.

To make these permanent in your shell session, add them to `~/.zshrc` or `~/.bashrc` (for personal dev machines only — never commit secrets to version control).

See the [GitHub Actions CI/CD Setup section](#9-github-actions-cicd-setup) for storing these as repository secrets.

---

## 3. Clone and Configure

```bash
git clone <this-repo> && cd azure_vm_gen_infra
```

### Create terraform.tfvars

`terraform/terraform.tfvars` is gitignored. Create it from scratch:

```bash
cp /dev/null terraform/terraform.tfvars   # or just create the file
```

**Minimal configuration** (one required variable):

```hcl
app_repo_url = "https://github.com/<org>/<repo>.git"
```

**Recommended configuration for development:**

```hcl
# Required
app_repo_url = "https://github.com/<org>/<repo>.git"

# Identity
resource_group_name = "rg-vm-python-dev"
environment         = "dev"
location            = "canadaeast"

# Security — restrict SSH to your current IP
ssh_allowed_cidr = "YOUR_PUBLIC_IP/32"   # curl ifconfig.me
```

**Recommended configuration for production:**

```hcl
# Required
app_repo_url = "https://github.com/<org>/<repo>.git"

# Identity
resource_group_name = "rg-vm-python-prod"
environment         = "prod"
location            = "canadaeast"

# Machine
vm_size        = "Standard_B4ms"
os_disk_size_gb = 64

# Security
ssh_allowed_cidr = "10.0.0.0/8"   # VPN/bastion CIDR only

# App
app_port = 8000

# Generator tuning
restocking_dtrs_per_batch = 5
restocking_fail_rate      = 0.02
job_hold_ticks            = 3
job_no_change_prob        = 0.50
```

All available variables are documented in [configuration-reference.md](configuration-reference.md).

---

## 4. Initialise Terraform

Downloads the AzureRM (`~> 3.110`) and Null (`~> 3.2`) providers into `.terraform/`.

```bash
make init
# equivalent: cd terraform && terraform init
```

Expected output:

```
Terraform has been successfully initialized!
```

If you are using a remote backend, run `make init` after configuring it — see [remote-state.md](remote-state.md).

---

## 5. Plan and Apply

### Preview the plan

```bash
make plan
# equivalent: cd terraform && terraform plan -out=tfplan
```

You should see **10 resources to create**:

| # | Resource type | Name |
|---|--------------|------|
| 1 | `azurerm_resource_group` | `rg-vm-python` |
| 2 | `azurerm_virtual_network` | `vnet-app-<env>` |
| 3 | `azurerm_subnet` | `snet-app-<env>` |
| 4 | `azurerm_network_security_group` | `nsg-app-<env>` |
| 5 | `azurerm_subnet_network_security_group_association` | — |
| 6 | `azurerm_public_ip` | `pip-app-<env>` |
| 7 | `azurerm_network_interface` | `nic-app-<env>` |
| 8 | `azurerm_linux_virtual_machine` | `vm-app-<env>` |
| 9 | `azurerm_virtual_machine_extension` | `AzureMonitorLinuxAgent` |
| 10 | `null_resource` | `wait_for_app` |

### Provision

```bash
make apply
# equivalent: cd terraform && terraform apply tfplan
```

Apply takes **5–12 minutes** on first run (the VM boots and cloud-init completes). The terminal will stream progress as the `null_resource` waits for the app to become active.

Expected successful output:

```
null_resource.wait_for_app (remote-exec): ✓ app service is active
null_resource.wait_for_app (remote-exec): ✓ restocking-generator.timer is active
null_resource.wait_for_app (remote-exec): ✓ job-status-generator.timer is active
null_resource.wait_for_app: Creation complete

Apply complete! Resources: 10 added, 0 changed, 0 destroyed.

Outputs:
  app_url      = "http://20.1.2.3:8000"
  ssh_command  = "ssh azureuser@20.1.2.3"
  vm_public_ip = "20.1.2.3"
```

---

## 6. Verify

```bash
# Print all Terraform outputs (IP, URL, SSH command)
make output

# Hit the health endpoint
curl http://$(cd terraform && terraform output -raw vm_public_ip):8000/health
# → {"status":"healthy"}

# Hit the root endpoint
curl http://$(cd terraform && terraform output -raw vm_public_ip):8000/
# → {"app":"azure-vm-python","version":"1.0.0","environment":"dev",...}
```

Open `http://<public_ip>:8000/docs` in a browser for the Swagger UI.

### Verify via nginx (port 80)

nginx is configured as a reverse proxy on port 80. Test it:

```bash
curl http://$(cd terraform && terraform output -raw vm_public_ip)/health
# → {"status":"healthy"}
```

### Verify generator services

```bash
make ssh

# On the VM
sudo systemctl status restocking-generator.timer
sudo systemctl status job-status-generator.timer

# Check generator output
ls -lh /var/restocking/inbound/
ls -lh /var/jobs/
cat /var/jobs/status.json
```

---

## 7. SSH and Logs

```bash
# Open an interactive SSH session
make ssh

# Stream live app logs
make logs

# Print service statuses (app + timers)
make status

# View the full first-boot bootstrap log
make cloud-init-log
```

Once SSH'd in:

```bash
# App service
sudo systemctl status app
journalctl -u app -f

# Restocking generator
journalctl -u restocking-generator -n 50 --no-pager

# Job status generator
journalctl -u job-status-generator -n 50 --no-pager

# nginx
sudo systemctl status nginx
sudo nginx -t   # test config

# View the injected environment file
cat /opt/app/.env
```

---

## 8. Updating the Application

### Quick update (SSH + git pull)

```bash
make deploy
```

Under the hood: SSHes into the VM, runs `git pull`, reinstalls dependencies, restarts the `app` service, and confirms it's active.

### Manual

```bash
make ssh

cd /opt/app
sudo git pull
sudo /opt/app/.venv/bin/pip install -r requirements.txt
sudo systemctl restart app
systemctl is-active app
```

### GitHub Actions (automated)

Push to `main` — the workflow in `.github/workflows/deploy.yml` deploys automatically. See [section 9](#9-github-actions-cicd-setup) for the full setup walkthrough.

### Full re-provision (cloud-init change)

Required when you change `scripts/cloud-init.yaml` or want to update the OS image:

```bash
cd terraform
terraform taint azurerm_linux_virtual_machine.app_vm
make apply-auto
```

This destroys and recreates the VM. Data on the OS disk is lost.

---

## 9. GitHub Actions CI/CD Setup

The workflow in `.github/workflows/deploy.yml` automatically deploys the application to the VM on every push to `main` that touches `app/**`. It requires the VM to be provisioned first (`make apply` must have completed successfully).

### What the workflow does

```
push to main (app/** changed)
  └── job: SSH deploy to Azure VM
        1. Checkout code
        2. Resolve target host (VM_HOST secret or manual vm_host input)
        3. SSH into VM (appleboy/ssh-action@v1.0.3):
             → cd /opt/app
             → sudo git pull
             → sudo /opt/app/.venv/bin/pip install -r requirements.txt
             → sudo systemctl restart app
             → sleep 3s, then systemctl is-active --quiet app
             → journalctl -u app -n 20
        4. Health check: GET http://<VM_HOST>:<APP_PORT>/health
             retries 5 × every 5 s — fails the run if no 200
```

The workflow also supports **manual dispatch** from the Actions tab, with an optional `vm_host` input to target a specific IP without changing the `VM_HOST` secret.

---

### Step 1 — Get the VM public IP

After `terraform apply` completes, retrieve the public IP:

```bash
make output
# or
cd terraform && terraform output -raw vm_public_ip
```

Note this value — you will need it in the next step.

---

### Step 2 — Add repository secrets

Go to your GitHub repository → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**.

Add each of the following secrets:

| Secret | Value | Notes |
|--------|-------|-------|
| `VM_HOST` | Public IP of the VM | From `make output` |
| `VM_USER` | `azureuser` | Default admin username; change if you set a different `admin_username` in `terraform.tfvars` |
| `VM_SSH_KEY` | Full contents of `~/.ssh/id_rsa` | The private key — include the `-----BEGIN` and `-----END` lines |
| `APP_PORT` | `8000` | Optional; workflow falls back to `8000` if the secret is absent |

**Copying the private key:**

```bash
# macOS — copy to clipboard
cat ~/.ssh/id_rsa | pbcopy

# Linux
cat ~/.ssh/id_rsa | xclip -selection clipboard
# or just print and copy manually
cat ~/.ssh/id_rsa
```

Paste the entire output (all lines including the header and footer) as the value of `VM_SSH_KEY`.

> Never share or commit the private key. GitHub encrypts all repository secrets and they are never exposed in workflow logs.

---

### Step 3 — Confirm the workflow file is tracked

The workflow file must be committed to the repository at `.github/workflows/deploy.yml`. Verify:

```bash
git ls-files .github/workflows/deploy.yml
# Expected: .github/workflows/deploy.yml
```

If it is not tracked, stage and commit it:

```bash
git add .github/workflows/deploy.yml
git commit -m "ci: add app deploy workflow"
git push origin main
```

---

### Step 4 — Trigger your first deploy

The push path filter (`app/**`) requires actual file changes under `app/` — an empty commit won't trigger it. The simplest way to trigger the first run is the manual dispatch:

1. Go to your repository → **Actions** → **Deploy App** → **Run workflow**
2. Select `main` and click **Run workflow**

Alternatively, make a real change to any file under `app/` and push:

```bash
# Example: append a blank line to requirements.txt
echo "" >> app/requirements.txt
git add app/requirements.txt
git commit -m "ci: trigger first deploy"
git push origin main
```

Watch the run live:

1. Go to your repository → **Actions** → **Deploy App**
2. Click the running workflow to see real-time logs
3. The **Health check** step confirms the app responded with HTTP 200 after the deploy

A passing run looks like:

```
✓ app service is running
→ Last 20 log lines:
  INFO:     Application startup complete.
  ...
→ Checking http://20.1.2.3:8000/health ...
✓ Health check passed (HTTP 200)
```

---

### Step 5 — Trigger a manual deploy

To deploy without a code push (e.g. after updating secrets or rotating the VM):

1. Go to **Actions** → **Deploy App** → **Run workflow**
2. Select the branch (`main`)
3. Optionally enter a VM IP in the **vm_host** field to override `VM_HOST`
4. Click **Run workflow**

---

### Workflow trigger details

The workflow only runs when files under these paths change on a push to `main`:

```yaml
on:
  push:
    branches: [main]
    paths:
      - "app/**"
      - ".github/workflows/deploy.yml"
```

Pushes that only change Terraform files, documentation, or scripts do **not** trigger a deploy. Use `workflow_dispatch` (step 5) to force a deploy from any commit.

---

### Updating the VM IP after re-provision

The public IP resource (`pip-app-<env>`) is separate from the VM resource. How it behaves depends on which destroy path was taken:

| Action | Public IP outcome |
|--------|------------------|
| `terraform taint azurerm_linux_virtual_machine.app_vm` + apply | **IP retained** — only the VM is destroyed and recreated; the PIP resource survives |
| `make destroy` + `make apply` | **IP changes** — all resources including the PIP are destroyed; a new static IP is allocated |

After a full destroy + apply, update `VM_HOST`:

1. Run `make output` to get the new IP
2. Go to GitHub → **Settings** → **Secrets and variables** → **Actions**
3. Click `VM_HOST` → **Update** → paste the new IP → **Save**

The next workflow run will use the updated IP automatically.

---

### Troubleshooting the workflow

| Symptom | Cause | Fix |
|---------|-------|-----|
| `VM_HOST secret is not set` | Secret missing or misspelled | Check Settings → Secrets — name must be exactly `VM_HOST` |
| `SSH authentication failed` | Wrong private key in `VM_SSH_KEY` | Paste the full `~/.ssh/id_rsa` including header/footer lines |
| `ssh: connect to host … port 22: Connection refused` | VM is stopped, NSG blocks SSH, or IP changed | Check VM is running in Azure portal; verify `ssh_allowed_cidr` in tfvars; update `VM_HOST` if IP changed |
| `git pull` fails with `Permission denied` | App repo is private but no deploy key is configured | See [Private repositories](#private-repositories) section |
| Health check fails (HTTP 502) | App crashed on restart | Check workflow logs for the `journalctl` output; SSH in and run `journalctl -u app -n 50` |
| Health check fails (connection refused on port 8000) | `APP_PORT` secret doesn't match `app_port` in tfvars | Set `APP_PORT` secret to match `terraform output` `app_url` port |

---

## 10. Security Hardening

### Restrict SSH access

The default `ssh_allowed_cidr = "0.0.0.0/0"` is convenient for development but exposes SSH to the internet. In production, set it to your static IP or VPN CIDR:

```hcl
# terraform.tfvars
ssh_allowed_cidr = "203.0.113.42/32"   # your static IP
# or
ssh_allowed_cidr = "10.10.0.0/16"      # your VPN range
```

### Private repositories

If the app repo requires authentication, embed a deploy key during cloud-init:

1. Generate a key pair:

   ```bash
   ssh-keygen -t ed25519 -C "deploy-key" -f deploy_key -N ""
   ```

2. Add `deploy_key.pub` as a read-only deploy key in your repo settings.

3. Add a `write_files` entry to `scripts/cloud-init.yaml`:

   ```yaml
   write_files:
     - path: /home/appuser/.ssh/id_ed25519
       permissions: "0600"
       owner: appuser:appuser
       content: |
         -----BEGIN OPENSSH PRIVATE KEY-----
         <paste key here>
         -----END OPENSSH PRIVATE KEY-----
   ```

4. Update the `git clone` line in `runcmd` to use the SSH URL:

   ```yaml
   - git clone git@github.com:<org>/<repo>.git /opt/app
   ```

   > For production, store the key in Azure Key Vault and retrieve it at runtime rather than embedding it in cloud-init.

### systemd hardening (already enabled)

The `app` service unit has the following sandbox flags active:

- `NoNewPrivileges=true`
- `PrivateTmp=true`
- `ProtectSystem=strict`
- App runs as `appuser` — no shell, no sudo

---

## 11. Destroying Resources

```bash
make destroy
```

Destroys **all** Azure resources in the resource group. There is a 5-second confirmation pause. This is irreversible — any data on the OS disk is lost.

---

## Makefile Reference

```
make init           terraform init
make validate       terraform validate
make fmt            terraform fmt (format .tf files)
make plan           terraform plan -out=tfplan
make apply          terraform apply tfplan
make apply-auto     terraform apply -auto-approve
make destroy        terraform destroy (5 s pause)

make deploy         git pull + pip install + restart app on running VM
make ssh            open SSH session to the VM
make logs           stream live app logs (journalctl -f)
make status         print systemd status for app + timers
make cloud-init-log view /var/log/cloud-init-output.log
make output         print terraform outputs (IP, URL, SSH command)
make clean          remove local .terraform/ and plan files
```

---

## Useful Links

- [Deploy Guide](deploy.md) — first-time provisioning, app updates, rollback, environment promotion
- [Architecture](architecture.md) — detailed component breakdown
- [Configuration Reference](configuration-reference.md) — every Terraform variable
- [Remote State](remote-state.md) — Azure Blob Storage backend setup
- [Troubleshooting](../docs/troubleshooting.md) — common errors and fixes
- [Code-Only Updates](../docs/code-only-updates.md) — deploy options compared
