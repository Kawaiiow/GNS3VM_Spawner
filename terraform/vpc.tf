# ---------------------------------------------------------------------------
# VPC 10.0.0.0/16 + Internet Gateway + Route Table (public) + Subnets
#   public1 (10.0.0.0/24) -> AZ แรก   |  public2 (10.0.1.0/24) -> AZ ที่สอง   (ALB / Frontend / Backend)
#   public-lab (10.0.2.0/24) -> var.lab_az (us-east-1c)                          (VM นักศึกษาที่ API สร้าง)
# ทุก subnet เป็น public (route 0.0.0.0/0 -> IGW + auto-assign public IP) จึงไม่ต้องใช้ NAT Gateway
# ---------------------------------------------------------------------------
data "aws_availability_zones" "available" {
  state = "available"
}

locals {
  # AZ ของเครื่อง web = AZ ตามตัวอักษร (ไม่รวม lab_az) จำนวน az_count
  web_azs = slice(
    sort([for z in data.aws_availability_zones.available.names : z if z != var.lab_az]),
    0, var.az_count
  )

  # CIDR ต่อ AZ: index 0 -> 10.0.0.0/24, index 1 -> 10.0.1.0/24 ...
  web_subnet_cidrs = { for i, az in local.web_azs : az => cidrsubnet(var.vpc_cidr, 8, i) }
}

resource "aws_vpc" "main" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = { Name = "${var.project}-vpc" }
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id
  tags   = { Name = "${var.project}-igw" }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }

  tags = { Name = "${var.project}-public-rt" }
}

# Subnet ของเครื่อง web / ALB (กระจายหลาย AZ)
resource "aws_subnet" "web" {
  for_each                = local.web_subnet_cidrs
  vpc_id                  = aws_vpc.main.id
  availability_zone       = each.key
  cidr_block              = each.value
  map_public_ip_on_launch = true

  tags = { Name = "${var.project}-public-${each.key}" }
}

resource "aws_route_table_association" "web" {
  for_each       = aws_subnet.web
  subnet_id      = each.value.id
  route_table_id = aws_route_table.public.id
}

# Subnet ของ VM นักศึกษา: backend ส่ง SubnetId นี้ใน run_instances เสมอ
resource "aws_subnet" "lab" {
  vpc_id                  = aws_vpc.main.id
  availability_zone       = var.lab_az
  cidr_block              = var.lab_subnet_cidr
  map_public_ip_on_launch = true # นักศึกษาต่อตรงที่ 3080 / 5900-5999 ต้องมี public IP

  tags = { Name = "${var.project}-public-lab-${var.lab_az}" }

  lifecycle {
    precondition {
      condition     = !contains(values(local.web_subnet_cidrs), var.lab_subnet_cidr)
      error_message = "lab_subnet_cidr ซ้ำกับ CIDR ของ subnet เครื่อง web เปลี่ยนเป็นช่วงอื่น"
    }
    precondition {
      condition     = !contains(local.web_azs, var.lab_az)
      error_message = "lab_az ซ้ำกับ AZ ของเครื่อง web"
    }
  }
}

resource "aws_route_table_association" "lab" {
  subnet_id      = aws_subnet.lab.id
  route_table_id = aws_route_table.public.id
}
