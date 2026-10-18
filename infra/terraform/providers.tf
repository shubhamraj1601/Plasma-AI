provider "google" {
  project = var.project_id
  region  = var.region

  # The Billing Budgets API needs a quota project when it runs with user
  # credentials (application-default login), so bill API quota to this project.
  user_project_override = true
  billing_project       = var.project_id
}
