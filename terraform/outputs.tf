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

output "remote_bootstrap_file" {
  description = "Path to the locally rendered app bootstrap script (from remote_bootstrap.sh.tftpl). `cat` it to verify what Terraform will upload in apply step 2."
  value       = abspath(local_file.remote_bootstrap.filename)
}

output "remote_bootstrap_sha256" {
  description = "Hex sha256 of the rendered app bootstrap. Compare with `shasum -a 256` on that file to confirm the template is loaded."
  # Script may embed a PAT; the digest is safe to print.
  value = nonsensitive(sha256(local.remote_bootstrap_script))
}

output "manual_verification_cmd" {
  description = "After /opt/app exists (Terraform bootstrap or your own), run on the VM to re-check app, venv, systemd, and /health."
  value       = "sudo bash /opt/app/scripts/verify_on_vm.sh"
}
