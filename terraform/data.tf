# backend เรียก run_instances โดยไม่ระบุ SubnetId -> VM จะไปอยู่ใน default VPC
# ดังนั้นทุกอย่างต้องอยู่ใน default VPC เดียวกัน (SG ข้าม VPC ไม่ได้)
data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
  filter {
    name   = "default-for-az"
    values = ["true"]
  }
}

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
  web_subnet  = sort(data.aws_subnets.default.ids)[0]
}
