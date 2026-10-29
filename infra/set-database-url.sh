#!/usr/bin/env bash
# Saves the PostgreSQL URL to infra/terraform.tfvars (ignored by git, readable only by you), where
# Terraform picks it up and stores it as an encrypted Lambda environment variable.
# The value is read without echoing, so it never appears on screen or in shell history.
#
# (SSM Parameter Store would be the usual place, but AWS Free plan accounts are not allowed to
# write parameters, so the Lambda's own encrypted environment is used instead.)
set -euo pipefail
cd "$(dirname "$0")"

read -rsp "Copy the PostgreSQL URL, then press Enter here (or paste it first): " url
echo
# Nothing typed: take the URL from the clipboard (macOS).
if [ -z "$url" ] && command -v pbpaste >/dev/null; then
  url=$(pbpaste | tr -d '[:space:]')
fi
case "$url" in
  postgres://* | postgresql://*) ;;
  *) echo "That does not look like a PostgreSQL URL (it should start with postgresql://)." >&2; exit 1 ;;
esac

umask 077
printf 'database_url = "%s"\n' "$url" > terraform.tfvars
echo "Saved to infra/terraform.tfvars (not committed to git)."
