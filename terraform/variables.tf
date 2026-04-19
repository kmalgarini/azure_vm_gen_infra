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

# ---------------------------------------------------------------------------
# Virtual Machine
# ---------------------------------------------------------------------------

variable "vm_size" {
  description = "Azure VM SKU. Standard_B2s is cost-effective for dev workloads."
  type        = string
  default     = "Standard_B2s"
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
