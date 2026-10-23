# VPC / subnet / IGW / route table ถูกสร้างและจัดการใน vpc.tf (VPC 10.0.0.0/16)
# backend ระบุ SubnetId (DEFAULT_SUBNET_ID) ให้ VM นักศึกษาเสมอ จึงไม่พึ่ง default VPC อีกต่อไป

data "aws_iam_instance_profile" "lab" {
  name = "LabInstanceProfile"
}

data "aws_ami" "al2023" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-2023*-x86_64"]
  }
}

# หา GNS3 base AMI ล่าสุดในบัญชีตัวเอง (สร้างด้วย scripts/build_gns3_ami.py)
data "aws_ami_ids" "gns3" {
  owners         = ["self"]
  sort_ascending = false

  filter {
    name   = "name"
    values = ["netlab-gns3-base*"]
  }
  filter {
    name   = "state"
    values = ["available"]
  }
}

locals {
  gns3_ami_id = var.base_ami_id != "" ? var.base_ami_id : try(data.aws_ami_ids.gns3.ids[0], "")

  # AZ และ subnet ของเครื่อง web/ALB มาจาก vpc.tf (public1 = AZ แรก, public2 = AZ ที่สอง ฯลฯ)
  app_azs     = local.web_azs
  app_subnets = [for az in local.app_azs : aws_subnet.web[az].id]
}
