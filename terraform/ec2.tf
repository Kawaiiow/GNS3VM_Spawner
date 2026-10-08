locals {
  # ฝัง token ลงใน URL เฉพาะตอน clone (user_data) เท่านั้น
  clone_url = var.github_token != "" ? replace(var.repo_url, "https://", "https://x-access-token:${var.github_token}@") : var.repo_url
}

resource "aws_instance" "web" {
  ami                    = data.aws_ami.al2023.id
  instance_type          = var.web_instance_type
  subnet_id              = local.web_subnet
  vpc_security_group_ids = [aws_security_group.web.id]
  iam_instance_profile   = data.aws_iam_instance_profile.lab.name
  key_name               = var.key_name

  root_block_device {
    volume_size = 20
    volume_type = "gp3"
  }

  user_data = templatefile("${path.module}/user_data.sh.tpl", {
    repo_url          = var.repo_url
    clone_url         = local.clone_url
    has_token         = var.github_token != ""
    repo_branch       = var.repo_branch
    region            = var.region
    ami_id            = local.gns3_ami_id
    lab_instance_type = var.lab_instance_type
    key_name          = var.key_name
    lab_sg_id         = aws_security_group.gns3_vm.id
    instance_profile  = data.aws_iam_instance_profile.lab.name
    max_instances     = var.max_concurrent_instances
    users_table       = aws_dynamodb_table.users.name
    instances_table   = aws_dynamodb_table.instances.name
    exercises_table   = aws_dynamodb_table.exercises.name
    snapshots_bucket  = data.aws_s3_bucket.snapshots.id

    # admin คนแรก (สร้างอัตโนมัติท้าย user_data)
    admin_username     = var.admin_username
    admin_member_id    = var.admin_member_id
    admin_password_b64 = base64encode(var.admin_password)
  })
  user_data_replace_on_change = true

  lifecycle {
    precondition {
      condition     = local.gns3_ami_id != ""
      error_message = "ไม่พบ GNS3 AMI: รัน scripts/build_gns3_ami.py ก่อน หรือระบุ base_ami_id"
    }

    precondition {
      condition     = var.github_token == "" || startswith(var.repo_url, "https://")
      error_message = "ใช้ github_token ได้เฉพาะ repo_url ที่ขึ้นต้นด้วย https://"
    }
  }

  tags = { Name = "${var.project}-web" }
}

resource "aws_eip" "web" {
  instance = aws_instance.web.id
  domain   = "vpc"
  tags     = { Name = "${var.project}-web-eip" }
}

# ตอน destroy: เรียก API ของ web (admin login -> POST /admin/instances/terminate-all)
# ให้ terminate VM ที่ API สร้างขึ้น (Terraform ไม่รู้จัก) ก่อน แล้วค่อยลบ web / SG gns3_vm
# ลำดับ destroy: cleanup_lab_vms -> web + EIP -> SG gns3_vm / DynamoDB
# (cleanup ต้อง depend on web เพื่อให้ถูกลบก่อน ตอนที่ API ยังทำงานอยู่)
# ต้องเข้าถึง port 8000 ของ web จากเครื่องที่รัน terraform ได้ (expose_backend_port = true)
# ถ้าเรียก API ไม่ได้ จะ fallback ไปใช้ aws CLI ลบตาม SG ของ VM lab (ถ้ามี aws ใน PATH)
resource "terraform_data" "cleanup_lab_vms" {
  # destroy-time provisioner อ้างได้เฉพาะ self จึงเก็บค่าที่ต้องใช้ไว้ใน input
  input = {
    region     = var.region
    api_base   = "http://${aws_eip.web.public_ip}:8000"
    sg_id      = aws_security_group.gns3_vm.id
    admin_user = var.admin_username
    admin_pass = var.admin_password
  }
  depends_on = [aws_instance.web, aws_eip.web, aws_security_group.gns3_vm]

  provisioner "local-exec" {
    when        = destroy
    interpreter = ["PowerShell", "-NoProfile", "-Command"]
    environment = {
      AWS_REGION = self.input.region
      API_BASE   = self.input.api_base
      SG_ID      = self.input.sg_id
      ADMIN_USER = self.input.admin_user
      ADMIN_PASS = self.input.admin_pass
    }
    command = <<-EOT
      $ErrorActionPreference = "Stop"
      $apiRan = $false
      $apiClean = $false

      # 1) เรียก API ลบ VM ทั้งหมด (รอจน terminated)
      try {
        $body = @{ identifier = $env:ADMIN_USER; password = $env:ADMIN_PASS } | ConvertTo-Json
        $login = Invoke-RestMethod -Method Post -Uri "$env:API_BASE/auth/login" -ContentType "application/json" -Body $body -TimeoutSec 30
        $headers = @{ Authorization = "Bearer $($login.access_token)" }
        $res = Invoke-RestMethod -Method Post -Uri "$env:API_BASE/admin/instances/terminate-all?wait=true" -Headers $headers -TimeoutSec 600
        $apiRan = $true
        Write-Host "API terminate-all: terminated=$($res.terminated_count) failed=$(@($res.failed).Count) wait_error=$($res.wait_error)"
        if ((@($res.failed).Count -eq 0) -and (-not $res.wait_error)) { $apiClean = $true }
      } catch {
        Write-Host "API cleanup failed: $($_.Exception.Message)"
      }

      # 2) fallback: aws CLI ลบ VM ที่ใช้ SG ของ lab
      if (-not $apiClean) {
        if (Get-Command aws -ErrorAction SilentlyContinue) {
          $ids = aws ec2 describe-instances --filters "Name=instance.group-id,Values=$env:SG_ID" "Name=instance-state-name,Values=pending,running,stopping,stopped" --query "Reservations[].Instances[].InstanceId" --output text
          if ($LASTEXITCODE -ne 0) { exit 1 }
          if ($ids) {
            $idList = @($ids -split "\s+" | Where-Object { $_ })
            aws ec2 terminate-instances --instance-ids $idList
            if ($LASTEXITCODE -ne 0) { exit 1 }
            aws ec2 wait instance-terminated --instance-ids $idList
            if ($LASTEXITCODE -ne 0) { exit 1 }
          }
        } elseif (-not $apiRan) {
          Write-Host "เรียก API ไม่ได้ และไม่พบ aws CLI ใน PATH: terminate VM ของ lab เองก่อน (SG $env:SG_ID) แล้วรัน destroy ใหม่"
          exit 1
        } else {
          Write-Host "warning: บาง VM ลบผ่าน API ไม่สำเร็จ (ไม่พบ aws CLI สำหรับ fallback)"
        }
      }
    EOT
  }
}
