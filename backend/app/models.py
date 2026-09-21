from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class UserRole(str, Enum):
    STUDENT = "student"
    INSTRUCTOR = "instructor"
    ADMIN = "admin"


class UserBase(BaseModel):
    username: str = Field(..., description="ชื่อผู้ใช้สำหรับเข้าสู่ระบบ")
    student_id: str = Field(..., description="รหัสนักศึกษา หรือ รหัสประจำตัว")
    full_name: Optional[str] = Field(None, description="ชื่อ-นามสกุลจริง")
    role: UserRole = Field(default=UserRole.STUDENT, description="บทบาทผู้ใช้")


class UserCreate(UserBase):
    password: str = Field(..., min_length=6, description="รหัสผ่าน")


class UserResponse(UserBase):
    user_id: str
    active_instance_id: Optional[str] = None
    created_at: str
    updated_at: str


class UserInDB(UserResponse):
    password_hash: str


class LoginRequest(BaseModel):
    identifier: str = Field(..., description="ชื่อผู้ใช้ (Username) หรือ รหัสนักศึกษา (Student ID)")
    password: str = Field(..., description="รหัสผ่าน")


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


class LaunchInstanceRequest(BaseModel):
    """Request body ตอนขอสร้าง GNS3 VM ใหม่"""

    instance_name: str = Field(..., description="ชื่อ instance เช่น gns3-6410000-vm1")
    student_id: Optional[str] = Field(
        None, description="รหัสนักศึกษา (ถ้าไม่ส่งจะใช้จากข้อมูลล็อกอินของ user)"
    )
    instance_type: Optional[str] = Field(
        None, description="ถ้าไม่ระบุจะใช้ค่า default จาก config (t2.micro/t2.medium)"
    )
    ami_id: Optional[str] = Field(
        None, description="ถ้าไม่ระบุจะใช้ AMI GNS3 default จาก config"
    )


class InstanceActionResponse(BaseModel):
    instance_id: str
    state: str
    message: str


class InstanceInfo(BaseModel):
    instance_id: str
    name: Optional[str] = None
    state: str
    instance_type: str
    public_ip: Optional[str] = None
    private_ip: Optional[str] = None
    launch_time: Optional[str] = None
    student_id: Optional[str] = None
    user_id: Optional[str] = None
    created_at: Optional[str] = None
    terminated_at: Optional[str] = None


class InstanceListResponse(BaseModel):
    count: int
    instances: list[InstanceInfo]
