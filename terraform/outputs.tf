output "app_url" {
  description = "PipeWatch API (restricted to allowed_cidr)."
  value       = "http://${aws_instance.app.public_ip}:8000"
}

output "db_endpoint" {
  description = "Private Postgres endpoint."
  value       = aws_db_instance.this.address
}

output "database_url_secret_arn" {
  description = "Secrets Manager ARN holding DATABASE_URL."
  value       = aws_secretsmanager_secret.database_url.arn
}
