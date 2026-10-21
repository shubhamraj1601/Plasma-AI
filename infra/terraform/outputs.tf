output "service_account_emails" {
  description = "Service account emails, by account id."
  value       = { for k, sa in google_service_account.sa : k => sa.email }
}

output "pubsub_topics" {
  description = "Pub/Sub topic names."
  value       = sort([for t in google_pubsub_topic.topics : t.name])
}

output "pubsub_subscriptions" {
  description = "Pub/Sub subscription names, by topic."
  value       = { for k, s in google_pubsub_subscription.subs : k => s.name }
}

output "bucket_name" {
  description = "Cloud Storage bucket for raw OES spectra."
  value       = google_storage_bucket.oes_raw.name
}

output "bigquery_dataset_id" {
  description = "BigQuery dataset id (no tables yet)."
  value       = google_bigquery_dataset.plasma_d1.dataset_id
}
