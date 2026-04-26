# Azure Linux VM + Python App — Infrastructure

Provision a production-ready Azure Linux VM and have your Python application **running automatically** by the time `terraform apply` completes. No manual post-deployment step is required.

```
terraform apply
  → Resource Group, VNet, NSG, Public IP, VM created
  → Azure Monitor Agent extension installed on the VM
  → cloud-init bootstraps the VM on first boot:
      installs Python 3 (3.12 on Ubuntu 24.04), clones your repo, creates a venv,
      installs dependencies, and starts the app via systemd
  → remote-exec waits for cloud-init to finish and confirms the app is active
  → terraform apply exits ✓
  → app is live at http://<public_ip>:8000
```

---

## Repository Layout

```
azure_vm_gen_infra/
├── plan/
│   └── azure-linux-vm-python-deploy.md   # Architecture plan
├── terraform/
│   ├── versions.tf        # Provider + Terraform version pins
│   ├── main.tf            # All Azure resources + bootstrap verification
│   ├── variables.tf       # Input variable declarations
│   ├── outputs.tf         # Public IP, app URL, SSH command
│   └── terraform.tfvars   # Non-sensitive defaults (edit before applying)
├── scripts/
│   ├── cloud-init.yaml    # First-boot bootstrap template (rendered by Terraform)
│   └── deploy.sh          # Code-only update helper (SSH + git pull)
├── app/
│   ├── main.py            # FastAPI application entry point
│   ├── requirements.txt   # Pinned Python dependencies
│   ├── .env.example       # Environment variable template
│   └── systemd/
│       └── app.service    # systemd unit file (reference copy)
├── docs/
│   ├── getting-started.md
│   ├── troubleshooting.md
│   └── code-only-updates.md
├── .github/
│   └── workflows/
│       └── deploy.yml     # GitHub Actions CI/CD workflow
├── Makefile               # Common targets: init, plan, apply, deploy, logs …
├── .gitignore
├── .pre-commit-config.yaml
└── README.md              # This file
```

---

## Prerequisites

| Tool | Version | Install |
|------|---------|---------|
| Terraform | ≥ 1.7 | [terraform.io/downloads](https://developer.hashicorp.com/terraform/downloads) |
| Azure CLI | ≥ 2.60 | `brew install azure-cli` |
| SSH key pair | — | `ssh-keygen -t rsa -b 4096` |

---

## Quick Start

```bash
# 1. Authenticate to Azure
az login

# 2. Clone this repo and enter the project
git clone <this-repo> && cd azure_vm_gen_infra

# 3. Edit terraform/terraform.tfvars
#    — set app_repo_url to your Python app's Git URL
#    — optionally restrict ssh_allowed_cidr to your IP

# 4. Initialise Terraform
make init

# 5. Preview what will be created
make plan

# 6. Provision infra + deploy app (blocks until app is running)
make apply

# 7. Get the app URL and SSH command
make output
```

See [docs/getting-started.md](docs/getting-started.md) for a detailed walkthrough.

---

## Key Variables

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `app_repo_url` | — | Yes | Git URL of your Python application |
| `resource_group_name` | `rg-vm-python` | No | Azure resource group |
| `location` | `canadaeast` | No | Azure region |
| `vm_size` | `Standard_B2s` | No | VM SKU |
| `app_port` | `8000` | No | App TCP port |
| `ssh_allowed_cidr` | `0.0.0.0/0` | No | CIDR allowed to SSH (restrict in prod) |
| `environment` | `dev` | No | `dev` / `staging` / `prod` |

Full list in [`terraform/variables.tf`](terraform/variables.tf).

---

## Makefile Targets

```bash
make help           # List all targets with descriptions
make init           # terraform init
make validate       # terraform validate
make fmt            # terraform fmt
make plan           # terraform plan
make apply          # terraform apply (uses existing plan file)
make apply-auto     # terraform apply -auto-approve
make destroy        # terraform destroy

make deploy         # Code-only update: git pull + restart on running VM
make ssh            # Open SSH session
make logs           # Stream live app logs
make status         # Check systemd service status
make cloud-init-log # View the first-boot bootstrap log
```

---

## Application

The bundled example app (`app/`) is a FastAPI service with three endpoints:

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | App name, version, environment, timestamp |
| GET | `/health` | Liveness probe (200 OK when process is up) |
| GET | `/info` | Hostname, Python version, OS, git SHA |
| GET | `/docs` | Swagger UI |

Replace `app/` with your own project. The only requirements are:
1. A `requirements.txt` at the repository root
2. An entry point that starts a server on `0.0.0.0:$APP_PORT`
3. Provide `app_repo_url` pointing to a Git repository accessible from the VM

---

## How Bootstrap Works

1. `terraform apply` creates the VM with the cloud-init template in `custom_data`
2. Terraform installs the Azure Monitor Agent VM extension automatically.
3. Azure runs cloud-init on first boot — it:
   - Updates packages and installs Python 3, git, nginx
   - Creates a system user `appuser`
   - Clones `app_repo_url` → `/opt/app`
   - Creates a virtualenv, installs `requirements.txt`
   - Writes a systemd unit and starts the `app` service
   - Configures nginx to proxy port 80 → app port
4. A Terraform `null_resource` SSHes in and runs `cloud-init status --wait` — `terraform apply` only exits after the service is confirmed active

---

## Security Notes

- Password authentication is **disabled**; SSH key auth only
- Restrict `ssh_allowed_cidr` to your IP (`1.2.3.4/32`) in non-dev environments
- The app runs as `appuser` (no shell, no sudo)
- `systemd` hardening flags: `NoNewPrivileges`, `PrivateTmp`, `ProtectSystem`
- Store secrets in Azure Key Vault and reference them via environment variables

---

## Further Reading

- [Getting Started](docs/getting-started.md) — step-by-step setup guide
- [Troubleshooting](docs/troubleshooting.md) — common errors and fixes
- [Code-Only Updates](docs/code-only-updates.md) — updating the app without reprovisioning
- [Architecture Plan](plan/azure-linux-vm-python-deploy.md) — full design document
