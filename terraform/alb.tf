# ---------- ALB สาธารณะ -> Frontend (2 AZ) ----------
resource "aws_lb" "public" {
  name               = "${var.project}-tf-alb"
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
  name                 = "${var.project}-tf-frontend-tg"
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

# ---------- ALB ภายใน (internal) -> Backend (2 AZ) ----------
# Frontend เรียก backend ผ่าน ALB นี้ (BACKEND_URL) ไม่ได้เปิดสู่อินเทอร์เน็ต
resource "aws_lb" "internal" {
  name               = "${var.project}-tf-backend-alb"
  load_balancer_type = "application"
  internal           = true
  security_groups    = [aws_security_group.backend_alb.id]
  subnets            = local.app_subnets
  idle_timeout       = var.alb_idle_timeout

  tags = { Name = "${var.project}-tf-backend-alb" }
}

resource "aws_lb_target_group" "backend" {
  name                 = "${var.project}-tf-backend-tg"
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

resource "aws_lb_listener" "internal_backend" {
  load_balancer_arn = aws_lb.internal.arn
  port              = 8000
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.backend.arn
  }
}

# (ไม่บังคับ) เปิด 8000 บน ALB สาธารณะ เฉพาะ IP admin เพื่อให้ terraform destroy เรียก API ลบ VM/AMI ได้
resource "aws_lb_listener" "public_backend_admin" {
  count             = var.expose_backend_port ? 1 : 0
  load_balancer_arn = aws_lb.public.arn
  port              = 8000
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.backend.arn
  }
}
