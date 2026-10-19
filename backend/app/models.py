from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field, field_validator

# ค่า placeholder ที่ Swagger UI (/docs) ใส่ให้อัตโนมัติตอนกด "Try it out"
# ถ้าไม่ลบทิ้ง ระบบจะเข้าใจว่าเป็นค่าจริง (เช่น ami_id="string") แล้วพัง
_SWAGGER_PLACEHOLDERS = {"", "string"}


def _blank_to_none(v: Any) -> Any:
    """ข้อความว่าง/"string" ของ Swagger -> None (ถือว่าไม่ได้ระบุ)"""
    if isinstance(v, str):
        v = v.strip()
        if v.lower() in _SWAGGER_PLACEHOLDERS:
            return None
    return v


def _clean_str_list(v: Any) -> Any:
    """ลบ placeholder ออกจาก list ของข้อความ ถ้าไม่เหลืออะไร -> None"""
    if isinstance(v, list):
        cleaned = [
            x.strip()
            for x in v
            if isinstance(x, str) and x.strip().lower() not in _SWAGGER_PLACEHOLDERS
        ]
        return cleaned or None
    return v


class UserRole(str, Enum):
    STUDENT = "student"
    INSTRUCTOR = "instructor"
    ADMIN = "admin"


class UserBase(BaseModel):
    username: str = Field(..., description="ชื่อผู้ใช้สำหรับเข้าสู่ระบบ")
    member_id: str = Field(..., description="รหัสประจำตัว / รหัสนักศึกษา / รหัสสมาชิก (Member ID)")
    full_name: Optional[str] = Field(None, description="ชื่อ-นามสกุลจริง")
    role: UserRole = Field(default=UserRole.STUDENT, description="บทบาทผู้ใช้")


class UserCreate(UserBase):
    password: str = Field(..., min_length=6, description="รหัสผ่าน")


class UserResponse(UserBase):
    user_id: str
    active_instance_id: Optional[str] = None  # Sandbox VM ที่ใช้อยู่ (นักศึกษา)
    active_exercise_instance_id: Optional[str] = None  # Exercise VM ที่ใช้อยู่ (นักศึกษา)
    created_at: str
    updated_at: str


class UserInDB(UserResponse):
    password_hash: str


class LoginRequest(BaseModel):
    identifier: str = Field(..., description="ชื่อผู้ใช้ (Username) หรือ รหัสประจำตัว (Member ID)")
    password: str = Field(..., description="รหัสผ่าน")


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


# ==========================================
# EXERCISE MODELS
# ==========================================

class GradingCheckType(str, Enum):
    PING = "ping"
    VPCS_SHOW_IP = "vpcs_show_ip"
    CLI_COMMAND = "cli_command"


class TestCase(BaseModel):
    id: str = Field(..., description="รหัสการทดสอบ เช่น test_1")
    title: str = Field(..., description="ชื่อการทดสอบ เช่น ตรวจสอบการ ping 8.8.8.8 จาก PC1")
    node: str = Field(..., description="ชื่อ node ใน GNS3 เช่น PC1, R1, Switch1")
    type: GradingCheckType = Field(
        default=GradingCheckType.PING,
        description="ประเภทการตรวจสอบ: ping, vpcs_show_ip, cli_command",
    )
    # สำหรับ ping:
    target: Optional[str] = Field(None, description="IP หรือ Hostname ปลายทาง (สำหรับ ping)")
    count: int = Field(default=3, ge=1, le=10, description="จำนวน packet ที่ ping")
    expected: str = Field(default="success", description="ผลที่คาดหวัง: success หรือ unreachable")
    # สำหรับ vpcs_show_ip:
    expected_ip: Optional[str] = Field(None, description="IP address ที่คาดหวัง")
    expected_mask: Optional[str] = Field(None, description="Subnet mask/prefix เช่น 24 หรือ 255.255.255.0")
    expected_gateway: Optional[str] = Field(None, description="Gateway IP ที่คาดหวัง")
    # สำหรับ cli_command:
    command: Optional[str] = Field(None, description="คำสั่ง CLI เช่น show ip interface brief หรือ show ip route")
    contains: Optional[list[str]] = Field(None, description="ข้อความที่ต้องพบในผลลัพธ์ (ทุกคำ)")
    not_contains: Optional[list[str]] = Field(None, description="ข้อความที่ต้องไม่พบในผลลัพธ์")
    # คะแนน:
    points: int = Field(default=10, ge=1, description="คะแนนของการทดสอบนี้")


class GradingConfig(BaseModel):
    auto_start_nodes: bool = Field(default=True, description="เปิด node อัตโนมัติถ้า node ปิดอยู่ก่อนตรวจ")
    timeout_seconds: int = Field(default=12, ge=3, le=60, description="เวลา timeout ต่อการทดสอบ (วินาที)")
    test_cases: list[TestCase] = Field(default_factory=list, description="รายการแบบทดสอบ")


class TestCaseResult(BaseModel):
    test_id: str
    title: str
    node: str
    status: str = Field(..., description="สถานะ: PASSED | FAILED | ERROR")
    points_awarded: int
    max_points: int
    message: str
    output_snippet: Optional[str] = None


class GradeSubmissionResponse(BaseModel):
    exercise_id: str
    instance_id: str
    total_score: int
    max_score: int
    percentage: float
    passed_count: int
    total_count: int
    results: list[TestCaseResult]
    checked_at: str


class ExerciseBase(BaseModel):
    title: str = Field(..., description="ชื่อแบบฝึกหัด Lab")
    description: Optional[str] = Field(None, description="คำอธิบายแบบฝึกหัด หรือโจทย์")
    ami_id: Optional[str] = Field(
        None, description="AWS AMI ID ของต้นแบบ VM (ถ้า AMI ถูกลบ ระบบจะกู้คืนจาก S3 ให้เองตอนสร้าง VM)"
    )
    is_active: bool = Field(default=True, description="สถานะเปิดให้นักศึกษาใช้งานหรือไม่")


class ExerciseCreate(BaseModel):
    title: str = Field(..., min_length=1, description="ชื่อแบบฝึกหัด Lab (จำเป็น)")
    description: str = Field(..., min_length=1, description="คำอธิบายแบบฝึกหัด หรือโจทย์ (จำเป็น)")
    instance_id: Optional[str] = Field(
        None, description="EC2 Instance ID ของอาจารย์ที่ต้องการทำ Snapshot (ถ้าไม่ระบุ จะดึงจาก VM ปัจจุบันของผู้สอน)"
    )
    project_name: Optional[str] = Field(
        None, description="ชื่อโปรเจ็ค GNS3 ที่ต้องการให้อยู่ในต้นแบบ VM (ไม่ระบุอะไรเลย = ทุกโปรเจ็ค)"
    )
    project_names: Optional[list[str]] = Field(
        None, description="หลายชื่อโปรเจ็ค (เลือกเฉพาะบางโปรเจ็ค)"
    )
    project_id: Optional[str] = Field(
        None, description="GNS3 project ID (ใช้แทนชื่อได้ กรณีชื่อโปรเจ็คซ้ำกัน)"
    )
    project_ids: Optional[list[str]] = Field(
        None, description="หลาย GNS3 project ID"
    )
    ami_id: Optional[str] = Field(
        None, description="AMI ID (ถ้ามี AMI อยู่แล้วและไม่ต้องการทำ Snapshot ใหม่)"
    )
    grading_config: Optional[GradingConfig] = Field(
        None, description="การตั้งค่าโจทย์และการตรวจอัตโนมัติ (Test Cases)"
    )

    @field_validator(
        "instance_id", "project_name", "project_id", "ami_id", mode="before"
    )
    @classmethod
    def _clean_optional_str(cls, v: Any) -> Any:
        return _blank_to_none(v)

    @field_validator("project_names", "project_ids", mode="before")
    @classmethod
    def _clean_optional_list(cls, v: Any) -> Any:
        return _clean_str_list(v)


class ExerciseResponse(ExerciseBase):
    exercise_id: str
    instructor_id: str
    status: str = Field(..., description="สถานะต้นแบบ VM: pending | available | failed")
    s3_key: Optional[str] = Field(None, description="S3 object key ของต้นแบบ (โหมด gns3project = ไฟล์โปรเจ็คแรก, โหมด ami = AMI ที่สำรองไว้)")
    s3_keys: Optional[list[str]] = Field(None, description="S3 key ของไฟล์ .gns3project แต่ละโปรเจ็ค (เรียงตาม project_names)")
    images: Optional[list[dict]] = Field(
        None, description="image (IOS/IOU/QEMU) ที่โปรเจ็คใช้ พร้อม S3 key ใน library (VM ใหม่จะโหลดก่อน import โปรเจ็ค)"
    )
    templates_key: Optional[str] = Field(None, description="S3 key ของ templates.json (GNS3 template ที่จะสร้างคืนบน VM ใหม่)")
    template_names: Optional[list[str]] = Field(None, description="ชื่อ GNS3 template ที่สำรองไว้")
    project_name: Optional[str] = Field(None, description="ชื่อโปรเจ็คในต้นแบบ (หลายโปรเจ็คคั่นด้วย ,)")
    project_names: Optional[list[str]] = Field(None, description="รายชื่อโปรเจ็ค GNS3 ทั้งหมดในต้นแบบ VM")
    project_count: Optional[int] = Field(None, description="จำนวนโปรเจ็คในต้นแบบ VM")
    status_detail: Optional[str] = Field(None, description="ความคืบหน้าตอน pending / สาเหตุเมื่อ failed")
    grading_config: Optional[GradingConfig] = Field(None, description="กติกาการตรวจอัตโนมัติ")
    created_at: str


class ExerciseListResponse(BaseModel):
    count: int
    exercises: list[ExerciseResponse]


# ==========================================
# INSTANCE (VM) MODELS
# ==========================================

class LaunchInstanceRequest(BaseModel):
    """Request body ตอนขอสร้าง GNS3 VM ใหม่"""

    instance_name: str = Field(..., description="ชื่อ instance เช่น gns3-lab1-vm")
    exercise_id: Optional[str] = Field(
        None, description="รหัสแบบฝึกหัด Lab (ถ้าต้องการสร้าง VM จาก Template แบบฝึกหัด)"
    )
    instance_type: Optional[str] = Field(
        None, description="ถ้าไม่ระบุจะใช้ค่า default จาก config (t2.micro/t2.medium)"
    )
    ami_id: Optional[str] = Field(
        None, description="ถ้าไม่ระบุจะใช้ AMI ของ exercise หรือ AMI GNS3 default จาก config"
    )

    @field_validator("exercise_id", "instance_type", "ami_id", mode="before")
    @classmethod
    def _clean_optional_str(cls, v: Any) -> Any:
        return _blank_to_none(v)


class InstanceActionResponse(BaseModel):
    instance_id: str
    state: str
    message: str
    public_ip: Optional[str] = None


class SetTimerRequest(BaseModel):
    minutes: int = Field(
        ..., ge=1, description="เวลาที่เหลือก่อน VM ถูก stop (นาที) นับจากตอนที่เรียก API"
    )


class ExtendTimerResponse(BaseModel):
    instance_id: str
    expires_at: int = Field(..., description="เวลาที่ระบบจะ stop VM (epoch วินาที, UTC)")
    remaining_seconds: int = Field(..., description="เวลาที่เหลือก่อนถูก stop (วินาที)")
    message: str


class InstanceInfo(BaseModel):
    instance_id: str
    user_id: Optional[str] = None
    exercise_id: Optional[str] = None
    name: Optional[str] = None
    state: str
    instance_type: Optional[str] = None
    public_ip: Optional[str] = None
    private_ip: Optional[str] = None
    launch_time: Optional[str] = None
    created_at: Optional[str] = None
    terminated_at: Optional[str] = None
    # Auto-stop (เฉพาะ VM ของ student): epoch วินาทีที่ระบบจะ stop VM และเวลาที่เหลือ
    auto_stop: Optional[bool] = None
    expires_at: Optional[int] = None
    remaining_seconds: Optional[int] = None
    # Login ของ GNS3 server บน VM นี้ (ส่งให้เจ้าของ VM เท่านั้น)
    gns3_user: Optional[str] = None
    gns3_password: Optional[str] = None


class InstanceListResponse(BaseModel):
    count: int
    instances: list[InstanceInfo]


# ==========================================
# ADMIN / DASHBOARD MODELS
# ==========================================

class UserUpdate(BaseModel):
    """ฟิลด์ที่ Admin แก้ไขได้ (ส่งเฉพาะที่ต้องการเปลี่ยน)"""

    username: Optional[str] = Field(None, min_length=1, description="ชื่อผู้ใช้ใหม่")
    member_id: Optional[str] = Field(None, min_length=1, description="รหัสประจำตัวใหม่")
    full_name: Optional[str] = Field(None, description="ชื่อ-นามสกุลใหม่")
    role: Optional[UserRole] = Field(None, description="บทบาทใหม่")
    password: Optional[str] = Field(None, min_length=6, description="รหัสผ่านใหม่ (รีเซ็ต)")


class DashboardInstance(BaseModel):
    instance_id: str
    name: Optional[str] = None
    kind: str = Field(..., description="sandbox | exercise")
    exercise_id: Optional[str] = None
    state: Optional[str] = None
    public_ip: Optional[str] = None


class DashboardUserInfo(BaseModel):
    """หนึ่งแถวใน Dashboard: ผู้ใช้ + Instance (Sandbox/Exercise) ทั้งหมดที่ยังไม่ถูกลบ"""

    user_id: str
    username: str
    member_id: str
    full_name: Optional[str] = None
    role: UserRole
    instances: list[DashboardInstance] = Field(default_factory=list)