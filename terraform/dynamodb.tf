# schema ตรงกับ scripts/init_dynamodb.py
#
# ทำงานอัตโนมัติด้วย `terraform apply` ปกติ:
#   - data.external เช็คตอน plan ว่าตารางมีอยู่ใน AWS หรือไม่ (ddb_exists.py)
#   - มีอยู่ -> import block ทำงาน รับตารางเดิมเข้า state
#   - ไม่มี  -> import block ถูกข้าม แล้ว Terraform สร้างตารางใหม่ให้
# ต้องใช้ Terraform >= 1.7 (import + for_each) และ python + boto3 ในเครื่อง
# (python_cmd ใช้ค่าเดียวกับใน s3.tf)

data "external" "ddb_exists" {
  program = [local.python_cmd, "${path.module}/ddb_exists.py"]
  query = {
    region = var.region
    tables = join(",", [var.users_table, var.instances_table, var.exercises_table])
  }
}

locals {
  ddb_exists = data.external.ddb_exists.result # { "<ชื่อตาราง>" = "true"/"false" }
}

import {
  for_each = lookup(local.ddb_exists, var.users_table, "false") == "true" ? toset(["import"]) : toset([])
  to       = aws_dynamodb_table.users
  id       = var.users_table
}

import {
  for_each = lookup(local.ddb_exists, var.instances_table, "false") == "true" ? toset(["import"]) : toset([])
  to       = aws_dynamodb_table.instances
  id       = var.instances_table
}

import {
  for_each = lookup(local.ddb_exists, var.exercises_table, "false") == "true" ? toset(["import"]) : toset([])
  to       = aws_dynamodb_table.exercises
  id       = var.exercises_table
}

resource "aws_dynamodb_table" "users" {
  name         = var.users_table
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "user_id"

  attribute {
    name = "user_id"
    type = "S"
  }
  attribute {
    name = "username"
    type = "S"
  }
  attribute {
    name = "member_id"
    type = "S"
  }

  global_secondary_index {
    name            = "UsernameIndex"
    hash_key        = "username"
    projection_type = "ALL"
  }
  global_secondary_index {
    name            = "MemberIdIndex"
    hash_key        = "member_id"
    projection_type = "ALL"
  }
}

resource "aws_dynamodb_table" "instances" {
  name         = var.instances_table
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "instance_id"

  attribute {
    name = "instance_id"
    type = "S"
  }
  attribute {
    name = "user_id"
    type = "S"
  }

  global_secondary_index {
    name            = "UserIdIndex"
    hash_key        = "user_id"
    projection_type = "ALL"
  }
}

resource "aws_dynamodb_table" "exercises" {
  name         = var.exercises_table
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "exercise_id"

  attribute {
    name = "exercise_id"
    type = "S"
  }
  attribute {
    name = "instructor_id"
    type = "S"
  }

  global_secondary_index {
    name            = "InstructorIdIndex"
    hash_key        = "instructor_id"
    projection_type = "ALL"
  }
}
