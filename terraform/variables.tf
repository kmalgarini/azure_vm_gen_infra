# ---------------------------------------------------------------------------
# General
# ---------------------------------------------------------------------------

variable "resource_group_name" {
  description = "Name of the Azure resource group."
  type        = string
  default     = "rg-vm-python"
}

variable "location" {
  description = "Azure region where resources will be deployed."
  type        = string
  default     = "eastus"
}

variable "environment" {
  description = "Deployment environment tag (dev / staging / prod)."
  type        = string
  default     = "dev"

  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "environment must be one of: dev, staging, prod."
  }
}

# ---------------------------------------------------------------------------
# Networking
# ---------------------------------------------------------------------------

variable "vnet_address_space" {
  description = "CIDR block for the virtual network."
  type        = string
  default     = "10.0.0.0/16"
}

variable "subnet_address_prefix" {
  description = "CIDR block for the application subnet."
  type        = string
  default     = "10.0.1.0/24"
}

variable "ssh_allowed_cidr" {
  description = <<-EOT
    CIDR range allowed to SSH into the VM (port 22).
    IMPORTANT: change this to your own public IP or VPN CIDR in production.
    Using 0.0.0.0/0 exposes SSH to the entire internet.
  EOT
  type        = string
  default     = "0.0.0.0/0"
}

variable "app_inbound_source_prefixes" {
  description = <<-EOT
    NSG source prefixes for inbound access to the HTTP / app ports
    (nginx on 80, FastAPI on app_port, both TCP).

    Azure does not support "this subscription only" in an NSG. The usual
    choices are:
      - "VirtualNetwork"  — any address in this VNet and directly peered
        VNets (internal traffic, other VMs in the same VNet, etc. — the
        closest match to in-subscription private access).
      - A /32 of your public IP  — to reach the app on the public IP from
        a laptop. GitHub Actions health checks (outside Azure) will fail
        unless you add the runner CIDR, run health checks from inside the
        VNet, or use a self-hosted runner in the VNet.
    The default locks the app to private VNet traffic only (not the public
    internet).

    Service tags and CIDRs are emitted as separate NSG rules: Azure only
    allows tags on source_address_prefix, not in source_address_prefixes.
  EOT
  type        = list(string)
  default     = ["VirtualNetwork"]

  validation {
    condition     = length(var.app_inbound_source_prefixes) > 0
    error_message = "app_inbound_source_prefixes must contain at least one prefix (e.g. VirtualNetwork or a CIDR)."
  }
}

# ---------------------------------------------------------------------------
# Virtual Machine
# ---------------------------------------------------------------------------

variable "vm_size" {
  description = "Azure VM SKU. Standard_B1s (1 vCPU, 1 GiB) is the smallest SKU that can run Python + nginx reliably. Use Standard_B1ls (0.5 GiB) only if memory is not a concern."
  type        = string
  default     = "Standard_B1s"
}

variable "admin_username" {
  description = "SSH admin username for the VM."
  type        = string
  default     = "azureuser"
}

variable "ssh_public_key_path" {
  description = "Path to the SSH public key file used for VM access."
  type        = string
  default     = "~/.ssh/id_rsa.pub"
}

variable "ssh_private_key_path" {
  description = "Path to the SSH private key file. Used by remote-exec to verify bootstrap completion."
  type        = string
  default     = "~/.ssh/id_rsa"
  sensitive   = true
}

variable "os_disk_size_gb" {
  description = "Size of the OS disk in GB."
  type        = number
  default     = 30
}

variable "enable_azure_monitor_agent" {
  description = <<-EOT
    Install the Azure Monitor Agent as a VM extension. Default is false: the
    Microsoft.Azure.Monitor AzureMonitorLinuxAgent extension often fails on
    Ubuntu 24.04 (e.g. "Unit azuremonitoragent.service could not be found").
    You can use Azure Policy / manual install, switch to a supported image (e.g.
    Ubuntu 22.04 LTS) for the extension, or re-enable this when a compatible
    extension version is available.
  EOT
  type        = bool
  default     = false
}

# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

variable "app_repo_url" {
  description = "Git URL of the Python application to clone onto the VM during first boot."
  type        = string
}

variable "app_port" {
  description = "TCP port the Python application listens on."
  type        = number
  default     = 8000

  validation {
    condition     = var.app_port > 1024 && var.app_port < 65535
    error_message = "app_port must be between 1025 and 65534."
  }
}

variable "app_startup_timeout" {
  description = "Seconds to wait for cloud-init + app startup before failing the apply."
  type        = number
  default     = 600
}

# ---------------------------------------------------------------------------
# Restocking File Generator
# ---------------------------------------------------------------------------

variable "restocking_dtrs_per_batch" {
  description = "Number of DTR numbers written into each BCR batch file per generator tick."
  type        = number
  default     = 3

  validation {
    condition     = var.restocking_dtrs_per_batch >= 1
    error_message = "restocking_dtrs_per_batch must be >= 1."
  }
}

variable "restocking_fail_rate" {
  description = "Probability (0–1) that a DTR lifecycle is abandoned after the 940 is written. Exercises the stale/not_started monitor path."
  type        = number
  default     = 0.05

  validation {
    condition     = var.restocking_fail_rate >= 0 && var.restocking_fail_rate <= 1
    error_message = "restocking_fail_rate must be between 0 and 1."
  }
}

variable "restocking_artefact_retention_days" {
  description = "Number of days to retain DTR artefact files in the restocking inbound directory. Files older than this are deleted daily at 02:00 UTC."
  type        = number
  default     = 7

  validation {
    condition     = var.restocking_artefact_retention_days >= 1
    error_message = "restocking_artefact_retention_days must be >= 1."
  }
}

# ---------------------------------------------------------------------------
# Job Status Generator
# ---------------------------------------------------------------------------

variable "job_hold_ticks" {
  description = "Number of ticks a job remains in a terminal status (COMPLETED/FAILED/CANCELLED) before resetting to PENDING."
  type        = number
  default     = 2

  validation {
    condition     = var.job_hold_ticks >= 0
    error_message = "job_hold_ticks must be >= 0."
  }
}

variable "job_no_change_prob" {
  description = "Probability (0–1, exclusive) that a job does not change status on a given tick. Higher values produce a more stable dataset."
  type        = number
  default     = 0.40

  validation {
    condition     = var.job_no_change_prob >= 0 && var.job_no_change_prob < 1
    error_message = "job_no_change_prob must be in [0, 1)."
  }
}
