# ชื่อ SG ต่างจากที่ scripts/bootstrap_aws.py สร้าง (netlab-gns3-vm-sg) จะได้ไม่ชนกัน

resource "aws_security_group" "web" {
  name        = "${var.project}-tf-web-sg"
  description = "NetLab web server (frontend 8080, SSH admin)"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description = "Frontend"
    from_port   = 8080
    to_port     = 8080
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "SSH admin"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [var.admin_cidr]
  }

  dynamic "ingress" {
    for_each = var.expose_backend_port ? [1] : []
    content {
      description = "Backend API (browser to 8000)"
      from_port   = 8000
      to_port     = 8000
      protocol    = "tcp"
      cidr_blocks = ["0.0.0.0/0"]
    }
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# DEFAULT_SECURITY_GROUP_ID ของ VM นักศึกษา (เหมือนที่ bootstrap_aws.py ทำ)
resource "aws_security_group" "gns3_vm" {
  name        = "${var.project}-tf-gns3-vm-sg"
  description = "NetLab GNS3 VM - 3080, 5900-5999, ssh admin"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description = "GNS3 server"
    from_port   = 3080
    to_port     = 3080
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "GNS3 consoles"
    from_port   = 5900
    to_port     = 5999
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "SSH admin"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [var.admin_cidr]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Project = "gns3-cloud" }
}
