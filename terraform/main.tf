# ---------------------------------------------------------------------------
# Locals
# ---------------------------------------------------------------------------

locals {
  tags = {
    environment = var.environment
    managed_by  = "terraform"
    project     = "azure-vm-python"
  }

  # NSG: service tags (VirtualNetwork, Internet, etc.) are only valid on
  # source_address_prefix. source_address_prefixes is CIDR-only; mixing
  # tags with CIDRs in the same rule returns SecurityRuleParameterContainsUnsupportedValue.
  app_nsg_inbound_cidrs = [for p in var.app_inbound_source_prefixes : p if can(cidrnetmask(p))]
  app_nsg_inbound_tags  = [for p in var.app_inbound_source_prefixes : p if !can(cidrnetmask(p))]

  app_nsg_inbound_base_priority      = 110
  app_nsg_inbound_cidr_rule_priority = local.app_nsg_inbound_base_priority + length(local.app_nsg_inbound_tags)
}

# ---------------------------------------------------------------------------
# Resource Group
# ---------------------------------------------------------------------------

resource "azurerm_resource_group" "main" {
  name     = var.resource_group_name
  location = var.location
  tags     = local.tags
}

# ---------------------------------------------------------------------------
# Networking
# ---------------------------------------------------------------------------

resource "azurerm_virtual_network" "main" {
  name                = "vnet-${var.environment}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  address_space       = [var.vnet_address_space]
  tags                = local.tags
}

resource "azurerm_subnet" "app" {
  name                 = "snet-app"
  resource_group_name  = azurerm_resource_group.main.name
  virtual_network_name = azurerm_virtual_network.main.name
  address_prefixes     = [var.subnet_address_prefix]
}

# ---------------------------------------------------------------------------
# Network Security Group
# ---------------------------------------------------------------------------

resource "azurerm_network_security_group" "app" {
  name                = "nsg-app-${var.environment}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  tags                = local.tags

  security_rule {
    name                       = "allow-ssh"
    priority                   = 100
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "22"
    source_address_prefix      = var.ssh_allowed_cidr
    destination_address_prefix = "*"
  }

  # HTTP + app: one rule per service tag, plus one for all CIDRs (see locals).
  dynamic "security_rule" {
    for_each = { for i, t in local.app_nsg_inbound_tags : i => t }
    content {
      name                       = "allow-app-in-${lower(replace(security_rule.value, "*", "any"))}"
      priority                   = local.app_nsg_inbound_base_priority + security_rule.key
      direction                  = "Inbound"
      access                     = "Allow"
      protocol                   = "Tcp"
      source_port_range          = "*"
      source_address_prefix      = security_rule.value
      destination_port_ranges    = [tostring(var.app_port), "80"]
      destination_address_prefix = "*"
    }
  }

  dynamic "security_rule" {
    for_each = length(local.app_nsg_inbound_cidrs) > 0 ? { 0 = true } : {}
    content {
      name                       = "allow-app-in-cidrs"
      priority                   = local.app_nsg_inbound_cidr_rule_priority
      direction                  = "Inbound"
      access                     = "Allow"
      protocol                   = "Tcp"
      source_port_range          = "*"
      source_address_prefixes    = local.app_nsg_inbound_cidrs
      destination_port_ranges    = [tostring(var.app_port), "80"]
      destination_address_prefix = "*"
    }
  }
}

resource "azurerm_subnet_network_security_group_association" "app" {
  subnet_id                 = azurerm_subnet.app.id
  network_security_group_id = azurerm_network_security_group.app.id

  depends_on = [
    azurerm_subnet.app,
    azurerm_network_security_group.app,
  ]
}

# ---------------------------------------------------------------------------
# Public IP
# ---------------------------------------------------------------------------

resource "azurerm_public_ip" "app" {
  name                = "pip-app-${var.environment}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  allocation_method   = "Static"
  sku                 = "Standard"
  tags                = local.tags
}

# ---------------------------------------------------------------------------
# Network Interface
# ---------------------------------------------------------------------------

resource "azurerm_network_interface" "app" {
  name                = "nic-app-${var.environment}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  tags                = local.tags

  ip_configuration {
    name                          = "ipconfig-app"
    subnet_id                     = azurerm_subnet.app.id
    private_ip_address_allocation = "Dynamic"
    public_ip_address_id          = azurerm_public_ip.app.id
  }
}

# ---------------------------------------------------------------------------
# Linux Virtual Machine
# ---------------------------------------------------------------------------

resource "azurerm_linux_virtual_machine" "app_vm" {
  name                = "vm-app-${var.environment}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  size                = var.vm_size
  admin_username      = var.admin_username
  tags                = local.tags

  network_interface_ids = [
    azurerm_network_interface.app.id,
  ]

  admin_ssh_key {
    username   = var.admin_username
    public_key = file(pathexpand(var.ssh_public_key_path))
  }

  os_disk {
    name                 = "osdisk-app-${var.environment}"
    caching              = "ReadWrite"
    storage_account_type = "Premium_LRS"
    disk_size_gb         = var.os_disk_size_gb
  }

  source_image_reference {
    publisher = "Canonical"
    offer     = "ubuntu-24_04-lts"
    sku       = "server"
    version   = "latest"
  }

  # cloud-init script: installs Python, clones the app, and starts it via systemd.
  # templatefile() injects Terraform variables into the YAML template before
  # base64-encoding it as custom_data.
  custom_data = base64encode(templatefile("${path.module}/../scripts/cloud-init.yaml", {
    app_repo                           = var.app_repo_url
    app_port                           = tostring(var.app_port)
    app_env                            = var.environment
    restocking_dtrs_per_batch          = tostring(var.restocking_dtrs_per_batch)
    restocking_fail_rate               = tostring(var.restocking_fail_rate)
    restocking_artefact_retention_days = tostring(var.restocking_artefact_retention_days)
    job_hold_ticks                     = tostring(var.job_hold_ticks)
    job_no_change_prob                 = tostring(var.job_no_change_prob)
  }))

  # Disable password authentication — SSH key only.
  disable_password_authentication = true

  # Boot diagnostics helps diagnose startup / cloud-init failures.
  boot_diagnostics {}
}

# ---------------------------------------------------------------------------
# Azure Monitor Agent (AMA) — optional VM extension
# ---------------------------------------------------------------------------

moved {
  from = azurerm_virtual_machine_extension.azure_monitor_agent
  to   = azurerm_virtual_machine_extension.azure_monitor_agent[0]
}

resource "azurerm_virtual_machine_extension" "azure_monitor_agent" {
  count = var.enable_azure_monitor_agent ? 1 : 0

  name                 = "AzureMonitorLinuxAgent"
  virtual_machine_id   = azurerm_linux_virtual_machine.app_vm.id
  publisher            = "Microsoft.Azure.Monitor"
  type                 = "AzureMonitorLinuxAgent"
  type_handler_version = "1.33"

  auto_upgrade_minor_version = true
  automatic_upgrade_enabled  = true

  tags = local.tags
}

# ---------------------------------------------------------------------------
# Bootstrap Verification
#
# Waits for cloud-init to complete and confirms the app service is active
# before terraform apply returns. Prevents a "success" with a broken app.
# ---------------------------------------------------------------------------

resource "null_resource" "wait_for_app" {
  depends_on = [
    azurerm_linux_virtual_machine.app_vm,
    azurerm_subnet_network_security_group_association.app,
  ]

  triggers = {
    vm_id = azurerm_linux_virtual_machine.app_vm.id
    cloud_init = base64encode(templatefile("${path.module}/../scripts/cloud-init.yaml", {
      app_repo                           = var.app_repo_url
      app_port                           = tostring(var.app_port)
      app_env                            = var.environment
      restocking_dtrs_per_batch          = tostring(var.restocking_dtrs_per_batch)
      restocking_fail_rate               = tostring(var.restocking_fail_rate)
      restocking_artefact_retention_days = tostring(var.restocking_artefact_retention_days)
      job_hold_ticks                     = tostring(var.job_hold_ticks)
      job_no_change_prob                 = tostring(var.job_no_change_prob)
    }))
  }

  connection {
    type        = "ssh"
    host        = azurerm_public_ip.app.ip_address
    user        = var.admin_username
    private_key = file(pathexpand(var.ssh_private_key_path))
    timeout     = "${var.app_startup_timeout}s"
  }

  # One shell: remote-exec runs each list element separately, so a failed
  # is-active was previously masked if a later command exited 0.
  provisioner "remote-exec" {
    inline = [
      "bash -c 'set -euo pipefail; cloud-init status --wait --long; systemctl is-active --quiet app; echo \"ok: app is active\"; systemctl is-active --quiet restocking-generator.timer; systemctl is-active --quiet job-status-generator.timer; systemctl is-active --quiet dtr-cleanup.timer; journalctl -u app -n 20 --no-pager'",
    ]
  }
}
