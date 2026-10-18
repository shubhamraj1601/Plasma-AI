terraform {
  required_version = ">= 1.5.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 8.0"
    }
  }

  # Local state for now (terraform.tfstate in this folder, git-ignored).
  # To move it to Cloud Storage later, see infra/README.md ("State").
}
