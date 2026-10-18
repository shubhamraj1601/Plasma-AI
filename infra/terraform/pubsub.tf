locals {
  # P-04 (pending): two topics plus dead-letter. Must match `topics:` in config/generator.yaml.
  topics = toset(["process-ts", "oes-spectra", "dead-letter"])
}

resource "google_pubsub_topic" "topics" {
  for_each = local.topics

  project = var.project_id
  name    = each.value

  depends_on = [google_project_service.apis]
}

# One subscription per topic, named <topic>-sub (same rule as `python -m plasma_ai.emulator setup`).
resource "google_pubsub_subscription" "subs" {
  for_each = google_pubsub_topic.topics

  project = var.project_id
  name    = "${each.value.name}-sub"
  topic   = each.value.id

  # By default a subscription expires after 31 idle days; an empty ttl means never.
  expiration_policy {
    ttl = ""
  }
}
