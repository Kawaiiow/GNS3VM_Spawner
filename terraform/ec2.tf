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

  # destroy: web -> cleanup_lab_vms (terminate VM ของ API) -> SG gns3_vm
  depends_on = [terraform_data.cleanup_lab_vms]

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

# ตอน destroy: terminate VM ที่ API สร้างขึ้น (Terraform ไม่รู้จัก) ก่อนลบ SG gns3_vm
# ไม่งั้น SG จะติด DependencyViolation เพราะ ENI ของ VM ยังอ้างถึงอยู่
resource "terraform_data" "cleanup_lab_vms" {
  # destroy-time provisioner อ้างได้เฉพาะ self จึงเก็บ region ไว้ใน input
  input      = var.region
  depends_on = [aws_security_group.gns3_vm]

  provisioner "local-exec" {
    when        = destroy
    environment = { AWS_REGION = self.input }
    command     = <<-EOT
      ids=$(aws ec2 describe-instances \
        --filters Name=tag:Project,Values=gns3-cloud \
                  Name=instance-state-name,Values=pending,running,stopping,stopped \
        --query 'Reservations[].Instances[].InstanceId' --output text)
      if [ -n "$ids" ]; then
        aws ec2 terminate-instances --instance-ids $ids
        aws ec2 wait instance-terminated --instance-ids $ids
      fi
    EOT
  }
}
