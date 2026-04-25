# Remote State

How to store Terraform state in Azure Blob Storage so that multiple developers and CI pipelines share a single source of truth.

---

## Why Remote State

By default Terraform writes `terraform/terraform.tfstate` locally. This causes problems when:

- Multiple people work on the same infrastructure
- CI (GitHub Actions) needs to run `terraform apply`
- You lose or rotate your local machine
- You need state locking to prevent concurrent applies

Azure Blob Storage provides **free, durable, encrypted storage** with **lease-based locking** built into the AzureRM backend.

---

## 1. Create the Storage Resources

Run this once before enabling the backend. Use a unique storage account name (3–24 lowercase letters/digits).

```bash
# Variables — adjust as needed
RG="rg-tfstate"
SA="tfstate$(openssl rand -hex 4)"   # e.g. tfstate1a2b3c4d
CONTAINER="tfstate"
LOCATION="eastus"

# Create resource group
az group create \
  --name "$RG" \
  --location "$LOCATION"

# Create storage account
# Standard_LRS is sufficient; ZRS/GRS adds redundancy for production
az storage account create \
  --name "$SA" \
  --resource-group "$RG" \
  --location "$LOCATION" \
  --sku Standard_LRS \
  --kind StorageV2 \
  --allow-blob-public-access false \
  --min-tls-version TLS1_2

# Create blob container
az storage container create \
  --name "$CONTAINER" \
  --account-name "$SA"

# Print the values you'll need for the backend config
echo "storage_account_name = \"$SA\""
```

---

## 2. Enable the Backend in versions.tf

Uncomment the `backend "azurerm"` block in `terraform/versions.tf` and fill in the values from the step above:

```hcl
terraform {
  required_version = ">= 1.7"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.110"
    }
    null = {
      source  = "hashicorp/null"
      version = "~> 3.2"
    }
  }

  backend "azurerm" {
    resource_group_name  = "rg-tfstate"
    storage_account_name = "tfstate1a2b3c4d"   # your unique name
    container_name       = "tfstate"
    key                  = "azure-vm-python.tfstate"
  }
}
```

> Use a different `key` per environment:
> - dev: `azure-vm-python-dev.tfstate`
> - staging: `azure-vm-python-staging.tfstate`
> - prod: `azure-vm-python-prod.tfstate`

---

## 3. Migrate Local State

```bash
make init
```

Terraform detects the new backend and offers to migrate your existing local state to Blob Storage. Accept when prompted:

```
Do you want to copy existing state to the new backend?
  Pre-existing state was found while migrating the previous "local" backend
  to the newly configured "azurerm" backend. No existing state was found in
  the newly configured "azurerm" backend. Do you want to copy this state to
  the new backend? Enter "yes" to copy and "no" to start with an empty state.

  Enter a value: yes
```

After migration, `terraform/terraform.tfstate` is no longer used. You can delete it (it's already in `.gitignore`).

---

## 4. Verify

```bash
# Confirm state is in Azure
az storage blob list \
  --account-name "tfstate1a2b3c4d" \
  --container-name "tfstate" \
  --output table

# Run a plan — should succeed with no local state file
make plan
```

---

## 5. Set Up Authentication for the Backend

### Local development (az login)

After `az login`, Terraform uses your active Azure CLI credentials automatically — no extra config needed.

### CI / GitHub Actions

The backend needs to authenticate separately from the provider. Add these four secrets to your GitHub repository (Settings → Secrets and variables → Actions):

| Secret | Value |
|--------|-------|
| `ARM_CLIENT_ID` | Service principal app ID |
| `ARM_CLIENT_SECRET` | Service principal secret |
| `ARM_TENANT_ID` | Azure tenant ID |
| `ARM_SUBSCRIPTION_ID` | Azure subscription ID |

Example workflow step:

```yaml
- name: Terraform Init
  run: cd terraform && terraform init
  env:
    ARM_CLIENT_ID:       ${{ secrets.ARM_CLIENT_ID }}
    ARM_CLIENT_SECRET:   ${{ secrets.ARM_CLIENT_SECRET }}
    ARM_TENANT_ID:       ${{ secrets.ARM_TENANT_ID }}
    ARM_SUBSCRIPTION_ID: ${{ secrets.ARM_SUBSCRIPTION_ID }}
```

The service principal must have at least **Contributor** on the main subscription (to manage Azure resources) and **Storage Blob Data Contributor** on the `rg-tfstate` storage account (to read/write state).

---

## 6. State Locking

The AzureRM backend uses blob leases for state locking. If a lock is stuck (e.g. a CI job was killed mid-apply):

```bash
# List active leases (find the lock ID in the error output from terraform)
cd terraform && terraform force-unlock <lock-id>
```

---

## Multiple Environments

To manage dev, staging, and prod from the same codebase, use **Terraform workspaces** or separate `tfvars` files with distinct state keys.

### Option A — Separate state keys (recommended)

Keep a `terraform.tfvars` per environment and run with `-var-file`:

```
terraform/
├── envs/
│   ├── dev.tfvars
│   ├── staging.tfvars
│   └── prod.tfvars
└── versions.tf       # backend key = "azure-vm-python-${workspace}.tfstate"
```

Pass the right file at plan/apply time:

```bash
terraform plan  -var-file="envs/prod.tfvars"
terraform apply -var-file="envs/prod.tfvars"
```

Update the `key` in the backend to include the environment name:

```hcl
backend "azurerm" {
  resource_group_name  = "rg-tfstate"
  storage_account_name = "tfstate1a2b3c4d"
  container_name       = "tfstate"
  key                  = "azure-vm-python-prod.tfstate"
}
```

### Option B — Terraform workspaces

```bash
terraform workspace new prod
terraform workspace select prod
terraform plan -var-file="envs/prod.tfvars"
```

State is stored at `azure-vm-python.tfstate/env:prod` inside the container.

---

## Hardening the State Storage Account

For production, apply these additional controls:

```bash
# Enable versioning (protects against accidental state deletion)
az storage account blob-service-properties update \
  --account-name "tfstate1a2b3c4d" \
  --enable-versioning true

# Enable soft delete (14-day retention)
az storage account blob-service-properties update \
  --account-name "tfstate1a2b3c4d" \
  --enable-delete-retention true \
  --delete-retention-days 14

# Restrict network access to your CI runner IP or VNet
az storage account update \
  --name "tfstate1a2b3c4d" \
  --default-action Deny

az storage account network-rule add \
  --account-name "tfstate1a2b3c4d" \
  --ip-address "<your_ci_ip>"
```
