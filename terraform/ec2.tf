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
