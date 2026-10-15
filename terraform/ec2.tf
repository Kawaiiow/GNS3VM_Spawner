locals {
  # ฝัง token ลงใน URL เฉพาะตอน clone (user_data) เท่านั้น (repo public ไม่ต้องตั้ง github_token)
  clone_url = var.github_token != "" ? replace(var.repo_url, "https://", "https://x-access-token:${var.github_token}@") : var.repo_url
}

# JWT secret ต้อง "ใช้ร่วมกัน" ทุกเครื่อง backend: token ที่เครื่อง A ออก เครื่อง B ต้องตรวจผ่าน
# (เดิมสุ่มใน user_data ต่อเครื่อง ถ้ามี backend 2 ตัวจะ login หลุดสลับกัน)
resource "random_password" "jwt" {
  length  = 64
  special = false
}

# ---------------------------------------------------------------------------
# Backend: Launch Template + ASG (กระจายหลาย AZ, อยู่หลัง internal ALB)
# ---------------------------------------------------------------------------
resource "aws_launch_template" "backend" {
  name_prefix   = "${var.project}-tf-backend-"
  image_id      = data.aws_ami.al2023.id
  instance_type = var.backend_instance_type
  key_name      = var.key_name

  vpc_security_group_ids = [aws_security_group.backend.id]

  # backend ใช้ LabInstanceProfile (boto3 เรียก EC2/DynamoDB/S3)
  iam_instance_profile {
    name = data.aws_iam_instance_profile.lab.name
  }

  block_device_mappings {
    device_name = "/dev/xvda"
    ebs {
      volume_size           = 20
      volume_type           = "gp3"
      delete_on_termination = true
    }
  }

  # hop limit 2: ให้ boto3 ใน Docker container อ่าน credentials จาก IMDS ของเครื่องได้
  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 2
  }

  # replace \r\n: กัน line ending แบบ Windows ทำให้ #!/bin/bash พัง
  user_data = base64encode(replace(templatefile("${path.module}/user_data_backend.sh.tpl", {
    repo_url          = var.repo_url
    clone_url         = local.clone_url
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
    jwt_secret        = random_password.jwt.result

    # admin คนแรก: สร้างจากเครื่องที่อยู่ AZ แรกเท่านั้น (กัน 2 เครื่องสร้างพร้อมกันแล้วซ้ำ)
    admin_az           = local.app_azs[0]
    admin_username     = var.admin_username
    admin_member_id    = var.admin_member_id
    admin_password_b64 = base64encode(var.admin_password)
  }), "\r\n", "\n"))

  tag_specifications {
    resource_type = "instance"
    tags          = { Name = "${var.project}-backend" }
  }

  lifecycle {
    create_before_destroy = true

    precondition {
      condition     = local.gns3_ami_id != ""
      error_message = "ไม่พบ GNS3 AMI: รัน scripts/build_gns3_ami.py ก่อน หรือระบุ base_ami_id"
    }

    precondition {
      condition     = var.github_token == "" || startswith(var.repo_url, "https://")
      error_message = "ใช้ github_token ได้เฉพาะ repo_url ที่ขึ้นต้นด้วย https://"
    }
  }
}

resource "aws_autoscaling_group" "backend" {
  name                = "${var.project}-tf-backend-asg"
  min_size            = var.backend_count
  max_size            = var.backend_count
  desired_capacity    = var.backend_count
  vpc_zone_identifier = local.app_subnets
  target_group_arns   = [aws_lb_target_group.backend.arn]

  # ให้ ASG ฆ่า/สร้างเครื่องใหม่เมื่อ ALB ตรวจ /health ไม่ผ่าน (ไม่ใช่แค่ EC2 status check)
  health_check_type         = "ELB"
  health_check_grace_period = var.health_check_grace_period
  force_delete              = true

  launch_template {
    id      = aws_launch_template.backend.id
    version = aws_launch_template.backend.latest_version
  }

  # เปลี่ยน user_data (เช่น repo_branch) แล้ว apply -> ทยอยเปลี่ยนเครื่องทีละตัว ระบบไม่หยุด
  instance_refresh {
    strategy = "Rolling"
    preferences {
      min_healthy_percentage = 50
      instance_warmup        = 300
    }
  }

  tag {
    key                 = "Name"
    value               = "${var.project}-backend"
    propagate_at_launch = true
  }

  depends_on = [aws_lb_listener.internal_backend]
}

# ---------------------------------------------------------------------------
# Frontend: Launch Template + ASG (กระจายหลาย AZ, อยู่หลัง ALB สาธารณะ)
# ไม่ใส่ IAM instance profile: frontend ไม่เรียก AWS API เรียกแค่ backend
# ---------------------------------------------------------------------------
resource "aws_launch_template" "frontend" {
  name_prefix   = "${var.project}-tf-frontend-"
  image_id      = data.aws_ami.al2023.id
  instance_type = var.frontend_instance_type
  key_name      = var.key_name

  vpc_security_group_ids = [aws_security_group.frontend.id]

  block_device_mappings {
    device_name = "/dev/xvda"
    ebs {
      volume_size           = 20
      volume_type           = "gp3"
      delete_on_termination = true
    }
  }

  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
  }

  user_data = base64encode(replace(templatefile("${path.module}/user_data_frontend.sh.tpl", {
    repo_url    = var.repo_url
    clone_url   = local.clone_url
    repo_branch = var.repo_branch
    backend_url = "http://${aws_lb.internal.dns_name}:8000"
  }), "\r\n", "\n"))

  tag_specifications {
    resource_type = "instance"
    tags          = { Name = "${var.project}-frontend" }
  }

  lifecycle {
    create_before_destroy = true

    precondition {
      condition     = var.github_token == "" || startswith(var.repo_url, "https://")
      error_message = "ใช้ github_token ได้เฉพาะ repo_url ที่ขึ้นต้นด้วย https://"
    }
  }
}

resource "aws_autoscaling_group" "frontend" {
  name                = "${var.project}-tf-frontend-asg"
  min_size            = var.frontend_count
  max_size            = var.frontend_count
  desired_capacity    = var.frontend_count
  vpc_zone_identifier = local.app_subnets
  target_group_arns   = [aws_lb_target_group.frontend.arn]

  health_check_type         = "ELB"
  health_check_grace_period = var.health_check_grace_period
  force_delete              = true

  launch_template {
    id      = aws_launch_template.frontend.id
    version = aws_launch_template.frontend.latest_version
  }

  instance_refresh {
    strategy = "Rolling"
    preferences {
      min_healthy_percentage = 50
      instance_warmup        = 300
    }
  }

  tag {
    key                 = "Name"
    value               = "${var.project}-frontend"
    propagate_at_launch = true
  }

  depends_on = [aws_lb_listener.public_http]
}

# ตอน destroy: เรียก API ของ web (admin login -> POST /admin/instances/terminate-all)
# ให้ terminate VM ที่ API สร้างขึ้น (Terraform ไม่รู้จัก) ก่อน แล้วค่อยลบ web / SG gns3_vm
# ลำดับ destroy: cleanup_lab_vms -> ASG (frontend/backend) + ALB -> SG gns3_vm / DynamoDB
# (cleanup ต้อง depend on backend ASG เพื่อให้ถูกลบก่อน ตอนที่ API ยังทำงานอยู่)
# ต้องเข้าถึง backend (port 8000 บน ALB สาธารณะ) จากเครื่องที่รัน terraform ได้ (expose_backend_port = true)
# ถ้าไม่เปิด/เรียก API ไม่ได้ จะ fallback ไปใช้ aws CLI ลบตาม SG ของ VM lab (ถ้ามี aws ใน PATH)
# หลังลบ VM แล้ว จะลบ AMI ต้นแบบแบบฝึกหัดที่ระบบสร้างเอง (ชื่อ netlab-ex-* / netlab-restore-*, tag Project=gns3-cloud)
# ผ่าน POST /admin/images/delete-all (fallback: aws CLI) เป็น best-effort ไม่ทำให้ destroy ล้ม
# ไม่แตะ Base AMI (netlab-gns3-base-*) และไฟล์สำรองใน S3
resource "terraform_data" "cleanup_lab_vms" {
  # destroy-time provisioner อ้างได้เฉพาะ self จึงเก็บค่าที่ต้องใช้ไว้ใน input
  input = {
    region     = var.region
    # ว่าง = ข้ามขั้นตอนเรียก API แล้วไปใช้ aws CLI fallback เลย (ไม่ต้องรอ timeout)
    api_base   = var.expose_backend_port ? "http://${aws_lb.public.dns_name}:8000" : ""
    sg_id      = aws_security_group.gns3_vm.id
    admin_user = var.admin_username
    admin_pass = var.admin_password
  }
  depends_on = [
    aws_autoscaling_group.backend,
    aws_autoscaling_group.frontend,
    aws_lb_listener.public_backend_admin,
    aws_security_group.gns3_vm,
  ]

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
      if ($env:API_BASE) {
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

      # 3) ลบ AMI ต้นแบบแบบฝึกหัดที่ระบบสร้างเอง (Terraform ไม่รู้จัก) - best effort ไม่ทำให้ destroy ล้ม
      $imgDone = $false
      if ($apiRan) {
        try {
          $r = Invoke-RestMethod -Method Post -Uri "$env:API_BASE/admin/images/delete-all" -Headers $headers -TimeoutSec 600
          Write-Host "API delete-all images: deleted=$(@($r.deleted).Count) skipped=$(@($r.skipped).Count) failed=$(@($r.failed).Count)"
          if (@($r.failed).Count -eq 0) { $imgDone = $true }
        } catch {
          Write-Host "API delete images failed: $($_.Exception.Message)"
        }
      }
      if (-not $imgDone) {
        if (Get-Command aws -ErrorAction SilentlyContinue) {
          try {
            $imgs = aws ec2 describe-images --owners self --filters "Name=tag:Project,Values=gns3-cloud" --output json | ConvertFrom-Json
            foreach ($img in @($imgs.Images)) {
              if (-not ($img.Name -like "netlab-ex-*" -or $img.Name -like "netlab-restore-*")) { continue }
              aws ec2 deregister-image --image-id $img.ImageId | Out-Null
              foreach ($bdm in @($img.BlockDeviceMappings)) {
                if ($bdm.Ebs -and $bdm.Ebs.SnapshotId) { aws ec2 delete-snapshot --snapshot-id $bdm.Ebs.SnapshotId | Out-Null }
              }
              Write-Host "deregistered $($img.ImageId) ($($img.Name))"
            }
          } catch {
            Write-Host "warning: aws CLI ลบ AMI ไม่สำเร็จ: $($_.Exception.Message)"
          }
        } else {
          Write-Host "warning: ยังไม่ได้ลบ AMI ต้นแบบ (ไม่มี API/aws CLI) ลบ netlab-ex-* และ netlab-restore-* เองใน EC2 console"
        }
      }
    EOT
  }
}
