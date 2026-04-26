# Architecture

Detailed breakdown of every component in the infrastructure, how they connect, and what happens during bootstrap.

---

## Azure Resource Topology

```
Azure Subscription
└── Resource Group: rg-vm-python
    │
    ├── Virtual Network: vnet-app-<env>  (10.0.0.0/16)
    │   └── Subnet: snet-app-<env>       (10.0.1.0/24)
    │       └── NSG: nsg-app-<env>
    │           ├── Inbound rule: port 22  from <ssh_allowed_cidr>
    │           ├── Inbound rule: port 80  from *
    │           └── Inbound rule: port <app_port> from *
    │
    ├── Public IP: pip-app-<env>   (static, Standard SKU)
    │
    ├── Network Interface: nic-app-<env>
    │   ├── attached to: snet-app-<env>
    │   └── assigned:    pip-app-<env>
    │
    ├── Linux Virtual Machine: vm-app-<env>
    │   ├── OS:      Ubuntu 24.04 LTS (Gen 2)
    │   ├── NIC:     nic-app-<env>
    │   ├── Auth:    SSH key only (password disabled)
    │   └── custom_data: rendered cloud-init template
    │
    └── VM Extension: AzureMonitorLinuxAgent
        └── installed on: vm-app-<env>
```

---

## Provisioning Timeline

```
Local machine                          Azure                          VM (Ubuntu 24.04)
─────────────────────────────────────────────────────────────────────────────────────
terraform apply
  │
  ├─ azurerm_resource_group ─────────► create RG
  ├─ azurerm_virtual_network ────────► create VNet
  ├─ azurerm_subnet ─────────────────► create Subnet
  ├─ azurerm_network_security_group ─► create NSG + rules
  ├─ azurerm_subnet_nsg_association ─► associate NSG
  ├─ azurerm_public_ip ──────────────► allocate static PIP
  ├─ azurerm_network_interface ──────► create NIC + attach PIP
  ├─ azurerm_linux_virtual_machine ──► boot VM with custom_data
  │                                                                 cloud-init starts
  │                                                                   apt upgrade
  │                                                                   install: python3 (3.12 on 24.04)
  │                                                                            pip, venv
  │                                                                            git, nginx
  │                                                                   adduser appuser
  │                                                                   git clone → /opt/app
  │                                                                   create .env
  │                                                                   venv + pip install
  │                                                                   write systemd units
  │                                                                   systemctl enable+start:
  │                                                                     app.service
  │                                                                     nginx.service
  │                                                                     restocking-generator.timer
  │                                                                     job-status-generator.timer
  │                                                                   mkdir /var/restocking/inbound
  │                                                                   mkdir /var/jobs
  │                                                                   cloud-init: done ✓
  ├─ azurerm_virtual_machine_extension ► install AzureMonitorLinuxAgent
  │
  └─ null_resource.wait_for_app
       remote-exec:
         cloud-init status --wait     ──────────────────────────► blocks until done
         systemctl is-active app      ──────────────────────────► confirms app running
         systemctl is-active restocking-generator.timer ────────► confirms timer running
         systemctl is-active job-status-generator.timer ────────► confirms timer running
         journalctl -u app -n 20      ──────────────────────────► prints last 20 log lines
       Creation complete ✓

terraform apply exits
```

---

## VM Services (systemd)

All units are injected during cloud-init via `write_files`. The `app/systemd/` directory contains reference copies for local inspection or comparison.

### `app.service` — FastAPI application

```
Type=simple
User=appuser
WorkingDirectory=/opt/app
ExecStart=/opt/app/.venv/bin/uvicorn main:app --host 0.0.0.0 --port <app_port>
EnvironmentFile=/opt/app/.env
Restart=on-failure
```

Hardening flags: `NoNewPrivileges=true`, `PrivateTmp=true`, `ProtectSystem=strict`.

### `restocking-generator.service` + `.timer`

- **Type**: oneshot
- **Schedule**: every 5 minutes
- **Action**: generates BCR-style batch files containing DTR numbers into `/var/restocking/inbound/`
- **Tuning**: `RESTOCKING_DTRS_PER_BATCH`, `RESTOCKING_FAIL_RATE` (from `.env`)

### `job-status-generator.service` + `.timer`

- **Type**: oneshot
- **Schedule**: every 1 minute
- **Action**: advances a probabilistic job state machine, writes `status.json` and appends to `events.jsonl` under `/var/jobs/`
- **Tuning**: `JOB_HOLD_TICKS`, `JOB_NO_CHANGE_PROB` (from `.env`)

---

## nginx Reverse Proxy

nginx listens on port **80** and proxies all traffic to `127.0.0.1:<app_port>`.

```
Internet → port 80 → nginx → 127.0.0.1:<app_port> → uvicorn (app.service)
Internet → port <app_port> → uvicorn (direct, via NSG rule)
```

Inbound to ports 80 and `app_port` is allowed only for sources in `app_inbound_source_prefixes` (by default the **VirtualNetwork** service tag, so the public IP is not open to the whole internet unless you add a CIDR or `0.0.0.0/0`).

Config written to `/etc/nginx/sites-enabled/app` by cloud-init:

```nginx
server {
    listen 80;
    location / {
        proxy_pass http://127.0.0.1:<app_port>;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

---

## Environment File

cloud-init renders `/opt/app/.env` from Terraform variables at bootstrap time:

```ini
APP_PORT=8000
APP_ENV=dev

# Paths for the generator subsystems
RESTOCKING_INBOUND_DIR=/var/restocking/inbound
JOB_DATA_DIR=/var/jobs

# Restocking generator tuning
RESTOCKING_DTRS_PER_BATCH=3
RESTOCKING_FAIL_RATE=0.05

# Job generator tuning
JOB_HOLD_TICKS=2
JOB_NO_CHANGE_PROB=0.40
```

This file is owned by `appuser` and readable only by that user. To update a value without re-provisioning, edit the file on the VM and restart the affected service:

```bash
make ssh
sudo nano /opt/app/.env
sudo systemctl restart app
```

---

## Network Security Group Rules

| Priority | Direction | Protocol | Port | Source | Action |
|----------|-----------|----------|------|--------|--------|
| 100 | Inbound | TCP | 22 | `ssh_allowed_cidr` | Allow |
| 110 | Inbound | TCP | 80, `app_port` | `app_inbound_source_prefixes` (default: `VirtualNetwork` only) | Allow |
| 65000 | Inbound | Any | Any | VirtualNetwork | Allow |
| 65001 | Inbound | Any | Any | AzureLoadBalancer | Allow |
| 65500 | Inbound | Any | Any | `*` | Deny |

Outbound: Azure default rules allow all outbound traffic (required for `apt`, `git clone`, `pip`).

---

## Azure Monitor Agent

The `AzureMonitorLinuxAgent` VM extension is installed by Terraform immediately after the VM is created. It enables:

- OS performance metrics (CPU, memory, disk, network) visible in Azure Monitor
- Log collection routing to a Log Analytics Workspace (if one is configured)
- Alerts and dashboards via Azure Monitor

No additional configuration is required for basic metric collection. To route logs, create a Data Collection Rule in the Azure portal and associate it with the VM.

---

## Filesystem Layout on the VM

```
/opt/app/               ← git clone of app_repo_url
├── main.py
├── requirements.txt
├── .env                ← written by cloud-init, NOT committed to git
├── .venv/              ← Python virtualenv
├── generator/
├── job_generator/
└── ...

/var/restocking/
└── inbound/            ← BCR batch files written every 5 min

/var/jobs/
├── status.json         ← current job status snapshot
└── events.jsonl        ← append-only event log

/etc/nginx/sites-enabled/app   ← nginx proxy config
/etc/systemd/system/
├── app.service
├── restocking-generator.service
├── restocking-generator.timer
├── job-status-generator.service
└── job-status-generator.timer
```

---

## Terraform State

By default Terraform stores state locally in `terraform/terraform.tfstate`. For team or CI use, enable the Azure Blob Storage backend — see [remote-state.md](remote-state.md).
