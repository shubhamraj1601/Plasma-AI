locals {
  # P-03 (pending): raw spectra in Cloud Storage.
  raw_prefix         = "oes_raw/"
  raw_retention_days = 30
}

resource "google_storage_bucket" "oes_raw" {
  project  = var.project_id
  name     = "${var.project_id}-oes-raw"
  location = var.region

  storage_class               = "STANDARD"
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"

  # Demo data only: `terraform destroy` deletes the bucket with all its objects.
  force_destroy = true

  lifecycle_rule {
    action {
      type = "Delete"
    }
    condition {
      age            = local.raw_retention_days
      matches_prefix = [local.raw_prefix]
    }
  }

  depends_on = [google_project_service.apis]
}
