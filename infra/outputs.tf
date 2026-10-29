output "url" {
  description = "Public address of the status page."
  value       = aws_lambda_function_url.http.function_url
}

output "deploy_role_arn" {
  description = "Role GitHub Actions assumes to deploy (set as the AWS_DEPLOY_ROLE_ARN repository variable)."
  value       = aws_iam_role.deploy.arn
}
