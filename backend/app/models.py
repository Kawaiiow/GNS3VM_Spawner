from typing import Optional
from pydantic import BaseModel, Field


class LaunchInstanceRequest(BaseModel):
    """Request body ตอนนักศึกษาขอสร้าง GNS3 VM ใหม่"""

    student_id: str = Field(..., description="รหัสนักศึกษา หรือ user id ที่ขอสร้าง VM")
    instance_name: str = Field(..., description="ชื่อ instance เช่น gns3-6410000-vm1")
    instance_type: Optional[str] = Field(
        None, description="ถ้าไม่ระบุจะใช้ค่า default จาก config (t2.medium)"
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


class InstanceListResponse(BaseModel):
    count: int
    instances: list[InstanceInfo]
