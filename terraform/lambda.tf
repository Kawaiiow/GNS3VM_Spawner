# Auto-stop VM ของ student (EventBridge schedule -> Lambda -> stop EC2)
#
# - ไม่แก้ ec2.tf / user_data จึงไม่ทำให้เครื่อง web ถูกสร้างใหม่
# - Lambda ใช้ LabRole (Learner Lab สร้าง IAM role เองไม่ได้)
# - Lambda log อยู่ที่ CloudWatch Logs: /aws/lambda/<project>-auto-stop
# - ตัวแปรของไฟล์นี้ประกาศไว้ในไฟล์นี้เลย เพื่อไม่ต้องแก้ variables.tf

variable "auto_stop_check_minutes" {
  description = "ความถี่ที่ Lambda ตรวจ VM ที่หมดเวลา (นาที) ยิ่งน้อยยิ่งปิดตรงเวลา"
  type        = number
  default     = 5

  validation {
    condition     = var.auto_stop_check_minutes >= 1 && var.auto_stop_check_minutes == floor(var.auto_stop_check_minutes)
    error_message = "auto_stop_check_minutes ต้องเป็นจำนวนเต็ม >= 1"
  }
}

locals {
  auto_stop_name = "${var.project}-auto-stop"
}

data "aws_iam_role" "lab_role" {
  name = "LabRole"
}

# zip ไฟล์ lambda_function.py (สร้างไฟล์ auto_stop_lambda.zip ข้างๆ ไฟล์นี้ ไม่ต้อง commit)
data "archive_file" "auto_stop" {
  type        = "zip"
  source_file = "${path.module}/lambda/auto_stop/lambda_function.py"
  output_path = "${path.module}/auto_stop_lambda.zip"
}

# สร้าง log group เองเพื่อกำหนดอายุ log (ไม่ให้สะสมไม่จำกัด)
resource "aws_cloudwatch_log_group" "auto_stop" {
  name              = "/aws/lambda/${local.auto_stop_name}"
  retention_in_days = 14
}

resource "aws_lambda_function" "auto_stop" {
  function_name = local.auto_stop_name
  description   = "NetLab: stop VM ของ student ที่เปิดเกินเวลา (อ่าน expires_at จาก DynamoDB)"
  role          = data.aws_iam_role.lab_role.arn
  runtime       = "python3.12"
  handler       = "lambda_function.lambda_handler"
  timeout       = 60
  memory_size   = 128

  filename         = data.archive_file.auto_stop.output_path
  source_code_hash = data.archive_file.auto_stop.output_base64sha256

  # หมายเหตุ: AWS_REGION เป็นตัวแปรสงวนของ Lambda ห้ามตั้งเอง
  environment {
    variables = {
      INSTANCES_TABLE = aws_dynamodb_table.instances.name
    }
  }

  depends_on = [aws_cloudwatch_log_group.auto_stop]
}

# EventBridge (CloudWatch Events) schedule
resource "aws_cloudwatch_event_rule" "auto_stop" {
  name                = "${local.auto_stop_name}-schedule"
  description         = "เรียก Lambda auto-stop ทุก ${var.auto_stop_check_minutes} นาที"
  schedule_expression = "rate(${var.auto_stop_check_minutes} ${var.auto_stop_check_minutes == 1 ? "minute" : "minutes"})"
}

resource "aws_cloudwatch_event_target" "auto_stop" {
  rule      = aws_cloudwatch_event_rule.auto_stop.name
  target_id = "auto-stop-lambda"
  arn       = aws_lambda_function.auto_stop.arn
}

resource "aws_lambda_permission" "auto_stop_from_events" {
  statement_id  = "AllowExecutionFromEventBridge"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.auto_stop.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.auto_stop.arn
}

output "auto_stop_lambda_name" {
  value = aws_lambda_function.auto_stop.function_name
}

output "auto_stop_log_group" {
  value = aws_cloudwatch_log_group.auto_stop.name
}
