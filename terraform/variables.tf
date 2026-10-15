variable "region" {
  description = "AWS region to deploy into."
  type        = string
  default     = "ap-south-1"
}

variable "name_prefix" {
  description = "Prefix for resource names."
  type        = string
  default     = "pipewatch"
}

variable "image" {
  description = "Container image to run, e.g. ghcr.io/<owner>/pipewatch:latest (must be pullable by the instance)."
  type        = string
}

variable "allowed_cidr" {
  description = "CIDR allowed to reach the API on port 8000, e.g. your IP as 203.0.113.7/32."
  type        = string

  validation {
    condition     = var.allowed_cidr != "0.0.0.0/0"
    error_message = "Do not expose the API to the whole internet; use a specific CIDR."
  }
}

variable "instance_type" {
  type    = string
  default = "t3.micro"
}

variable "db_instance_class" {
  type    = string
  default = "db.t4g.micro"
}
