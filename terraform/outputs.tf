output "web_url" {
  description = "URL เปิดเว็บ (ผ่าน ALB สาธารณะ port 80)"
  value       = "http://${aws_lb.public.dns_name}"
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
