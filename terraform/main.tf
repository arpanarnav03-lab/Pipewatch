terraform {
  required_version = ">= 1.5"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project   = "pipewatch"
      ManagedBy = "terraform"
    }
  }
}

data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

data "aws_ssm_parameter" "al2023" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"
}

# ---------- Network ----------

resource "aws_security_group" "app" {
  name_prefix = "${var.name_prefix}-app-"
  description = "PipeWatch API"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description = "API from allowed CIDR"
    from_port   = 8000
    to_port     = 8000
    protocol    = "tcp"
    cidr_blocks = [var.allowed_cidr]
  }

  egress {
    description = "Outbound (image pull, public APIs, Secrets Manager)"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "db" {
  name_prefix = "${var.name_prefix}-db-"
  description = "PipeWatch Postgres"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description     = "Postgres from the app only"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.app.id]
  }
}

# ---------- Database + secret ----------

resource "random_password" "db" {
  length  = 32
  special = false
}

resource "aws_db_subnet_group" "this" {
  name_prefix = "${var.name_prefix}-"
  subnet_ids  = data.aws_subnets.default.ids
}

resource "aws_db_instance" "this" {
  identifier_prefix       = "${var.name_prefix}-"
  engine                  = "postgres"
  engine_version          = "16"
  instance_class          = var.db_instance_class
  allocated_storage       = 20
  storage_encrypted       = true
  db_name                 = "pipewatch"
  username                = "pipewatch"
  password                = random_password.db.result
  db_subnet_group_name    = aws_db_subnet_group.this.name
  vpc_security_group_ids  = [aws_security_group.db.id]
  publicly_accessible     = false
  backup_retention_period = 1
  skip_final_snapshot     = true # demo setting: set to false (and add a snapshot identifier) for real data
}

resource "aws_secretsmanager_secret" "database_url" {
  name_prefix = "${var.name_prefix}/database-url-"
}

resource "aws_secretsmanager_secret_version" "database_url" {
  secret_id     = aws_secretsmanager_secret.database_url.id
  secret_string = "postgresql://${aws_db_instance.this.username}:${random_password.db.result}@${aws_db_instance.this.address}:5432/${aws_db_instance.this.db_name}"
}

# ---------- Compute ----------

data "aws_iam_policy_document" "assume_ec2" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "read_secret" {
  statement {
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.database_url.arn]
  }
}

resource "aws_iam_role" "app" {
  name_prefix        = "${var.name_prefix}-"
  assume_role_policy = data.aws_iam_policy_document.assume_ec2.json
}

resource "aws_iam_role_policy" "read_secret" {
  name   = "read-database-url"
  role   = aws_iam_role.app.id
  policy = data.aws_iam_policy_document.read_secret.json
}

resource "aws_iam_instance_profile" "app" {
  name_prefix = "${var.name_prefix}-"
  role        = aws_iam_role.app.name
}

resource "aws_instance" "app" {
  ami                    = data.aws_ssm_parameter.al2023.value
  instance_type          = var.instance_type
  subnet_id              = data.aws_subnets.default.ids[0]
  vpc_security_group_ids = [aws_security_group.app.id]
  iam_instance_profile   = aws_iam_instance_profile.app.name

  metadata_options {
    http_tokens = "required" # IMDSv2 only
  }

  root_block_device {
    encrypted   = true
    volume_size = 12
  }

  user_data_replace_on_change = true
  user_data                   = <<-EOT
    #!/bin/bash
    set -euo pipefail
    dnf install -y docker
    systemctl enable --now docker
    DATABASE_URL=$(aws secretsmanager get-secret-value \
      --secret-id ${aws_secretsmanager_secret.database_url.arn} \
      --region ${var.region} --query SecretString --output text)
    docker run -d --name pipewatch --restart unless-stopped -p 8000:8000 \
      -e DATABASE_URL="$DATABASE_URL" \
      -e PIPEWATCH_SOURCE=open_meteo \
      -e PIPEWATCH_RUN_INTERVAL_MINUTES=60 \
      ${var.image}
  EOT

  depends_on = [aws_secretsmanager_secret_version.database_url]
}
