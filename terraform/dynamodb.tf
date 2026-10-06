# schema ตรงกับ scripts/init_dynamodb.py
# (ถ้าใช้ Terraform สร้างตารางแล้ว ไม่ต้องรัน init_dynamodb.py อีก ไม่งั้นชื่อซ้ำ)

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
