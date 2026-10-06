output "web_url" {
  value = "http://${aws_eip.web.public_ip}:8080"
}

output "web_public_ip" {
  value = aws_eip.web.public_ip
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
