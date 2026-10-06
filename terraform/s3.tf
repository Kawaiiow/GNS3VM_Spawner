# เก็บไฟล์ .gns3project ที่ backend export จาก GNS3 ของอาจารย์
# private ทั้งหมด: VM นักศึกษาดาวน์โหลดผ่าน presigned URL อายุสั้นที่ backend ออกให้
#
# หมายเหตุ: Learner Lab (SCP) บล็อก s3:GetBucketObjectLockConfiguration ทำให้
# resource "aws_s3_bucket" ล้มตอนสร้าง/refresh จึงสร้าง-ลบ bucket ด้วยสคริปต์ s3_bucket.py (boto3)
# แล้วอ้างอิงด้วย data source (ต้องมี python + boto3 และโหลด credentials ใน terminal แล้ว)
# ถ้าเครื่องใช้ `py` แทน `python` ให้แก้ค่า python_cmd ด้านล่าง

resource "random_id" "suffix" {
  byte_length = 4
}

locals {
  snapshots_bucket_name = "${var.project}-snapshots-${random_id.suffix.hex}"
  python_cmd            = "python"
}

# สร้าง bucket ตอน apply และลบ (พร้อมไฟล์ข้างใน) ตอน destroy
resource "terraform_data" "snapshots_bucket" {
  input = {
    name   = local.snapshots_bucket_name
    region = var.region
    python = local.python_cmd
    script = "${path.module}/s3_bucket.py"
  }

  provisioner "local-exec" {
    command = "${self.input.python} ${self.input.script} create ${self.input.name} ${self.input.region}"
  }

  provisioner "local-exec" {
    when       = destroy
    on_failure = continue
    command    = "${self.input.python} ${self.input.script} delete ${self.input.name} ${self.input.region}"
  }
}

data "aws_s3_bucket" "snapshots" {
  bucket     = local.snapshots_bucket_name
  depends_on = [terraform_data.snapshots_bucket]
}

resource "aws_s3_bucket_public_access_block" "snapshots" {
  bucket                  = data.aws_s3_bucket.snapshots.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
