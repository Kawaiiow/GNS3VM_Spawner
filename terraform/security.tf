# ชื่อ SG ต่างจากที่ scripts/bootstrap_aws.py สร้าง (netlab-gns3-vm-sg) จะได้ไม่ชนกัน
#
# เส้นทางการเข้าถึง (อ้างอิงกันด้วย SG ไม่ใช้ IP เพราะเครื่องมีหลายตัวและเปลี่ยนได้):
#   Internet -> alb (80) -> frontend (8080)
#   frontend -> alb (8000) -> backend (8000)   (ALB สาธารณะตัวเดียว ไม่มี internal ALB)
#   นักศึกษา -> VM GNS3 ตรงๆ (3080, 5900-5999) ไม่ผ่าน ALB

# ALB ที่เปิดสู่อินเทอร์เน็ต (หน้าเว็บ)
resource "aws_security_group" "alb" {
  name        = "${var.project}-tf-alb-sg"
  description = "NetLab public ALB (HTTP 80, backend 8000)"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description = "HTTP from internet"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # Backend API: frontend เรียกผ่าน DNS ของ ALB สาธารณะ จึงเห็น source เป็น public IP ของเครื่อง
  # frontend (อ้างด้วย SG ไม่ได้) และ terraform destroy ก็เรียกจากเครื่อง admin ด้วย
  ingress {
    description = "Backend API (frontend + terraform destroy cleanup)"
    from_port   = 8000
    to_port     = 8000
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# เครื่อง Frontend (รับเฉพาะจาก ALB)
resource "aws_security_group" "frontend" {
  name        = "${var.project}-tf-frontend-sg"
  description = "NetLab frontend (8080 from ALB, SSH admin)"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description     = "Frontend from public ALB"
    from_port       = 8080
    to_port         = 8080
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
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
}

# เครื่อง Backend (รับเฉพาะจาก ALB)
resource "aws_security_group" "backend" {
  name        = "${var.project}-tf-backend-sg"
  description = "NetLab backend (8000 from ALB, SSH admin)"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description     = "Backend API from public ALB"
    from_port       = 8000
    to_port         = 8000
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
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
}

# DEFAULT_SECURITY_GROUP_ID ของ VM นักศึกษา (เหมือนที่ bootstrap_aws.py ทำ)
# ไม่เปลี่ยนจากเดิม: VM พวกนี้ไม่มี HA และไม่ต้องอยู่ AZ เดียวกับเครื่อง web
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
