###############################################################################
# IQ Engine — Azure AI Search Index Schema
#
# azurerm_search_index is not yet available in the azurerm provider (as of 4.x).
# We use a null_resource + az CLI to create/update the index idempotently.
# The index JSON is rendered inline; swap for a templatefile() if preferred.
###############################################################################

locals {
  search_index_name = "iq-chunks"

  search_index_json = jsonencode({
    name   = local.search_index_name
    fields = [
      # ── Key ──────────────────────────────────────────────────────────────
      {
        name       = "chunk_id"
        type       = "Edm.String"
        key        = true
        searchable = false
        filterable = true
        sortable   = true
        facetable  = false
        retrievable = true
      },
      # ── Source metadata ──────────────────────────────────────────────────
      {
        name        = "source_type"
        type        = "Edm.String"
        key         = false
        searchable  = true
        filterable  = true
        sortable    = false
        facetable   = true
        retrievable = true
      },
      {
        name        = "source_url"
        type        = "Edm.String"
        key         = false
        searchable  = false
        filterable  = true
        sortable    = false
        facetable   = false
        retrievable = true
      },
      {
        name        = "title"
        type        = "Edm.String"
        key         = false
        searchable  = true
        filterable  = false
        sortable    = true
        facetable   = false
        retrievable = true
        analyzer    = "en.microsoft"
      },
      {
        name        = "published_at"
        type        = "Edm.DateTimeOffset"
        key         = false
        searchable  = false
        filterable  = true
        sortable    = true
        facetable   = false
        retrievable = true
      },
      # ── Content ──────────────────────────────────────────────────────────
      {
        name        = "content"
        type        = "Edm.String"
        key         = false
        searchable  = true
        filterable  = false
        sortable    = false
        facetable   = false
        retrievable = true
        analyzer    = "en.microsoft"
      },
      # ── IQ classification layers ─────────────────────────────────────────
      {
        name        = "iq_layers"
        type        = "Collection(Edm.String)"
        key         = false
        searchable  = true
        filterable  = true
        sortable    = false
        facetable   = true
        retrievable = true
      },
      {
        name        = "azure_services"
        type        = "Collection(Edm.String)"
        key         = false
        searchable  = true
        filterable  = true
        sortable    = false
        facetable   = true
        retrievable = true
      },
      {
        name        = "capabilities"
        type        = "Collection(Edm.String)"
        key         = false
        searchable  = true
        filterable  = true
        sortable    = false
        facetable   = true
        retrievable = true
      },
      {
        name        = "entities"
        type        = "Collection(Edm.String)"
        key         = false
        searchable  = true
        filterable  = true
        sortable    = false
        facetable   = false
        retrievable = true
      },
      # ── Video-specific ───────────────────────────────────────────────────
      {
        name        = "video_id"
        type        = "Edm.String"
        key         = false
        searchable  = false
        filterable  = true
        sortable    = false
        facetable   = false
        retrievable = true
      },
      {
        name        = "video_timestamp"
        type        = "Edm.Int32"
        key         = false
        searchable  = false
        filterable  = false
        sortable    = true
        facetable   = false
        retrievable = true
      },
      # ── Quality & governance ─────────────────────────────────────────────
      {
        name        = "ga_status"
        type        = "Edm.String"
        key         = false
        searchable  = false
        filterable  = true
        sortable    = false
        facetable   = true
        retrievable = true
      },
      {
        name        = "fingerprint"
        type        = "Edm.String"
        key         = false
        searchable  = false
        filterable  = true
        sortable    = false
        facetable   = false
        retrievable = true
      },
      {
        name        = "quality_score"
        type        = "Edm.Double"
        key         = false
        searchable  = false
        filterable  = true
        sortable    = true
        facetable   = false
        retrievable = true
      },
      # ── Audience targeting ───────────────────────────────────────────────
      {
        name        = "target_roles"
        type        = "Collection(Edm.String)"
        key         = false
        searchable  = true
        filterable  = true
        sortable    = false
        facetable   = true
        retrievable = true
      },
      {
        name        = "difficulty"
        type        = "Edm.String"
        key         = false
        searchable  = false
        filterable  = true
        sortable    = true
        facetable   = true
        retrievable = true
      },
      {
        name        = "certification_tags"
        type        = "Collection(Edm.String)"
        key         = false
        searchable  = true
        filterable  = true
        sortable    = false
        facetable   = true
        retrievable = true
      },
      {
        name        = "learn_lab_url"
        type        = "Edm.String"
        key         = false
        searchable  = false
        filterable  = false
        sortable    = false
        facetable   = false
        retrievable = true
      },
      # ── Embedding vector (text-embedding-ada-002 = 1536 dims) ────────────
      {
        name       = "embedding"
        type       = "Collection(Edm.Single)"
        searchable = true
        retrievable = false
        dimensions  = 1536
        vectorSearchProfile = "iq-hnsw-profile"
      }
    ]
    # Vector search configuration
    vectorSearch = {
      profiles = [
        {
          name        = "iq-hnsw-profile"
          algorithmConfigurationName = "iq-hnsw"
        }
      ]
      algorithms = [
        {
          name = "iq-hnsw"
          kind = "hnsw"
          hnswParameters = {
            m              = 4
            efConstruction = 400
            efSearch       = 500
            metric         = "cosine"
          }
        }
      ]
    }
    # Semantic configuration
    semantic = {
      defaultConfiguration = "iq-semantic"
      configurations = [
        {
          name = "iq-semantic"
          prioritizedFields = {
            titleField = { fieldName = "title" }
            contentFields = [
              { fieldName = "content" }
            ]
            keywordsFields = [
              { fieldName = "azure_services" },
              { fieldName = "capabilities" },
              { fieldName = "iq_layers" }
            ]
          }
        }
      ]
    }
  })
}

###############################################################################
# Render the index JSON to a local file so az CLI can read it
###############################################################################
resource "local_file" "search_index_json" {
  content  = local.search_index_json
  filename = "${path.module}/.generated/search-index.json"

  lifecycle {
    # Regenerate only when the schema changes
    create_before_destroy = true
  }
}

###############################################################################
# Apply the index via az REST — idempotent (PUT upserts)
###############################################################################
resource "null_resource" "search_index" {
  triggers = {
    # Re-run whenever the index JSON changes
    index_hash = sha256(local.search_index_json)
    search_id  = azurerm_search_service.search.id
  }

  provisioner "local-exec" {
    command = <<-EOT
      az search index create \
        --resource-group ${azurerm_resource_group.rg.name} \
        --service-name   ${azurerm_search_service.search.name} \
        --name           ${local.search_index_name} \
        --fields-file    "${path.module}/.generated/search-index.json" \
        2>/dev/null || \
      az rest \
        --method PUT \
        --url "https://${azurerm_search_service.search.name}.search.windows.net/indexes/${local.search_index_name}?api-version=2024-07-01" \
        --headers "Content-Type=application/json" \
        --body "@${path.module}/.generated/search-index.json"
    EOT
  }

  depends_on = [
    azurerm_search_service.search,
    local_file.search_index_json
  ]
}

###############################################################################
# Terraform block additions required by this file
###############################################################################
terraform {
  required_providers {
    local = {
      source  = "hashicorp/local"
      version = "~> 2.5"
    }
    null = {
      source  = "hashicorp/null"
      version = "~> 3.2"
    }
  }
}
