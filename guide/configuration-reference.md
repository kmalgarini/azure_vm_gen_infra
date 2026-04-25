# Configuration Reference

Complete reference for every Terraform variable. All variables are set in `terraform/terraform.tfvars` (gitignored).

---

## Quick Start Template

Copy this into `terraform/terraform.tfvars` and fill in the values marked `# required`:

```hcl
# ── Required ─────────────────────────────────────────────────────────────────
app_repo_url = "https://github.com/<org>/<repo>.git"   # required

# ── General ──────────────────────────────────────────────────────────────────
resource_group_name = "rg-vm-python"
location            = "eastus"
environment         = "dev"

# ── Networking ───────────────────────────────────────────────────────────────
vnet_address_space    = "10.0.0.0/16"
subnet_address_prefix = "10.0.1.0/24"
ssh_allowed_cidr      = "0.0.0.0/0"      # CHANGE in prod: use your IP/VPN CIDR

# ── Virtual Machine ───────────────────────────────────────────────────────────
vm_size              = "Standard_B1s"
admin_username       = "azureuser"
ssh_public_key_path  = "~/.ssh/id_rsa.pub"
ssh_private_key_path = "~/.ssh/id_rsa"
os_disk_size_gb      = 30

# ── Application ───────────────────────────────────────────────────────────────
app_port            = 8000
app_startup_timeout = 600

# ── Restocking File Generator ─────────────────────────────────────────────────
restocking_dtrs_per_batch = 3
restocking_fail_rate      = 0.05

# ── Job Status Generator ──────────────────────────────────────────────────────
job_hold_ticks     = 2
job_no_change_prob = 0.40
```

---

## General

### `resource_group_name`

| | |
|-|-|
| Type | `string` |
| Default | `"rg-vm-python"` |
| Required | No |

Name of the Azure resource group that contains all provisioned resources. If the group doesn't exist Terraform creates it; if it already exists Terraform imports it.

```hcl
resource_group_name = "rg-myapp-prod"
```

---

### `location`

| | |
|-|-|
| Type | `string` |
| Default | `"eastus"` |
| Required | No |

Azure region for all resources. All resources are placed in the same region.

Common values: `eastus`, `eastus2`, `westus2`, `westeurope`, `northeurope`, `australiaeast`.

```hcl
location = "westeurope"
```

---

### `environment`

| | |
|-|-|
| Type | `string` |
| Default | `"dev"` |
| Required | No |
| Valid values | `dev`, `staging`, `prod` |

Tags all resources and is used as a suffix in resource names (e.g. `vm-app-prod`). Validation rejects any other value.

```hcl
environment = "prod"
```

---

## Networking

### `vnet_address_space`

| | |
|-|-|
| Type | `string` |
| Default | `"10.0.0.0/16"` |
| Required | No |

CIDR block for the Azure Virtual Network. The subnet (`subnet_address_prefix`) must be a subset of this range.

```hcl
vnet_address_space = "172.16.0.0/16"
```

---

### `subnet_address_prefix`

| | |
|-|-|
| Type | `string` |
| Default | `"10.0.1.0/24"` |
| Required | No |

CIDR block for the application subnet within the VNet. The VM NIC is placed in this subnet.

```hcl
subnet_address_prefix = "172.16.1.0/24"
```

---

### `ssh_allowed_cidr`

| | |
|-|-|
| Type | `string` |
| Default | `"0.0.0.0/0"` |
| Required | No |

CIDR range allowed to reach the VM on **port 22** (SSH). The default `0.0.0.0/0` permits connections from any IP; this is acceptable for development but must be restricted in production.

```hcl
# Your current public IP (curl ifconfig.me to find it)
ssh_allowed_cidr = "203.0.113.42/32"

# Your VPN or office CIDR
ssh_allowed_cidr = "10.10.0.0/16"
```

> Port 80 and `app_port` are open to `*` by default. To restrict app access to specific CIDRs, edit the NSG rules in `terraform/main.tf`.

---

## Virtual Machine

### `vm_size`

| | |
|-|-|
| Type | `string` |
| Default | `"Standard_B1s"` |
| Required | No |

Azure VM SKU. The app (uvicorn), nginx, and the two generator timers run comfortably on `Standard_B1s` (1 vCPU, 1 GiB RAM).

| SKU | vCPUs | RAM | Typical use |
|-----|-------|-----|-------------|
| `Standard_B1s` | 1 | 1 GiB | dev / light workloads |
| `Standard_B2s` | 2 | 4 GiB | moderate load |
| `Standard_B4ms` | 4 | 16 GiB | production |
| `Standard_D2s_v5` | 2 | 8 GiB | production (non-burstable) |

```hcl
vm_size = "Standard_B4ms"
```

---

### `admin_username`

| | |
|-|-|
| Type | `string` |
| Default | `"azureuser"` |
| Required | No |

SSH admin username for the VM. Used by `make ssh`, `make deploy`, and the `null_resource` remote-exec.

```hcl
admin_username = "deployer"
```

---

### `ssh_public_key_path`

| | |
|-|-|
| Type | `string` |
| Default | `"~/.ssh/id_rsa.pub"` |
| Required | No |

Path to the SSH public key file. Terraform reads the file and injects its contents into the VM's `authorized_keys`.

```hcl
ssh_public_key_path = "~/.ssh/azure_vm.pub"
```

---

### `ssh_private_key_path`

| | |
|-|-|
| Type | `string` |
| Default | `"~/.ssh/id_rsa"` |
| Required | No |
| Sensitive | Yes (not written to plan output) |

Path to the SSH private key file. Used only by the `null_resource.wait_for_app` remote-exec connection to verify bootstrap completion. Must correspond to `ssh_public_key_path`.

```hcl
ssh_private_key_path = "~/.ssh/azure_vm"
```

---

### `os_disk_size_gb`

| | |
|-|-|
| Type | `number` |
| Default | `30` |
| Required | No |

OS disk size in GB. The default 30 GB is sufficient for the OS + Python app. Increase this if your app writes substantial data locally.

```hcl
os_disk_size_gb = 64
```

---

## Application

### `app_repo_url` *(required)*

| | |
|-|-|
| Type | `string` |
| Default | none |
| Required | **Yes** |

Git URL of the Python application repository. cloud-init clones this URL into `/opt/app` on first boot.

```hcl
# Public HTTPS repo
app_repo_url = "https://github.com/myorg/myapp.git"

# SSH repo (requires deploy key in cloud-init)
app_repo_url = "git@github.com:myorg/myapp.git"
```

The repository must contain:

- `requirements.txt` at the root (pip installs from this)
- An application entry point that binds to `0.0.0.0:$APP_PORT` (the `app.service` unit starts uvicorn)

---

### `app_port`

| | |
|-|-|
| Type | `number` |
| Default | `8000` |
| Required | No |
| Validation | Must be between 1025 and 65534 |

TCP port the Python application listens on. This value is:

- Set in `/opt/app/.env` as `APP_PORT`
- Passed to uvicorn via the systemd unit
- Added as an inbound NSG rule
- Used in the nginx `proxy_pass` target
- Shown in the `app_url` Terraform output

```hcl
app_port = 5000
```

---

### `app_startup_timeout`

| | |
|-|-|
| Type | `number` |
| Default | `600` |
| Required | No |

Maximum seconds the `null_resource.wait_for_app` remote-exec will wait for cloud-init to finish and the app service to become active. Increase this on slow networks or if your `requirements.txt` is large.

```hcl
app_startup_timeout = 900   # 15 minutes
```

---

## Restocking File Generator

These variables tune the `restocking-generator.timer` that runs every 5 minutes on the VM.

### `restocking_dtrs_per_batch`

| | |
|-|-|
| Type | `number` |
| Default | `3` |
| Required | No |
| Validation | Must be ≥ 1 |

Number of DTR numbers written into each BCR batch file per generator tick. A higher value produces larger, more data-rich batch files; useful for load testing downstream consumers.

```hcl
restocking_dtrs_per_batch = 10
```

---

### `restocking_fail_rate`

| | |
|-|-|
| Type | `number` |
| Default | `0.05` |
| Required | No |
| Validation | Must be in [0, 1] |

Probability (0–1) that a DTR lifecycle is abandoned after the 940 file is written, simulating the `stale` / `not_started` monitor path. Set to `0` for a clean success-only dataset; set higher (e.g. `0.20`) to stress-test alerting on stale records.

```hcl
restocking_fail_rate = 0.10   # 10% abandoned lifecycles
```

---

## Job Status Generator

These variables tune the `job-status-generator.timer` that runs every 1 minute on the VM.

### `job_hold_ticks`

| | |
|-|-|
| Type | `number` |
| Default | `2` |
| Required | No |
| Validation | Must be ≥ 0 |

Number of ticks a job remains in a terminal status (`COMPLETED`, `FAILED`, `CANCELLED`) before resetting to `PENDING`. Increase this to produce longer-lived terminal states (useful when monitoring for jobs stuck in a terminal status).

```hcl
job_hold_ticks = 5   # jobs stay terminal for 5 minutes before recycling
```

---

### `job_no_change_prob`

| | |
|-|-|
| Type | `number` |
| Default | `0.40` |
| Required | No |
| Validation | Must be in [0, 1) |

Probability (0–1, exclusive) that a job does not change status on a given tick. Higher values produce a more stable, slowly-changing dataset. Lower values produce rapid churn, useful for testing real-time consumers.

```hcl
job_no_change_prob = 0.70   # stable dataset, few changes per minute
job_no_change_prob = 0.10   # high churn dataset
```

---

## Environment-Specific Examples

### Development

```hcl
app_repo_url        = "https://github.com/myorg/myapp.git"
resource_group_name = "rg-vm-python-dev"
environment         = "dev"
location            = "eastus"
vm_size             = "Standard_B1s"
ssh_allowed_cidr    = "0.0.0.0/0"
```

### Staging

```hcl
app_repo_url        = "https://github.com/myorg/myapp.git"
resource_group_name = "rg-vm-python-staging"
environment         = "staging"
location            = "eastus"
vm_size             = "Standard_B2s"
ssh_allowed_cidr    = "10.10.0.0/16"   # VPN only

restocking_dtrs_per_batch = 5
restocking_fail_rate      = 0.05
job_hold_ticks            = 2
job_no_change_prob        = 0.40
```

### Production

```hcl
app_repo_url        = "https://github.com/myorg/myapp.git"
resource_group_name = "rg-vm-python-prod"
environment         = "prod"
location            = "eastus"
vm_size             = "Standard_B4ms"
os_disk_size_gb     = 64
ssh_allowed_cidr    = "10.10.0.0/16"   # VPN only

app_startup_timeout = 900

restocking_dtrs_per_batch = 10
restocking_fail_rate      = 0.02
job_hold_ticks            = 3
job_no_change_prob        = 0.50
```

---

## Variable Precedence

Terraform applies values in this order (later sources win):

1. Variable defaults in `variables.tf`
2. `terraform.tfvars`
3. `*.auto.tfvars` files (alphabetical order)
4. `-var` flags on the command line
5. `TF_VAR_<name>` environment variables

To override a single variable without editing `terraform.tfvars`:

```bash
terraform plan -var="vm_size=Standard_B4ms"
terraform apply -var="ssh_allowed_cidr=203.0.113.42/32"
```
