variable "project_id" {
  description = "GCP project id, e.g. plasma-ai-d1. The project and its billing link are made by hand (infra/README.md, step 0)."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]$", var.project_id))
    error_message = "The project_id must be 6-30 characters: lowercase letters, digits and hyphens, starting with a letter."
  }
}

variable "billing_account" {
  description = "Billing account id, format 000000-000000-000000 (gcloud billing accounts list)."
  type        = string

  validation {
    condition     = can(regex("^[0-9A-F]{6}-[0-9A-F]{6}-[0-9A-F]{6}$", var.billing_account))
    error_message = "The billing_account must look like 000000-000000-000000 (digits and uppercase A-F)."
  }
}

variable "region" {
  description = "Region for the bucket and the BigQuery dataset (P-07, pending)."
  type        = string
  default     = "us-central1"
}

variable "budget_usd" {
  description = "Monthly budget in USD (Q2 assumption)."
  type        = number
  default     = 200

  validation {
    condition     = var.budget_usd > 0 && floor(var.budget_usd) == var.budget_usd
    error_message = "The budget_usd must be a positive whole number."
  }
}

variable "alert_thresholds" {
  description = "Budget alert thresholds as a share of the budget (1.0 = 100 %), on current (actual) spend."
  type        = list(number)
  default     = [0.5, 0.8, 1.0]

  validation {
    condition     = length(var.alert_thresholds) > 0 && alltrue([for t in var.alert_thresholds : t > 0])
    error_message = "The alert_thresholds need at least one value, each greater than 0."
  }
}

variable "alert_email" {
  description = "Optional extra recipient for budget mail. Billing account admins and users always get it; this adds a Cloud Monitoring email channel."
  type        = string
  default     = ""

  validation {
    condition     = var.alert_email == "" || can(regex("^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$", var.alert_email))
    error_message = "The alert_email must be empty or an email address."
  }
}
