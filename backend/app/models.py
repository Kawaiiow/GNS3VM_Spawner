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

class ExerciseBase(BaseModel):
    title: str = Field(..., description="ชื่อแบบฝึกหัด Lab")
    description: Optional[str] = Field(None, description="คำอธิบายแบบฝึกหัด หรือโจทย์")
    ami_id: Optional[str] = Field(
        None, description="AWS AMI ID ของต้นแบบ VM (ถ้า AMI ถูกลบ ระบบจะกู้คืนจาก S3 ให้เองตอนสร้าง VM)"
    )
    is_active: bool = Field(default=True, description="สถานะเปิดให้นักศึกษาใช้งานหรือไม่")
    has_grading: bool = Field(default=False, description="มีระบบตรวจแบบฝึกหัดอัตโนมัติหรือไม่")
    rubric_s3_key: Optional[str] = Field(None, description="S3 object key ของไฟล์ rubric.json")
    max_attempts: int = Field(default=0, description="จำนวนครั้งสูงสุดที่ส่งได้ (0 = ไม่จำกัด)")
    keep_score_policy: str = Field(default="highest", description="นโยบายเก็บคะแนน: highest | latest")
    passing_score: int = Field(default=60, description="เกณฑ์คะแนนผ่านขั้นต่ำ")
    feedback_mode: str = Field(default="detailed", description="ระดับการแสดงผลตรวจ: detailed | checklist_only | score_only")


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


# ==========================================
# AUTOMATED GRADER & RUBRIC MODELS
# ==========================================

class RubricCheck(BaseModel):
    type: str = Field(..., description="config_regex | command_output | ping")
    description: Optional[str] = Field(None, description="คำอธิบายการตรวจ")
    pattern: Optional[str] = Field(None, description="Regex pattern สำหรับ config_regex")
    command: Optional[str] = Field(None, description="CLI command ที่จะสั่งรัน")
    must_contain: Optional[list[str]] = Field(default_factory=list, description="ข้อความ/Regex ที่ต้องมีในผลลัพธ์")
    must_not_contain: Optional[list[str]] = Field(default_factory=list, description="ข้อความ/Regex ที่ต้องไม่มีในผลลัพธ์")
    target_ip: Optional[str] = Field(None, description="IP ปลายทางสำหรับ ping")
    repeat: Optional[int] = Field(5, description="จำนวนครั้งที่ ping")
    min_success_rate: Optional[float] = Field(60.0, description="เปอร์เซ็นต์ขั้นต่ำที่ถือว่า ping ผ่าน")
    negative: Optional[bool] = Field(False, description="ถ้า True ผลลัพธ์ต้องไม่ match pattern")
    hint: Optional[str] = Field(None, description="คำใบ้เมื่อตรวจไม่ผ่าน")


class RubricTask(BaseModel):
    id: str = Field(..., description="Task identifier เช่น t1")
    name: str = Field(..., description="ชื่อโจทย์ย่อย เช่น R1 GigabitEthernet0/0 IP Config")
    node: str = Field(..., description="ชื่ออุปกรณ์ใน GNS3 เช่น R1, SW1, PC1")
    device_type: Optional[str] = Field("cisco", description="cisco | linux")
    points: int = Field(..., ge=1, description="คะแนนเต็มของข้อนี้")
    checks: list[RubricCheck] = Field(..., min_length=1, description="รายการตรวจสอบย่อย")


class RubricDefinition(BaseModel):
    version: str = Field(default="1.0", description="Rubric schema version")
    title: Optional[str] = Field(None, description="ชื่อชุดตรวจ")
    max_score: int = Field(default=100, description="คะแนนเต็มรวม")
    passing_score: int = Field(default=60, description="เกณฑ์ผ่าน")
    feedback_mode: str = Field(default="detailed", description="detailed | checklist_only | score_only")
    tasks: list[RubricTask] = Field(..., min_length=1, description="รายการโจทย์ทั้งหมด")
    credentials: Optional[dict[str, dict]] = Field(default=None, description="รหัสผ่านอุปกรณ์ เช่น enable_password")


class RubricUpdateRequest(BaseModel):
    rubric_yaml: str = Field(..., description="เนื้อหา rubric ในรูปแบบ YAML หรือ JSON")
    max_attempts: Optional[int] = Field(None, ge=0, description="จำนวนครั้งสูงสุดที่ส่งได้ (0 = ไม่จำกัด)")
    keep_score_policy: Optional[str] = Field(None, description="highest | latest")
    feedback_mode: Optional[str] = Field(None, description="detailed | checklist_only | score_only")
    passing_score: Optional[int] = Field(None, ge=0)


class GradeCheckResult(BaseModel):
    type: str
    passed: bool
    description: Optional[str] = None
    hint: Optional[str] = None
    message: Optional[str] = None
    details: Optional[str] = None


class GradeTaskResult(BaseModel):
    id: str
    name: str
    node: Optional[str] = None
    points: int
    max_points: int
    status: str = Field(..., description="passed | failed")
    checks: Optional[list[GradeCheckResult]] = None


class GradingReportResponse(BaseModel):
    status: str = Field(..., description="success | error")
    score: int = 0
    max_score: int = 100
    percentage: float = 0.0
    passed: bool = False
    passing_score: int = 60
    mode: str = Field(default="practice", description="practice | submit")
    feedback_mode: str = Field(default="detailed", description="detailed | checklist_only | score_only")
    tasks: Optional[list[GradeTaskResult]] = None
    message: Optional[str] = None
    error_code: Optional[str] = None
    evaluated_at: Optional[str] = None
    submission_id: Optional[str] = None
    attempt_number: Optional[int] = None


class SubmissionRecord(BaseModel):
    submission_id: str
    exercise_id: str
    user_id: str
    member_id: Optional[str] = None
    username: Optional[str] = None
    full_name: Optional[str] = None
    instance_id: Optional[str] = None
    score: int
    max_score: int
    percentage: float
    passed: bool
    attempt_number: int
    submitted_at: str
    tasks_summary: Optional[list[dict]] = None


class SubmissionListResponse(BaseModel):
    count: int
    exercise_id: Optional[str] = None
    submissions: list[SubmissionRecord]