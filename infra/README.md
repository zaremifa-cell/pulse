# Pulse on AWS Lambda (Terraform)

A serverless deployment of Pulse that fits inside AWS's always-free limits:

```
EventBridge Scheduler --every minute--> pulse-check (Lambda) --HTTP--> monitored sites
                                               |
visitors --> function URL --> pulse-http (Lambda) --+--> PostgreSQL (Neon, Frankfurt)
```

- **pulse-http** serves the status page and REST API. The FastAPI app runs in-process through
  httpx's ASGI transport, so no web server or adapter layer is needed (`src/pulse/aws_lambda.py`).
- **pulse-check** runs one round of checks per invocation, using the same `run_due` code as the
  long-running checker, including `SELECT … FOR UPDATE SKIP LOCKED`, so it can share a database
  with the Render deployment without double checks.
- Each container keeps one event loop, so the database connection pool is reused across invocations.
- IAM roles are least-privilege; GitHub Actions deploys code through OIDC with no stored AWS keys
  (`github.tf`), and only from the `main` branch of this repository.
- Terraform state lives in a versioned, encrypted S3 bucket with native S3 locking (`bootstrap/`).
- CloudWatch log retention is 7 days, with an alarm when the scheduled checks keep failing.

## Deploy

```bash
aws configure                    # credentials with permission to create these resources
infra/set-database-url.sh        # writes infra/terraform.tfvars (git-ignored)
infra/deploy.sh                  # build, bootstrap the state bucket, terraform apply
```

Then set the `AWS_DEPLOY_ROLE_ARN` repository variable to the `deploy_role_arn` output, and every
push to `main` that passes the tests ships new code.

## Status

The stack validates (`terraform validate`) and the Lambda handlers are covered by
`tests/test_aws_lambda.py`, but it has not been applied yet. Accounts on the new AWS Free plan
sit under an AWS-managed service control policy that denies S3, Lambda and SSM to IAM users,
so it needs an account on the Paid plan, where the services used here stay within free limits.
