# backend เรียก run_instances โดยไม่ระบุ SubnetId -> VM นักศึกษาจะไปอยู่ใน default VPC (AWS เลือก AZ ให้เอง)
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

# อ่านว่า subnet แต่ละตัวอยู่ AZ ไหน เพื่อเลือก subnet ให้ครบ var.az_count AZ (ไม่ซ้ำ AZ)
data "aws_subnet" "default" {
  for_each = toset(data.aws_subnets.default.ids)
  id       = each.value
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

  # AZ -> subnet id (default VPC มี 1 default subnet ต่อ 1 AZ)
  subnet_by_az = { for s in data.aws_subnet.default : s.availability_zone => s.id }

  # เลือก AZ แรกๆ ตามลำดับตัวอักษร จำนวน az_count แล้วใช้ร่วมกันทั้ง ALB และ ASG
  app_azs     = slice(sort(keys(local.subnet_by_az)), 0, var.az_count)
  app_subnets = [for az in local.app_azs : local.subnet_by_az[az]]
}
