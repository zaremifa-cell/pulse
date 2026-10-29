variable "region" {
  description = "AWS region for every resource."
  type        = string
  default     = "eu-central-1"
}

variable "database_url" {
  description = "PostgreSQL URL. Set it with infra/set-database-url.sh, which writes the git-ignored terraform.tfvars."
  type        = string
  sensitive   = true
}

variable "github_repository" {
  description = "owner/name of the repository whose main branch may deploy."
  type        = string
  default     = "zaremifa-cell/pulse"
}
