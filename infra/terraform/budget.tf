locals {
  budget_name = "plasma-ai-budget"
}

# The budget filter takes the project number, not the id.
data "google_project" "this" {
  project_id = var.project_id

  depends_on = [google_project_service.apis]
}

# Optional extra recipient. Billing account admins and users get budget mail either way.
resource "google_monitoring_notification_channel" "budget_email" {
  count = var.alert_email == "" ? 0 : 1

  project      = var.project_id
  display_name = "${local.budget_name}-email"
  type         = "email"
  labels = {
    email_address = var.alert_email
  }

  depends_on = [google_project_service.apis]
}

# Alerts only notify. They do not stop spending.
resource "google_billing_budget" "project" {
  billing_account = var.billing_account
  display_name    = local.budget_name

  budget_filter {
    projects = ["projects/${data.google_project.this.number}"]
  }

  amount {
    specified_amount {
      currency_code = "USD"
      units         = tostring(var.budget_usd)
    }
  }

  dynamic "threshold_rules" {
    for_each = var.alert_thresholds
    content {
      threshold_percent = threshold_rules.value
      spend_basis       = "CURRENT_SPEND"
    }
  }

  dynamic "all_updates_rule" {
    for_each = google_monitoring_notification_channel.budget_email
    content {
      monitoring_notification_channels = [all_updates_rule.value.id]
      disable_default_iam_recipients   = false
    }
  }

  depends_on = [google_project_service.apis]
}
