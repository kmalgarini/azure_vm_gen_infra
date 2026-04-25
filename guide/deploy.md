# Deployment Guide

Step-by-step runbook for provisioning the infrastructure and deploying the application — from first run through ongoing updates, rollback, and environment promotion.

---

## Deploy Types at a Glance

| Scenario | Command | Duration | Infra change |
|----------|---------|----------|-------------|
| First-time provisioning | `make plan && make apply` | 5–12 min | Yes — creates all resources |
| App code update | `make deploy` | ~30 s | No |
| App update via CI | push to `main` | ~1 min | No |
| Config change (tfvars) | `make plan && make apply` | 1–3 min | Yes — modifies resources in-place |
| OS / cloud-init change | `terraform taint` + apply | 5–12 min | Yes — recreates VM |
| Tear down | `make destroy` | 2–3 min | Yes — deletes all resources |

---

## Part 1 — First-Time Infrastructure Provisioning

Use this path when no Azure resources exist yet.

### Pre-flight checklist

Before running `terraform apply` for the first time:

- [ ] `terraform -version` reports ≥ 1.7
- [ ] `az --version` reports ≥ 2.60
- [ ] `az account show` shows the correct subscription
- [ ] `ls ~/.ssh/id_rsa ~/.ssh/id_rsa.pub` — both files exist
- [ ] `terraform/terraform.tfvars` exists with at least `app_repo_url` set
- [ ] `app_repo_url` is reachable from the internet (or a deploy key is configured for private repos)
- [ ] `ssh_allowed_cidr` is set to your IP/CIDR (not `0.0.0.0/0`) for non-dev environments

### Step 1 — Authenticate to Azure

```bash
az login
az account set --subscription "<subscription-id-or-name>"
az account show --query "{name:name, id:id}" -o table
```

### Step 2 — Create terraform.tfvars

```bash
# terraform/terraform.tfvars is gitignored — create it locally
cat > terraform/terraform.tfvars <<EOF
app_repo_url     = "https://github.com/<org>/<repo>.git"
environment      = "dev"
ssh_allowed_cidr = "$(curl -s ifconfig.me)/32"
EOF
```

For a full list of available variables see [configuration-reference.md](configuration-reference.md).

### Step 3 — Initialise providers

```bash
make init
```

Downloads the AzureRM (`~> 3.110`) and Null (`~> 3.2`) providers. Run this once, and again after any provider version change.

### Step 4 — Review the plan

```bash
make plan
```

Verify the plan shows **10 resources to add** and no unexpected changes. Inspect any resource that is flagged as `forces replacement` — those will destroy and recreate. Save the plan file (`tfplan`) for the next step.

### Step 5 — Apply

```bash
make apply
```

What happens during apply (5–12 minutes):

```
1. Azure resources created (RG → VNet → Subnet → NSG → PIP → NIC → VM)
2. AzureMonitorLinuxAgent extension installed on the VM
3. VM first boot — cloud-init runs:
     • apt upgrade + install Python 3.11, git, nginx
     • adduser appuser
     • git clone <app_repo_url> → /opt/app
     • python3 -m venv /opt/app/.venv && pip install -r requirements.txt
     • write + enable systemd units (app, restocking-generator, job-status-generator)
     • configure nginx reverse proxy on port 80
     • mkdir /var/restocking/inbound /var/jobs
4. null_resource.wait_for_app SSHes in and polls until:
     • cloud-init status: done
     • systemctl is-active app
     • systemctl is-active restocking-generator.timer
     • systemctl is-active job-status-generator.timer
5. terraform apply exits ✓
```

Successful output:

```
null_resource.wait_for_app (remote-exec): ✓ app service is active
null_resource.wait_for_app (remote-exec): ✓ restocking-generator.timer is active
null_resource.wait_for_app (remote-exec): ✓ job-status-generator.timer is active
null_resource.wait_for_app: Creation complete

Apply complete! Resources: 10 added, 0 changed, 0 destroyed.

Outputs:
  app_url          = "http://20.1.2.3:8000"
  resource_group_name = "rg-vm-python"
  ssh_command      = "ssh azureuser@20.1.2.3"
  vm_id            = "/subscriptions/.../virtualMachines/vm-app-dev"
  vm_public_ip     = "20.1.2.3"
```

### Step 6 — Verify

```bash
# Print all outputs
make output

# Health check
curl http://$(cd terraform && terraform output -raw vm_public_ip):8000/health
# Expected: {"status":"healthy"}

# Root endpoint
curl http://$(cd terraform && terraform output -raw vm_public_ip):8000/
# Expected: {"app":"azure-vm-python","version":"1.0.0","environment":"dev",...}

# nginx proxy (port 80)
curl http://$(cd terraform && terraform output -raw vm_public_ip)/health
# Expected: {"status":"healthy"}

# Check generator services are running
make ssh -- "systemctl is-active restocking-generator.timer && systemctl is-active job-status-generator.timer"
```

---

## Part 2 — App-Only Deployments

Use this after the VM is already provisioned. No Terraform or Azure resource changes are made.

### Option A — make deploy (fastest)

```bash
make deploy
```

Runs `scripts/deploy.sh` which:
1. SSHes into the VM using the IP from `terraform output`
2. `sudo git pull` in `/opt/app`
3. `pip install -r requirements.txt` (picks up new dependencies)
4. `systemctl restart app`
5. Confirms `systemctl is-active app` and prints the last 10 journal lines

Deploy to a specific IP (when Terraform state is not local):

```bash
./scripts/deploy.sh 20.1.2.3
./scripts/deploy.sh 20.1.2.3 azureuser ~/.ssh/id_rsa
```

### Option B — Manual SSH

Use when you need to inspect before committing to a restart, or when deploying to a specific branch/commit.

```bash
make ssh

# On the VM
cd /opt/app

# Preview what will change
sudo git fetch && sudo git log HEAD..origin/main --oneline

# Pull and update
sudo git pull
sudo /opt/app/.venv/bin/pip install -r requirements.txt

# Restart
sudo systemctl restart app

# Confirm
systemctl is-active app
journalctl -u app -n 20 --no-pager
```

### Option C — GitHub Actions (automated CI/CD)

The workflow in `.github/workflows/deploy.yml` triggers automatically on every push to `main` that touches `app/**`.

**One-time setup — add repository secrets:**

Go to GitHub → your repo → Settings → Secrets and variables → Actions → New repository secret.

| Secret | Value | Where to get it |
|--------|-------|----------------|
| `VM_HOST` | Public IP of the VM | `make output` or `terraform output vm_public_ip` |
| `VM_USER` | `azureuser` | Default value |
| `VM_SSH_KEY` | Private key contents | `cat ~/.ssh/id_rsa` |
| `APP_PORT` | `8000` | Optional; defaults to 8000 if omitted |

**Deploy by pushing:**

```bash
git add .
git commit -m "feat: update app"
git push origin main
```

The workflow runs:
1. Checkout
2. SSH into VM → `git pull` → `pip install` → `systemctl restart app`
3. Health check: `curl http://<VM_HOST>:<APP_PORT>/health` (retries 5×, 5 s apart)

**Trigger a manual deploy** (from the Actions tab, without a push):
1. GitHub → Actions → Deploy App → Run workflow
2. Optionally override the VM IP in the `vm_host` input field

**Workflow trigger path filter:** Only runs when files under `app/**` or `.github/workflows/deploy.yml` change. Pushes to `main` that only modify Terraform or docs do not trigger a deploy.

---

## Part 3 — Infrastructure Updates (Terraform Config Changes)

Use this when you modify `terraform.tfvars` or any `.tf` file — but the changes can be applied in-place without recreating the VM.

Examples of in-place changes: `vm_size`, `ssh_allowed_cidr`, `os_disk_size_gb`, adding NSG rules, updating generator tuning variables.

```bash
# Edit terraform/terraform.tfvars (or a .tf file)
# Then:
make plan    # review — ensure no resource is flagged as "forces replacement"
make apply   # apply the plan
```

### When changes force VM recreation

Some changes require destroying and recreating the VM (marked `forces replacement` in the plan):

- Changing the OS image
- Changing the admin username
- Changing `app_repo_url` or `cloud-init.yaml` (the `custom_data` hash changes)

If you intend the recreation, proceed with `make apply`. If you didn't expect it, cancel and investigate before applying.

> **Data warning**: recreating the VM destroys everything on the OS disk — including `/var/restocking/inbound/`, `/var/jobs/`, and any local state not committed to git.

---

## Part 4 — Full VM Re-provision (cloud-init Change)

Use this when you change `scripts/cloud-init.yaml` — for example, to update packages, add new systemd units, or change the nginx config.

```bash
# 1. Edit scripts/cloud-init.yaml

# 2. Taint the VM to mark it for recreation
cd terraform && terraform taint azurerm_linux_virtual_machine.app_vm

# 3. Also taint the bootstrap gate so it re-runs
terraform taint null_resource.wait_for_app

# 4. Apply (recreates the VM + runs cloud-init again)
make apply-auto
```

Terraform will destroy the old VM, create a new one, and block until cloud-init finishes and the services are active. The public IP is **static** — `pip-app-<env>` retains the same address.

---

## Part 5 — Rollback

### App rollback (revert to a previous commit)

```bash
make ssh

cd /opt/app

# List recent commits
sudo git log --oneline -10

# Revert to a specific commit
sudo git checkout <commit-sha>
sudo systemctl restart app

# Verify
systemctl is-active app
journalctl -u app -n 20 --no-pager
```

To make the rollback permanent, revert the commit in your app repository and push:

```bash
git revert <commit-sha>
git push origin main
```

GitHub Actions will pick up the push and re-deploy.

### Infrastructure rollback (revert Terraform state)

If a `terraform apply` put the infrastructure in a bad state and you want to revert:

```bash
cd terraform

# List available state snapshots (if using remote state with versioning)
az storage blob list \
  --account-name "<tfstate_storage_account>" \
  --container-name "tfstate" \
  --output table

# Download a previous state version
az storage blob download \
  --account-name "<tfstate_storage_account>" \
  --container-name "tfstate" \
  --name "azure-vm-python.tfstate" \
  --file terraform.tfstate.backup \
  --version-id "<version-id>"

# Push the old state back
terraform state push terraform.tfstate.backup

# Reconcile
terraform plan   # review the diff before applying
```

---

## Part 6 — Environment Promotion

Deploy the same application to multiple environments by maintaining a `tfvars` file per environment. Each environment gets its own Azure resource group, VNet, and VM.

### Directory layout

```
terraform/
├── envs/
│   ├── dev.tfvars
│   ├── staging.tfvars
│   └── prod.tfvars
├── main.tf
├── variables.tf
└── versions.tf
```

### Deploy to dev

```bash
make plan    # uses terraform.tfvars by default
make apply
```

### Deploy to staging / prod

```bash
# Plan with environment-specific vars
cd terraform && terraform plan \
  -var-file="envs/staging.tfvars" \
  -out=tfplan-staging

# Apply
terraform apply tfplan-staging
```

### Promotion checklist

Before promoting from dev → staging, or staging → prod:

- [ ] All tests pass in the app repository
- [ ] `curl http://<dev_ip>:8000/health` returns 200
- [ ] No errors in `make logs` output
- [ ] `terraform plan -var-file="envs/prod.tfvars"` shows only expected changes
- [ ] `ssh_allowed_cidr` is restricted (not `0.0.0.0/0`)
- [ ] Remote state is configured — see [remote-state.md](remote-state.md)

---

## Part 7 — Tear Down

Destroys **all** Azure resources in the resource group. There is a 5-second pause before it runs.

```bash
make destroy
```

After destroying, the Terraform state still records the deletion. To start fresh (next `make apply` will create everything from scratch):

```bash
make init    # re-initialise providers if needed
make plan    # should show 10 resources to add
make apply
```

---

## Post-Deploy Verification Checklist

Run after every deploy (both infra and app):

```bash
# 1. App health endpoint
curl -s http://$(cd terraform && terraform output -raw vm_public_ip):8000/health
# Expected: {"status":"healthy"}

# 2. nginx health (port 80)
curl -s http://$(cd terraform && terraform output -raw vm_public_ip)/health
# Expected: {"status":"healthy"}

# 3. No errors in recent app logs
make logs
# Ctrl-C after 10–15 seconds — look for ERROR or CRITICAL lines

# 4. Generator timers active
make ssh -- "systemctl is-active restocking-generator.timer job-status-generator.timer"
# Expected: active (x2)

# 5. Generator output present
make ssh -- "ls -lht /var/restocking/inbound/ | head -5 && cat /var/jobs/status.json"
```

---

## Quick Reference

```bash
make help            # list all make targets

# Infra
make init            # download providers
make plan            # preview changes
make apply           # apply saved plan
make apply-auto      # apply without confirmation prompt
make destroy         # destroy all resources
make output          # print IP, URL, SSH command

# App deployment
make deploy          # git pull + restart on running VM

# Operations
make ssh             # interactive SSH session
make logs            # stream live app logs
make status          # systemd service status
make cloud-init-log  # first-boot bootstrap log
```
