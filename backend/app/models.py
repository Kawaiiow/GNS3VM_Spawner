from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


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
    ami_id: str = Field(..., description="AWS AMI Image ID ที่เป็น Snapshot ของแบบฝึกหัดนี้")
    is_active: bool = Field(default=True, description="สถานะเปิดให้นักศึกษาใช้งานหรือไม่")


class ExerciseCreate(BaseModel):
    title: str = Field(..., min_length=1, description="ชื่อแบบฝึกหัด Lab (จำเป็น)")
    description: str = Field(..., min_length=1, description="คำอธิบายแบบฝึกหัด หรือโจทย์ (จำเป็น)")
    instance_id: Optional[str] = Field(
        None, description="EC2 Instance ID ของอาจารย์ที่ต้องการทำ Snapshot (ถ้าไม่ระบุ จะดึงจาก VM ปัจจุบันของผู้สอน)"
    )
    ami_id: Optional[str] = Field(
        None, description="AMI ID (ถ้ามี AMI อยู่แล้วและไม่ต้องการทำ Snapshot ใหม่)"
    )


class ExerciseResponse(ExerciseBase):
    exercise_id: str
    instructor_id: str
    status: str = Field(..., description="สถานะ AMI snapshot: pending | available | failed")
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


class InstanceActionResponse(BaseModel):
    instance_id: str
    state: str
    message: str
    public_ip: Optional[str] = None


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