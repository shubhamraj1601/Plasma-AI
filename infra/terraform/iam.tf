locals {
  # Project-level roles for now; topic-, bucket- and dataset-level grants are a hardening step.
  service_accounts = {
    "sa-generator" = {
      display_name = "Plasma-AI synthetic generator"
      roles        = ["roles/pubsub.publisher"]
    }
    "sa-dataflow" = {
      display_name = "Plasma-AI Dataflow workers"
      roles = [
        "roles/dataflow.worker",
        "roles/pubsub.subscriber",
        "roles/pubsub.publisher", # dead-letter topic
        "roles/bigquery.dataEditor",
        "roles/bigquery.jobUser",
        "roles/storage.objectAdmin",
      ]
    }
  }

  # One entry per (service account, role), keyed like "sa-dataflow/roles/dataflow.worker".
  service_account_roles = merge([
    for sa, cfg in local.service_accounts : {
      for role in cfg.roles : "${sa}/${role}" => { sa = sa, role = role }
    }
  ]...)
}

# No keys are created: local runs use application-default credentials, Dataflow runs as sa-dataflow.
resource "google_service_account" "sa" {
  for_each = local.service_accounts

  project      = var.project_id
  account_id   = each.key
  display_name = each.value.display_name

  depends_on = [google_project_service.apis]
}

# _member adds this one grant only. Never use _binding or _policy here: they
# would remove other members' roles on the project.
resource "google_project_iam_member" "sa_roles" {
  for_each = local.service_account_roles

  project = var.project_id
  role    = each.value.role
  member  = google_service_account.sa[each.value.sa].member
}
