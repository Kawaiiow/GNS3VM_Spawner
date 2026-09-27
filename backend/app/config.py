from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BASE_DIR / ".env"


class Settings(BaseSettings):
    """
    ค่า config ทั้งหมดจะถูกอ่านจากไฟล์ .env (ดู .env.example)
    ห้าม hardcode AWS credentials ไว้ในโค้ดเด็ดขาด

    หมายเหตุ AWS Academy Learner Lab:
    Learner Lab ไม่ให้สร้าง IAM User/Access Key เอง ต้องก็อป credentials
    ชั่วคราว (รวม session token) จากปุ่ม "AWS Details" ในหน้า Lab ทุกครั้งที่
    เปิด session ใหม่ เพราะมันหมดอายุทุก ~3-4 ชม. -> ต้องมี aws_session_token
    เพิ่มจากปกติ (ปกติ IAM user key ธรรมดาไม่ต้องมีตัวนี้)
    """

    model_config = SettingsConfigDict(
        env_file=(str(ENV_FILE), ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # AWS credentials & region
    aws_access_key_id: str
    aws_secret_access_key: str

    # >>> LEARNER LAB ONLY <<<
    # Session token ที่ได้มาพร้อมกับ Access Key/Secret จากหน้า "AWS Details"
    # ถ้าใช้ AWS account จริงกับ IAM user ปกติ ค่านี้จะไม่มี ปล่อยเป็น None ได้เลย
    # (ตอนใช้งานจริงให้ลบ field นี้ทิ้ง หรือปล่อยว่างใน .env ก็พอ ไม่ต้องลบโค้ดก็ได้
    # เพราะเราเช็ค None ก่อนส่งเข้า boto3 อยู่แล้วใน ec2_service.py)
    aws_session_token: Optional[str] = None

    # Learner Lab ล็อกให้ใช้ได้แค่ us-east-1 เท่านั้น
    # ถ้าใช้ AWS account จริง เปลี่ยนเป็น region ที่ต้องการได้อิสระ เช่น ap-southeast-1
    aws_region: str = "us-east-1"

    # ค่า default สำหรับสร้าง EC2 instance (GNS3 VM)
    default_ami_id: str            # AMI ที่ลง GNS3 ไว้แล้ว (ทำจาก GNS3 VM appliance)
    # Learner Lab บาง lab บล็อก instance type ที่ใหญ่กว่า micro/small เพื่อกัน budget
    # หมด ถ้าใช้ account จริงเปลี่ยนกลับเป็น t2.medium/t3.medium ได้ตามต้องการ
    default_instance_type: str = "t2.micro"
    default_key_name: str          # ชื่อ EC2 Key Pair ที่สร้างไว้ใน AWS Console
    default_security_group_id: str  # SG ที่เปิด port ที่ GNS3 ต้องใช้ (เช่น 80, 443, 3080, VNC range)

    # >>> LEARNER LAB ONLY <<<
    # ชื่อ IAM Role สำหรับแนบเป็น instance profile ตอน launch instance (ถ้า GNS3 VM
    # ต้องเรียก AWS service อื่น เช่น S3) Learner Lab ไม่ให้สร้าง Role เอง ต้องใช้
    # Role ชื่อ "LabRole" ที่ระบบเตรียมไว้ให้เท่านั้น
    # ถ้าใช้ AWS account จริง ให้สร้าง IAM Role เองตาม least-privilege แล้วเปลี่ยน
    # ค่านี้เป็นชื่อ role ที่สร้างเอง (หรือปล่อย None ถ้า instance ไม่ต้องเรียก
    # AWS service อื่นเลย)
    instance_profile_name: Optional[str] = "LabRole"

    # จำกัดจำนวน instance ที่ระบบสร้างพร้อมกันได้ (กันค่าใช้จ่ายบานปลาย/โควตานักศึกษา)
    # Learner Lab มี budget จำกัดต่อ lab (มักไม่กี่สิบ USD) แนะนำตั้งค่าต่ำไว้ก่อน
    max_concurrent_instances: int = 3

    # DynamoDB Tables & Endpoint
    users_table_name: str = "netlab_users"
    instances_table_name: str = "netlab_instances"
    exercises_table_name: str = "netlab_exercises"
    dynamodb_endpoint_url: Optional[str] = None

    # JWT Authentication
    jwt_secret_key: str = "netlab-super-secret-key-change-in-env-file"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440


@lru_cache
def get_settings() -> Settings:
    return Settings()
