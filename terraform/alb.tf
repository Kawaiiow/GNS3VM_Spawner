# ---------- ALB สาธารณะ -> Frontend (2 AZ) ----------
resource "aws_lb" "public" {
  name               = var.project
  load_balancer_type = "application"
  internal           = false
  security_groups    = [aws_security_group.alb.id]
  subnets            = local.app_subnets

  # frontend เรียก backend แบบ synchronous นานได้ถึง ~150 วินาที (เช่น start VM)
  # ค่าเริ่มต้นของ ALB คือ 60 วินาที จะตัดการเชื่อมต่อก่อน
  idle_timeout = var.alb_idle_timeout

  tags = { Name = "${var.project}-tf-alb" }
}

resource "aws_lb_target_group" "frontend" {
  name                 = "${var.project}-frontend"
  port                 = 8080
  protocol             = "HTTP"
  target_type          = "instance"
  vpc_id               = data.aws_vpc.default.id
  deregistration_delay = 30

  health_check {
    path                = "/"
    matcher             = "200-399"
    interval            = 30
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }
}

resource "aws_lb_listener" "public_http" {
  load_balancer_arn = aws_lb.public.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.frontend.arn
  }
}

# ---------- Backend Target Group (ใช้ ALB สาธารณะตัวเดียว) ----------
# ลบ ALB internal (aws_lb.internal) และ listener internal_backend ออกแล้ว
# Target Group ผูกได้กับ ALB เพียงตัวเดียว จึงเหลือเฉพาะ public ALB
resource "aws_lb_target_group" "backend" {
  name                 = "${var.project}-backend"
  port                 = 8000
  protocol             = "HTTP"
  target_type          = "instance"
  vpc_id               = data.aws_vpc.default.id
  deregistration_delay = 30

  health_check {
    path                = "/health"
    matcher             = "200"
    interval            = 30
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }
}

# Backend เปิดที่ port 8000 ของ ALB สาธารณะตัวเดียวกัน (ไม่ใช้ path-based, ไม่ต้องแก้โค้ด backend)
# frontend ตั้ง BACKEND_URL=http://<ALB DNS>:8000 และ terraform destroy ก็เรียก API ผ่าน port นี้
# ต้องมี ingress 8000 ใน SG ของ ALB (aws_security_group.alb) และ SG ของ backend ต้องรับ 8000 จาก SG ของ ALB
resource "aws_lb_listener" "public_backend" {
  load_balancer_arn = aws_lb.public.arn
  port              = 8000
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.backend.arn
  }
}
