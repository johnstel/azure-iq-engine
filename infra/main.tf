###############################################################################
# IQ Engine — Azure Infrastructure
# All resources share common tags: project + environment
###############################################################################

locals {
  tags = {
    project     = "iq-engine"
    environment = var.environment
    managed_by  = "terraform"
  }
}

###############################################################################
# Random suffix — keeps storage account names globally unique
###############################################################################
resource "random_id" "storage_suffix" {
  byte_length = 4
}

###############################################################################
# Resource Group
###############################################################################
resource "azurerm_resource_group" "rg" {
  name     = "rg-${var.project_name}-${var.environment}"
  location = var.location
  tags     = local.tags
}

###############################################################################
# Log Analytics Workspace
###############################################################################
resource "azurerm_log_analytics_workspace" "law" {
  name                = "law-${var.project_name}-${var.environment}"
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
  sku                 = "PerGB2018"
  retention_in_days   = 30
  tags                = local.tags
}

###############################################################################
# Application Insights
###############################################################################
resource "azurerm_application_insights" "appi" {
  name                = "appi-${var.project_name}-${var.environment}"
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
  workspace_id        = azurerm_log_analytics_workspace.law.id
  application_type    = "web"
  tags                = local.tags
}

###############################################################################
# Application Insights Availability Test — ping /health every 5 minutes
###############################################################################
resource "azurerm_application_insights_standard_web_test" "health_ping" {
  name                    = "avt-${var.project_name}-${var.environment}-health"
  resource_group_name     = azurerm_resource_group.rg.name
  location                = azurerm_resource_group.rg.location
  application_insights_id = azurerm_application_insights.appi.id
  geo_locations           = ["us-tx-sn1-azr", "us-il-ch1-azr", "us-va-ash-azr"]
  enabled                 = true
  frequency               = 300  # seconds (every 5 minutes)
  timeout                 = 30   # seconds

  request {
    url = "https://${azurerm_container_app.app.ingress[0].fqdn}/health"
  }

  validation_rules {
    expected_status_code = 200
  }

  tags = local.tags
}

###############################################################################
# Azure AI Search — Basic tier
###############################################################################
resource "azurerm_search_service" "search" {
  name                = "srch-${var.project_name}-${var.environment}"
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
  sku                 = "basic"
  replica_count       = 1
  partition_count     = 1
  tags                = local.tags

  lifecycle {
    prevent_destroy = false
  }
}

###############################################################################
# Storage Account — Standard LRS (Table + Blob)
###############################################################################
resource "azurerm_storage_account" "storage" {
  name                     = "stiqengine${var.environment}${random_id.storage_suffix.hex}"
  resource_group_name      = azurerm_resource_group.rg.name
  location                 = azurerm_resource_group.rg.location
  account_tier             = "Standard"
  account_replication_type = "LRS"
  account_kind             = "StorageV2"
  min_tls_version          = "TLS1_2"

  blob_properties {
    versioning_enabled = false
  }

  tags = local.tags
}

# Blob container for raw ingested content
resource "azurerm_storage_container" "raw" {
  name                  = "raw-content"
  storage_account_id    = azurerm_storage_account.storage.id
  container_access_type = "private"
}

# Table for lightweight metadata / state tracking
resource "azurerm_storage_table" "metadata" {
  name               = "iqmetadata"
  storage_account_id = azurerm_storage_account.storage.id
}

###############################################################################
# Azure Cache for Redis — Basic C1 (1 GB)
###############################################################################
resource "azurerm_redis_cache" "redis" {
  name                = "redis-${var.project_name}-${var.environment}"
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
  capacity            = 1
  family              = "C"
  sku_name            = "Basic"
  non_ssl_port_enabled = false
  minimum_tls_version = "1.2"

  redis_configuration {}

  tags = local.tags
}

###############################################################################
# Azure Service Bus — Basic tier + DLQ queue
###############################################################################
resource "azurerm_servicebus_namespace" "sb" {
  name                = "sb-${var.project_name}-${var.environment}"
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
  sku                 = "Basic"
  tags                = local.tags
}

resource "azurerm_servicebus_queue" "ingestion_dlq" {
  name         = "ingestion-dlq"
  namespace_id = azurerm_servicebus_namespace.sb.id

  # Basic tier does not support sessions or partitioning beyond defaults
  max_delivery_count = 10
}

###############################################################################
# Azure Key Vault — Standard
###############################################################################
data "azurerm_client_config" "current" {}

resource "azurerm_key_vault" "kv" {
  name                        = "kv-${var.project_name}-${var.environment}"
  resource_group_name         = azurerm_resource_group.rg.name
  location                    = azurerm_resource_group.rg.location
  tenant_id                   = data.azurerm_client_config.current.tenant_id
  sku_name                    = "standard"
  soft_delete_retention_days  = 7
  purge_protection_enabled    = false # Set true for prod

  # Deploying identity gets full access — tighten in prod
  access_policy {
    tenant_id = data.azurerm_client_config.current.tenant_id
    object_id = data.azurerm_client_config.current.object_id

    secret_permissions = [
      "Get", "List", "Set", "Delete", "Purge", "Recover"
    ]
    key_permissions = [
      "Get", "List", "Create", "Delete", "Purge", "Recover"
    ]
  }

  tags = local.tags
}

###############################################################################
# Container Apps Environment (Consumption plan)
###############################################################################
resource "azurerm_container_app_environment" "cae" {
  name                       = "cae-${var.project_name}-${var.environment}"
  resource_group_name        = azurerm_resource_group.rg.name
  location                   = azurerm_resource_group.rg.location
  log_analytics_workspace_id = azurerm_log_analytics_workspace.law.id
  tags                       = local.tags
}

###############################################################################
# Container App — IQ Engine API (placeholder image)
###############################################################################
resource "azurerm_container_app" "app" {
  name                         = "ca-${var.project_name}-${var.environment}"
  resource_group_name          = azurerm_resource_group.rg.name
  container_app_environment_id = azurerm_container_app_environment.cae.id
  revision_mode                = "Single"
  tags                         = local.tags

  template {
    container {
      name   = "iq-engine"
      image  = "mcr.microsoft.com/azuredocs/containerapps-helloworld:latest"
      cpu    = 0.5
      memory = "1Gi"

      env {
        name  = "APPLICATIONINSIGHTS_CONNECTION_STRING"
        value = azurerm_application_insights.appi.connection_string
      }

      env {
        name  = "AZURE_SEARCH_ENDPOINT"
        value = "https://${azurerm_search_service.search.name}.search.windows.net"
      }

      env {
        name  = "STORAGE_ACCOUNT_NAME"
        value = azurerm_storage_account.storage.name
      }
    }

    min_replicas = 0
    max_replicas = 3
  }

  ingress {
    external_enabled = true
    target_port      = 80

    traffic_weight {
      percentage      = 100
      latest_revision = true
    }
  }

  identity {
    type = "SystemAssigned"
  }
}

###############################################################################
# Grant Container App managed identity read access to Key Vault
###############################################################################
resource "azurerm_key_vault_access_policy" "app_identity" {
  key_vault_id = azurerm_key_vault.kv.id
  tenant_id    = data.azurerm_client_config.current.tenant_id
  object_id    = azurerm_container_app.app.identity[0].principal_id

  secret_permissions = ["Get", "List"]
}
