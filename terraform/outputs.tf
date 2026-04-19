output "vm_public_ip" {
  description = "Public IP address of the virtual machine."
  value       = azurerm_public_ip.app.ip_address
}

output "app_url" {
  description = "HTTP URL of the deployed Python application."
  value       = "http://${azurerm_public_ip.app.ip_address}:${var.app_port}"
}

output "ssh_command" {
  description = "SSH command to connect to the virtual machine."
  value       = "ssh ${var.admin_username}@${azurerm_public_ip.app.ip_address}"
}

output "vm_id" {
  description = "Azure resource ID of the virtual machine."
  value       = azurerm_linux_virtual_machine.app_vm.id
}

output "resource_group_name" {
  description = "Name of the resource group containing all resources."
  value       = azurerm_resource_group.main.name
}
