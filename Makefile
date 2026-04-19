# ---------------------------------------------------------------------------
# Makefile — common targets for Azure VM Python deployment
# ---------------------------------------------------------------------------

SHELL       := /bin/bash
TF_DIR      := terraform
SCRIPTS_DIR := scripts

# Resolve the VM public IP from Terraform output (requires a previous apply).
PUBLIC_IP   := $(shell cd $(TF_DIR) && terraform output -raw vm_public_ip 2>/dev/null || echo "")
ADMIN_USER  := azureuser
SSH_KEY     := $$HOME/.ssh/id_rsa

.PHONY: help init validate fmt lint plan apply destroy deploy ssh logs status clean

help: ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-18s\033[0m %s\n", $$1, $$2}'

# ---------------------------------------------------------------------------
# Terraform
# ---------------------------------------------------------------------------

init: ## Initialize Terraform (download providers, configure backend)
	cd $(TF_DIR) && terraform init -upgrade

validate: init ## Validate Terraform configuration
	cd $(TF_DIR) && terraform validate

fmt: ## Format all Terraform files
	cd $(TF_DIR) && terraform fmt -recursive

lint: ## Run tflint (requires tflint to be installed)
	cd $(TF_DIR) && tflint --init && tflint

plan: init ## Generate and review an execution plan
	cd $(TF_DIR) && terraform plan -out=tfplan

apply: init ## Apply the Terraform plan (provisions infra + deploys app)
	cd $(TF_DIR) && terraform apply tfplan

apply-auto: init ## Apply without an existing plan file (non-interactive)
	cd $(TF_DIR) && terraform apply -auto-approve

destroy: ## Destroy all provisioned resources
	@echo "WARNING: This will destroy all Azure resources. Press Ctrl-C to cancel."
	@sleep 5
	cd $(TF_DIR) && terraform destroy -auto-approve

output: ## Print Terraform outputs (IP, URL, SSH command)
	cd $(TF_DIR) && terraform output

# ---------------------------------------------------------------------------
# App deployment
# ---------------------------------------------------------------------------

deploy: ## Push a code-only update to the running VM (no infra change)
	@test -n "$(PUBLIC_IP)" || (echo "ERROR: could not resolve vm_public_ip from Terraform output" && exit 1)
	$(SCRIPTS_DIR)/deploy.sh $(PUBLIC_IP) $(ADMIN_USER) $(SSH_KEY)

# ---------------------------------------------------------------------------
# Operations
# ---------------------------------------------------------------------------

ssh: ## Open an SSH session to the VM
	@test -n "$(PUBLIC_IP)" || (echo "ERROR: could not resolve vm_public_ip from Terraform output" && exit 1)
	ssh -i $(SSH_KEY) $(ADMIN_USER)@$(PUBLIC_IP)

logs: ## Stream live app logs from the VM
	@test -n "$(PUBLIC_IP)" || (echo "ERROR: could not resolve vm_public_ip from Terraform output" && exit 1)
	ssh -i $(SSH_KEY) $(ADMIN_USER)@$(PUBLIC_IP) "journalctl -u app -f"

status: ## Check app service status on the VM
	@test -n "$(PUBLIC_IP)" || (echo "ERROR: could not resolve vm_public_ip from Terraform output" && exit 1)
	ssh -i $(SSH_KEY) $(ADMIN_USER)@$(PUBLIC_IP) "systemctl status app --no-pager"

cloud-init-log: ## View the cloud-init bootstrap log on the VM
	@test -n "$(PUBLIC_IP)" || (echo "ERROR: could not resolve vm_public_ip from Terraform output" && exit 1)
	ssh -i $(SSH_KEY) $(ADMIN_USER)@$(PUBLIC_IP) "sudo cat /var/log/cloud-init-output.log"

# ---------------------------------------------------------------------------
# Housekeeping
# ---------------------------------------------------------------------------

clean: ## Remove local Terraform plan file
	rm -f $(TF_DIR)/tfplan
