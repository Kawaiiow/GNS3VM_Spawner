# เก็บไฟล์ .gns3project ที่ backend export จาก GNS3 ของอาจารย์
# private ทั้งหมด: VM นักศึกษาดาวน์โหลดผ่าน presigned URL อายุสั้นที่ backend ออกให้

resource "random_id" "suffix" {
  byte_length = 4
}

# bucket สร้างไว้แล้ว อ้างผ่าน data source เพื่อเลี่ยง GetBucketObjectLockConfiguration ที่ถูก SCP บล็อก
data "aws_s3_bucket" "snapshots" {
  bucket = "${var.project}-snapshots-${random_id.suffix.hex}"
}

resource "aws_s3_bucket_public_access_block" "snapshots" {
  bucket                  = data.aws_s3_bucket.snapshots.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}