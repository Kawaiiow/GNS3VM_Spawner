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

# ---------- SSL / TLS Certificate (ACM / Self-Signed) ----------
# หากไม่ได้ระบุ var.certificate_arn จะสร้าง self-signed certificate และ import เข้า ACM ให้อัตโนมัติ
resource "tls_private_key" "alb_self_signed" {
  count     = var.certificate_arn == "" ? 1 : 0
  algorithm = "RSA"
  rsa_bits  = 2048
}

resource "tls_self_signed_cert" "alb_self_signed" {
  count           = var.certificate_arn == "" ? 1 : 0
  private_key_pem = tls_private_key.alb_self_signed[0].private_key_pem

  subject {
    common_name  = "${var.project}.local"
    organization = "NetLab"
  }

  validity_period_hours = 8760 # 1 ปี

  allowed_uses = [
    "key_encipherment",
    "digital_signature",
    "server_auth",
  ]
}

resource "aws_acm_certificate" "alb_self_signed" {
  count            = var.certificate_arn == "" ? 1 : 0
  private_key      = tls_private_key.alb_self_signed[0].private_key_pem
  certificate_body = tls_self_signed_cert.alb_self_signed[0].cert_pem

  tags = {
    Name    = "${var.project}-self-signed-cert"
    Project = "gns3-cloud"
  }

  lifecycle {
    create_before_destroy = true
  }
}

locals {
  alb_certificate_arn = var.certificate_arn != "" ? var.certificate_arn : aws_acm_certificate.alb_self_signed[0].arn
}

resource "aws_lb_listener" "public_http" {
  load_balancer_arn = aws_lb.public.arn
  port              = 80
  protocol          = "HTTP"

  dynamic "default_action" {
    for_each = var.redirect_http_to_https ? [1] : []
    content {
      type = "redirect"
      redirect {
        port        = "443"
        protocol    = "HTTPS"
        status_code = "HTTP_301"
      }
    }
  }

  dynamic "default_action" {
    for_each = var.redirect_http_to_https ? [] : [1]
    content {
      type             = "forward"
      target_group_arn = aws_lb_target_group.frontend.arn
    }
  }
}

resource "aws_lb_listener" "public_https" {
  load_balancer_arn = aws_lb.public.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = var.ssl_policy
  certificate_arn   = local.alb_certificate_arn

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
