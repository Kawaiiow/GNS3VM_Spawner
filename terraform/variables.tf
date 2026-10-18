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

variable "frontend_instance_type" {
  description = "ชนิดเครื่อง Frontend (ต่อ 1 เครื่องใน ASG)"
  type        = string
  default     = "t3.small"
}

variable "backend_instance_type" {
  description = "ชนิดเครื่อง Backend (ต่อ 1 เครื่องใน ASG)"
  type        = string
  default     = "t3.small"
}

variable "frontend_count" {
  description = "จำนวนเครื่อง Frontend ใน ASG (ขนาดคงที่ กระจายตาม AZ) อย่างน้อย 2 เพื่อให้ทนการล่มของ AZ"
  type        = number
  default     = 2

  validation {
    condition     = var.frontend_count >= 1
    error_message = "frontend_count ต้องมากกว่าหรือเท่ากับ 1 (แนะนำ 2 ขึ้นไป)"
  }
}

variable "backend_count" {
  description = "จำนวนเครื่อง Backend ใน ASG (ขนาดคงที่ กระจายตาม AZ) อย่างน้อย 2 เพื่อให้ทนการล่มของ AZ"
  type        = number
  default     = 2

  validation {
    condition     = var.backend_count >= 1
    error_message = "backend_count ต้องมากกว่าหรือเท่ากับ 1 (แนะนำ 2 ขึ้นไป)"
  }
}

variable "az_count" {
  description = "จำนวน AZ ที่ใช้วาง ALB และเครื่อง Frontend/Backend (เลือก AZ แรกๆ ตามตัวอักษรใน default VPC)"
  type        = number
  default     = 2

  validation {
    condition     = var.az_count >= 2 && var.az_count <= 4
    error_message = "az_count ต้องอยู่ระหว่าง 2 ถึง 4"
  }
}

variable "health_check_grace_period" {
  description = "วินาทีที่ ASG รอก่อนเริ่มนับ health check ของเครื่องใหม่ (ต้องนานกว่าเวลา clone + docker build ~3-5 นาที)"
  type        = number
  default     = 600
}

variable "alb_idle_timeout" {
  description = "idle timeout ของ ALB (วินาที) ต้องมากกว่าคำสั่งที่นานที่สุดที่ frontend รอ backend (เช่น start VM ~150 วินาที)"
  type        = number
  default     = 600
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
  description = "เปิด port 8000 (backend API) บน ALB สาธารณะ เฉพาะ admin_cidr เพื่อให้ terraform destroy เรียก API ลบ VM/AMI ที่ระบบสร้าง (ปกติปิดไว้ ถ้าปิดจะใช้ aws CLI fallback ตอน destroy)"
  type        = bool
  default     = false
}


variable "gns3_export_include_images" {
  type    = bool
  default = true
}