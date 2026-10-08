variable "region" {
  type    = string
  default = "us-east-1"
}

variable "project" {
  type    = string
  default = "netlab"
}

variable "admin_cidr" {
  description = "IP ผู้ดูแลสำหรับ SSH เช่น 1.2.3.4/32"
  type        = string
}

variable "repo_url" {
  description = "HTTPS URL ของ repo เช่น https://github.com/<owner>/<repo>.git (ห้ามใส่ token ใน URL ให้ใช้ github_token)"
  type        = string

  validation {
    condition     = !can(regex("^https?://[^/]*@", var.repo_url))
    error_message = "repo_url ห้ามมี token/รหัสผ่านฝังอยู่ ให้ตั้ง github_token แยกต่างหาก"
  }
}

variable "github_token" {
  description = "GitHub token (read-only) สำหรับ clone repo แบบ private; ว่าง = repo public แนะนำให้ตั้งผ่าน TF_VAR_github_token แทนการเขียนลงไฟล์"
  type        = string
  default     = ""
  sensitive   = true
}

variable "repo_branch" {
  type    = string
  default = "main"
}

variable "base_ami_id" {
  description = "GNS3 base AMI (ว่าง = หา AMI ชื่อ netlab-gns3-base* ที่ใหม่สุดในบัญชีนี้ ซึ่ง build_gns3_ami.py สร้างไว้)"
  type        = string
  default     = ""
}

variable "key_name" {
  description = "EC2 Key Pair ที่มีอยู่แล้ว (Learner Lab มี vockey ให้) ใช้ทั้งเครื่อง web และ VM นักศึกษา"
  type        = string
  default     = "vockey"
}

variable "web_instance_type" {
  type    = string
  default = "t3.small"
}

variable "lab_instance_type" {
  description = "DEFAULT_INSTANCE_TYPE ของ VM นักศึกษา (GNS3 แนะนำ >= t3.medium ถ้า budget ไหว)"
  type        = string
  default     = "t3.medium"
}

variable "max_concurrent_instances" {
  type    = number
  default = 3
}

variable "users_table" {
  type    = string
  default = "netlab_users"
}

variable "instances_table" {
  type    = string
  default = "netlab_instances"
}

variable "exercises_table" {
  type    = string
  default = "netlab_exercises"
}

variable "expose_backend_port" {
  description = "เปิด port 8000 (backend API) ให้เบราว์เซอร์เข้าถึงโดยตรง ใช้เมื่อ JavaScript ในหน้าเว็บเรียก API ที่ <host>:8000"
  type        = bool
  default     = false
}
