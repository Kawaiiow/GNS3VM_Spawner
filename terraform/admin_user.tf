# วางไฟล์นี้ในโฟลเดอร์ terraform/ (ข้างๆ variables.tf)
# ใช้สร้างบัญชี admin คนแรกอัตโนมัติหลัง terraform apply

variable "admin_username" {
  description = "username ของ admin คนแรก"
  type        = string
  default     = "admin"
}

variable "admin_member_id" {
  description = "member id ของ admin คนแรก (ตรงกับ -m ใน create_user.py)"
  type        = string
  default     = "ADMIN01"
}

variable "admin_password" {
  description = "รหัสผ่าน admin คนแรก ตั้งผ่าน TF_VAR_admin_password (ไม่ต้องเขียนลงไฟล์)"
  type        = string
  sensitive   = true

  validation {
    condition     = length(var.admin_password) >= 6
    error_message = "admin_password ต้องยาวอย่างน้อย 6 ตัวอักษร"
  }
}
