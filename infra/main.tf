# Pulse on AWS, serverless and inside the always-free tier:
#
#   EventBridge Scheduler --every minute--> check function --HTTP--> monitored sites
#                                                  |
#   visitors --> function URL --> http function ---+--> PostgreSQL (Neon, Frankfurt)
#
# The code is deployed by GitHub Actions through a short-lived OIDC role; Terraform owns the
# infrastructure and the first version of the code.

terraform {
  required_version = ">= 1.10"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 6.0" }
  }
  # The bucket is passed at init time (see README): terraform init -backend-config="bucket=..."
  backend "s3" {
    key          = "pulse/terraform.tfstate"
    region       = "eu-central-1"
    encrypt      = true
    use_lockfile = true
  }
}

provider "aws" {
  region = var.region
  default_tags {
    tags = { Project = "pulse", ManagedBy = "terraform" }
  }
}

data "aws_caller_identity" "current" {}

locals {
  package = "${path.module}/build/pulse.zip"
  # Lambda encrypts environment variables at rest. (SSM Parameter Store would keep the URL out
  # of the function configuration, but Free plan accounts are not allowed to write parameters.)
  environment = {
    DATABASE_URL = var.database_url
    SEED_DEMO    = "true"
    RUN_CHECKER  = "false"
  }
}

# ---------------------------------------------------------------- functions

resource "aws_iam_role" "lambda" {
  name = "pulse-lambda"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Principal = { Service = "lambda.amazonaws.com" }, Action = "sts:AssumeRole" }]
  })
}

resource "aws_iam_role_policy_attachment" "lambda_logs" {
  role       = aws_iam_role.lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_cloudwatch_log_group" "http" {
  name              = "/aws/lambda/pulse-http"
  retention_in_days = 7
}

resource "aws_cloudwatch_log_group" "check" {
  name              = "/aws/lambda/pulse-check"
  retention_in_days = 7
}

resource "aws_lambda_function" "http" {
  function_name    = "pulse-http"
  description      = "Pulse status page and REST API"
  role             = aws_iam_role.lambda.arn
  runtime          = "python3.14"
  architectures    = ["arm64"]
  handler          = "pulse.aws_lambda.http_handler"
  filename         = local.package
  source_code_hash = filebase64sha256(local.package)
  memory_size      = 512
  timeout          = 15
  environment { variables = local.environment }
  logging_config {
    log_format = "Text"
    log_group  = aws_cloudwatch_log_group.http.name
  }
  # After the first deploy, GitHub Actions ships new code; Terraform leaves it alone.
  lifecycle { ignore_changes = [filename, source_code_hash] }
}

resource "aws_lambda_function" "check" {
  function_name    = "pulse-check"
  description      = "Pulse: one round of uptime checks"
  role             = aws_iam_role.lambda.arn
  runtime          = "python3.14"
  architectures    = ["arm64"]
  handler          = "pulse.aws_lambda.check_handler"
  filename         = local.package
  source_code_hash = filebase64sha256(local.package)
  memory_size      = 256
  timeout          = 55 # a round must finish before the next one starts
  environment { variables = local.environment }
  logging_config {
    log_format = "Text"
    log_group  = aws_cloudwatch_log_group.check.name
  }
  lifecycle { ignore_changes = [filename, source_code_hash] }
}

# ---------------------------------------------------------------- public URL

resource "aws_lambda_function_url" "http" {
  function_name      = aws_lambda_function.http.function_name
  authorization_type = "NONE"
}

# A public function URL needs both permissions since October 2025.
resource "aws_lambda_permission" "url_public" {
  statement_id           = "public-function-url"
  action                 = "lambda:InvokeFunctionUrl"
  function_name          = aws_lambda_function.http.function_name
  principal              = "*"
  function_url_auth_type = "NONE"
}

resource "aws_lambda_permission" "url_invoke" {
  statement_id             = "public-function-url-invoke"
  action                   = "lambda:InvokeFunction"
  function_name            = aws_lambda_function.http.function_name
  principal                = "*"
  invoked_via_function_url = true
}

# ---------------------------------------------------------------- schedule

resource "aws_iam_role" "scheduler" {
  name = "pulse-scheduler"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow", Principal = { Service = "scheduler.amazonaws.com" }, Action = "sts:AssumeRole"
      Condition = { StringEquals = { "aws:SourceAccount" = data.aws_caller_identity.current.account_id } }
    }]
  })
}

resource "aws_iam_role_policy" "scheduler_invoke" {
  name = "invoke-check"
  role = aws_iam_role.scheduler.id
  policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = "lambda:InvokeFunction", Resource = aws_lambda_function.check.arn }]
  })
}

resource "aws_scheduler_schedule" "check" {
  name                = "pulse-check-every-minute"
  schedule_expression = "rate(1 minute)"
  flexible_time_window { mode = "OFF" }
  target {
    arn      = aws_lambda_function.check.arn
    role_arn = aws_iam_role.scheduler.arn
    retry_policy {
      maximum_retry_attempts = 0 # a missed round is simply caught up by the next one
    }
  }
}

# ---------------------------------------------------------------- alarm

# Errors in the check function mean the monitor itself is down: worth knowing about.
resource "aws_cloudwatch_metric_alarm" "check_errors" {
  alarm_name          = "pulse-check-errors"
  alarm_description   = "The scheduled uptime checks are failing."
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = aws_lambda_function.check.function_name }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 3
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
}
