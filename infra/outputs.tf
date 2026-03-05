###############################################################################
# IQ Engine — Terraform Outputs
###############################################################################

output "ai_search_endpoint" {
  description = "Azure AI Search service endpoint URL."
  value       = "https://${azurerm_search_service.search.name}.search.windows.net"
}

output "storage_account_name" {
  description = "Name of the Storage Account (Table + Blob)."
  value       = azurerm_storage_account.storage.name
}

output "redis_hostname" {
  description = "Azure Cache for Redis hostname."
  value       = azurerm_redis_cache.redis.hostname
}

output "key_vault_uri" {
  description = "Azure Key Vault URI."
  value       = azurerm_key_vault.kv.vault_uri
}

output "container_app_url" {
  description = "Container App ingress FQDN (HTTPS)."
  value       = "https://${azurerm_container_app.app.ingress[0].fqdn}"
}

output "app_insights_connection_string" {
  description = "Application Insights connection string."
  value       = azurerm_application_insights.appi.connection_string
  sensitive   = true
}

output "app_insights_availability_test_name" {
  description = "Name of the Application Insights availability test for the /health endpoint."
  value       = azurerm_application_insights_standard_web_test.health_ping.name
}

output "service_bus_namespace_endpoint" {
  description = "Service Bus namespace endpoint."
  value       = "${azurerm_servicebus_namespace.sb.name}.servicebus.windows.net"
}

output "resource_group_name" {
  description = "Name of the resource group containing all IQ Engine resources."
  value       = azurerm_resource_group.rg.name
}
