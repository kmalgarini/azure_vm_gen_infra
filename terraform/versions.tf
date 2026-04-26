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
    local = {
      source  = "hashicorp/local"
      version = "~> 2.5"
    }
  }

  # Uncomment to store state remotely in Azure Blob Storage.
  # backend "azurerm" {
  #   resource_group_name  = "rg-tfstate"
  #   storage_account_name = "tfstate<unique_suffix>"
  #   container_name       = "tfstate"
  #   key                  = "azure-vm-python.tfstate"
  # }
}

provider "azurerm" {
  features {}
}
