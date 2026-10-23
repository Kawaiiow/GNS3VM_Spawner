output "web_url" {
  description = "URL เปิดเว็บ HTTPS (ผ่าน ALB สาธารณะ port 443)"
  value       = "https://${aws_lb.public.dns_name}"
}

output "web_http_url" {
  description = "URL เปิดเว็บ HTTP (ผ่าน ALB สาธารณะ port 80 - redirect ไป HTTPS)"
  value       = "http://${aws_lb.public.dns_name}"
}

output "ssl_certificate_arn" {
  description = "ARN ของ Certificate ที่ใช้งานบน ALB"
  value       = local.alb_certificate_arn
}


output "alb_dns_name" {
  value = aws_lb.public.dns_name
}

output "backend_url" {
  description = "BACKEND_URL ที่ frontend ใช้ (ALB สาธารณะ port 8000)"
  value       = "http://${aws_lb.public.dns_name}:8000"
}

output "availability_zones_used" {
  description = "AZ ที่ ALB / Frontend / Backend กระจายอยู่"
  value       = local.app_azs
}

output "frontend_asg_name" {
  value = aws_autoscaling_group.frontend.name
}

output "backend_asg_name" {
  value = aws_autoscaling_group.backend.name
}

output "gns3_ami_used" {
  value = local.gns3_ami_id
}

output "gns3_vm_sg_id" {
  value = aws_security_group.gns3_vm.id
}

output "snapshots_bucket" {
  value = data.aws_s3_bucket.snapshots.id
}

output "vpc_id" {
  value = aws_vpc.main.id
}

output "lab_subnet_id" {
  description = "Subnet ที่ backend ใช้สร้าง VM นักศึกษา (DEFAULT_SUBNET_ID)"
  value       = aws_subnet.lab.id
}

output "lab_az" {
  value = aws_subnet.lab.availability_zone
}
