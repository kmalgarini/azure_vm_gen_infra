# Plan: Azure Linux VM Infrastructure + Python App Deployment

## Overview

Provision an Azure Linux virtual machine using Terraform and have the Python application fully installed, configured, and running by the time `terraform apply` completes — with no manual post-deployment step required. The app lifecycle (install → configure → start → auto-restart) is driven entirely by a `cloud-init` script embedded in the Terraform configuration as `custom_data`. The stack is designed to be reproducible, idempotent, and production-ready.

---

## Phase 1 – Repository & Tooling Setup

### Goals
- Establish a clean project structure
- Pin tool versions for reproducibility

### Tasks
- [ ] Initialize Terraform project layout (`main.tf`, `variables.tf`, `outputs.tf`, `terraform.tfvars`)
- [ ] Add `.terraform.lock.hcl` to version control, ignore `.terraform/` directory
- [ ] Create a `scripts/` folder for provisioning helpers
- [ ] Create an `app/` folder for the Python application
- [ ] Add a `Makefile` (or `justfile`) with common targets: `init`, `plan`, `apply`, `destroy`, `deploy`
- [ ] Configure pre-commit hooks (tflint, terraform fmt, detect-secrets)

### Tools Required
| Tool | Purpose |
|------|---------|
| Terraform ≥ 1.7 | IaC provisioning + app bootstrap trigger |
| Azure CLI (`az`) | Auth + resource queries |
| Python ≥ 3.11 | Application runtime (installed on VM via cloud-init) |
| SSH key pair | VM access + remote-exec bootstrap verification |

---

## Phase 2 – Azure Infrastructure (Terraform)

### Resources to Provision

```
Resource Group
└── Virtual Network
    └── Subnet
        └── Network Security Group
            └── NSG Rules (SSH :22, App port e.g. :8000)
        └── Public IP (Static)
        └── Network Interface
            └── Linux Virtual Machine (Ubuntu 24.04 LTS)
                └── OS Disk (Premium SSD, 30 GB min)
                └── cloud-init / custom_data bootstrap script
Storage Account (optional – remote Terraform state backend)
```

### Key Terraform Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `resource_group_name` | `rg-vm-python` | Azure resource group name |
| `location` | `eastus` | Azure region |
| `vm_size` | `Standard_B2s` | VM SKU |
| `admin_username` | `azureuser` | SSH admin user |
| `ssh_public_key_path` | `~/.ssh/id_rsa.pub` | Path to local public key |
| `ssh_private_key_path` | `~/.ssh/id_rsa` | Path to private key (remote-exec verification) |
| `app_repo_url` | _(required)_ | Git URL of the Python app to clone on first boot |
| `app_port` | `8000` | Port exposed by the Python app |
| `environment` | `dev` | Tag for environment |

### Security Considerations
- Disable password authentication; enforce SSH key auth only
- Restrict SSH ingress to a known CIDR (not `0.0.0.0/0`) via NSG rule
- Use a managed identity on the VM if the app needs Azure resource access
- Store secrets (connection strings, API keys) in Azure Key Vault; reference from app via env vars
- Enable Azure Defender for Servers (optional for dev, recommended for prod)

---

## Phase 3 – Integrated Bootstrap via cloud-init (runs automatically on first boot)

> **Key constraint**: the app must be live by the time `terraform apply` returns.
> This is achieved by embedding `cloud-init.yaml` as `custom_data` in the Terraform VM resource. Azure executes it on first boot with no manual intervention.

### cloud-init execution order

1. **Package install** – `apt-get update` + install Python 3.11, pip, venv, git, nginx
2. **App user** – create dedicated system user `appuser` (no login shell, no sudo)
3. **App code** – clone repo from Git (or pull a pre-built artifact) into `/opt/app`
4. **Write `.env`** – inject runtime secrets/config from Terraform `templatefile()` or Azure Key Vault references
5. **Virtual environment** – `python3.11 -m venv /opt/app/.venv`
6. **Dependencies** – `/opt/app/.venv/bin/pip install -r /opt/app/requirements.txt`
7. **systemd unit** – write `/etc/systemd/system/app.service` inline, `daemon-reload`
8. **Enable + start** – `systemctl enable app && systemctl start app`
9. (Optional) **nginx reverse proxy** – write `/etc/nginx/sites-available/app`, enable, reload
10. (Optional) **certbot / Let's Encrypt** – only if a DNS name is provided

### How Terraform embeds cloud-init

```hcl
# terraform/main.tf (relevant excerpt)
resource "azurerm_linux_virtual_machine" "app_vm" {
  # ...
  custom_data = base64encode(templatefile("${path.module}/../scripts/cloud-init.yaml", {
    app_repo    = var.app_repo_url
    app_port    = var.app_port
    app_env     = var.environment
  }))
}
```

`templatefile()` lets Terraform inject variables (repo URL, port, env) into the cloud-init YAML before base64-encoding it as `custom_data`.

### Full cloud-init template (`scripts/cloud-init.yaml`)

```yaml
#cloud-config

package_update: true
package_upgrade: true

packages:
  - python3.11
  - python3.11-venv
  - python3-pip
  - git
  - nginx

write_files:
  - path: /etc/systemd/system/app.service
    permissions: "0644"
    content: |
      [Unit]
      Description=Python Application
      After=network.target

      [Service]
      User=appuser
      WorkingDirectory=/opt/app
      EnvironmentFile=/opt/app/.env
      ExecStart=/opt/app/.venv/bin/uvicorn main:app --host 0.0.0.0 --port ${app_port}
      Restart=always
      RestartSec=5

      [Install]
      WantedBy=multi-user.target

  - path: /opt/app/.env
    permissions: "0640"
    owner: appuser:appuser
    content: |
      APP_ENV=${app_env}
      APP_PORT=${app_port}

runcmd:
  - useradd -r -s /usr/sbin/nologin appuser
  - git clone ${app_repo} /opt/app
  - chown -R appuser:appuser /opt/app
  - python3.11 -m venv /opt/app/.venv
  - /opt/app/.venv/bin/pip install --upgrade pip
  - /opt/app/.venv/bin/pip install -r /opt/app/requirements.txt
  - systemctl daemon-reload
  - systemctl enable app
  - systemctl start app
```

### Verifying bootstrap completion

cloud-init writes its exit status to `/var/log/cloud-init-output.log`. A Terraform `null_resource` with a `remote-exec` provisioner can be used to wait and assert success before `terraform apply` exits:

```hcl
resource "null_resource" "wait_for_app" {
  depends_on = [azurerm_linux_virtual_machine.app_vm]

  connection {
    type        = "ssh"
    host        = azurerm_public_ip.app.ip_address
    user        = var.admin_username
    private_key = file(var.ssh_private_key_path)
  }

  provisioner "remote-exec" {
    inline = [
      "cloud-init status --wait",
      "systemctl is-active --quiet app && echo 'App is running'"
    ]
  }
}
```

This makes `terraform apply` block until the app process is confirmed active.

---

## Phase 4 – Python Application

### Minimal App Structure

```
app/
├── main.py            # Entry point (e.g. FastAPI / Flask)
├── requirements.txt   # Pinned dependencies
├── .env.example       # Template for environment variables
├── systemd/
│   └── app.service    # systemd unit file
└── README.md
```

### Recommended Runtime
- **Framework**: FastAPI (async, lightweight) or Flask (simpler)
- **WSGI/ASGI server**: `uvicorn` (FastAPI) or `gunicorn` (Flask)
- **Process manager**: `systemd` (keeps app alive on reboot/crash)

### systemd Unit File (`app.service`)

```ini
[Unit]
Description=Python Application
After=network.target

[Service]
User=appuser
WorkingDirectory=/opt/app
EnvironmentFile=/opt/app/.env
ExecStart=/opt/app/.venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

---

## Phase 5 – Deployment Workflow

### Single-command deployment (infra + app together)

```
1. az login  (or export ARM_* env vars for CI)
2. terraform init
3. terraform plan -var="app_repo_url=https://github.com/<org>/<repo>" -out=tfplan
4. terraform apply tfplan
   → VM is provisioned
   → cloud-init runs on first boot: installs Python, clones app, starts service
   → null_resource/remote-exec waits for cloud-init to finish
   → terraform apply exits only when `systemctl is-active app` confirms success
5. Done — app is live at http://<public_ip>:<app_port>
```

> There is **no separate deploy step**. Infrastructure and application are deployed atomically via `terraform apply`.

### Key Terraform variables to set

| Variable | Example value |
|----------|--------------|
| `app_repo_url` | `https://github.com/acme/myapp.git` |
| `app_port` | `8000` |
| `ssh_public_key_path` | `~/.ssh/id_rsa.pub` |
| `ssh_private_key_path` | `~/.ssh/id_rsa` (needed by remote-exec) |
| `environment` | `dev` |

### Subsequent Code-Only Updates (no infra change)

Option A – **SSH + git pull** (quick iteration)
```bash
ssh azureuser@<public_ip> "cd /opt/app && git pull && \
  .venv/bin/pip install -r requirements.txt && \
  sudo systemctl restart app"
```

Option B – **`terraform apply` with `taint`** (full re-provisioning)
```bash
terraform taint azurerm_linux_virtual_machine.app_vm
terraform apply   # recreates VM, cloud-init re-runs from scratch
```

Option C – **GitHub Actions / Azure DevOps** (recommended for teams)
- Trigger on push to `main`
- SSH into VM, pull latest code, restart service

---

## Phase 6 – Observability & Maintenance

- [ ] Enable Azure Monitor + Log Analytics Workspace
- [ ] Stream VM diagnostics (boot diagnostics, guest OS metrics)
- [ ] Tail app logs: `journalctl -u app -f`
- [ ] Set up alerting on CPU / memory / disk thresholds
- [ ] Schedule OS patching via Azure Update Manager
- [ ] Document backup strategy for OS disk (Azure Backup or snapshot policy)

---

## Directory Layout (Target)

```
azure_vm_gen_infra/
├── plan/
│   └── azure-linux-vm-python-deploy.md   ← this file
├── terraform/
│   ├── main.tf
│   ├── variables.tf
│   ├── outputs.tf
│   ├── terraform.tfvars
│   └── modules/
│       └── vm/
├── scripts/
│   ├── cloud-init.yaml        # bootstrap: installs + starts app on first boot
│   └── deploy.sh              # optional: code-only update helper (ssh + git pull)
├── app/
│   ├── main.py
│   ├── requirements.txt
│   ├── .env.example
│   └── systemd/
│       └── app.service
├── ansible/              (optional – code-only updates only, not initial deploy)
│   ├── deploy.yml
│   └── inventory/
├── .github/
│   └── workflows/
│       └── deploy.yml    (optional CI/CD)
├── Makefile
└── README.md
```

---

## Open Decisions / Next Steps

| # | Decision | Options | Status |
|---|----------|---------|--------|
| 1 | Terraform state backend | Local file vs. Azure Blob Storage | Pending |
| 2 | Python framework | FastAPI vs. Flask | Pending |
| 3 | App source during cloud-init | Public GitHub repo vs. private repo (deploy key) vs. Azure Artifacts | Pending |
| 4 | TLS / domain | Self-signed vs. Let's Encrypt vs. Azure App Gateway | Pending |
| 5 | VM size | `Standard_B2s` (dev) vs. larger SKU (prod) | Pending |
| 6 | Secrets management | `.env` via `templatefile()` vs. Azure Key Vault | Pending |
| 7 | Bootstrap verification timeout | `cloud-init status --wait` default vs. custom timeout | Pending |
