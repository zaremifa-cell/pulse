#!/usr/bin/env bash
# Creates or updates the whole stack from this machine:
#   1. builds the Lambda package,
#   2. makes sure the S3 bucket for Terraform state exists (infra/bootstrap),
#   3. applies infra/ with its state in that bucket.
# Needs AWS credentials (aws configure) and infra/terraform.tfvars (infra/set-database-url.sh).
set -euo pipefail
cd "$(dirname "$0")"

./build.sh

terraform -chdir=bootstrap init -input=false >/dev/null
terraform -chdir=bootstrap apply -input=false -auto-approve
bucket=$(terraform -chdir=bootstrap output -raw bucket)

terraform init -input=false -reconfigure -backend-config="bucket=$bucket" >/dev/null
terraform apply -input=false -auto-approve

echo
echo "Status page: $(terraform output -raw url)"
