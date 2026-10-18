resource "google_bigquery_dataset" "plasma_d1" {
  project     = var.project_id
  dataset_id  = "plasma_d1"
  location    = var.region
  description = "Plasma-AI D1 data (tables from Day 11)"

  # Demo data only: `terraform destroy` deletes the dataset with any tables in it.
  delete_contents_on_destroy = true

  depends_on = [google_project_service.apis]
}

# Day 11 hook: tables and views go here once the schema is frozen (designs in the
# plan doc, tab ST2). Do not add them before then. Shape, for reference only:
#
# resource "google_bigquery_table" "process_ts" {
#   project             = var.project_id
#   dataset_id          = google_bigquery_dataset.plasma_d1.dataset_id
#   table_id            = "process_ts"
#   deletion_protection = false
#   schema              = file("${path.module}/bq_schemas/process_ts.json")
#
#   time_partitioning {
#     type  = "DAY"
#     field = "event_ts"
#   }
# }
