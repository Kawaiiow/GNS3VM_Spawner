from typing import Optional

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

from app import ec2_service
from app.models import (
    InstanceActionResponse,
    InstanceInfo,
    InstanceListResponse,
    LaunchInstanceRequest,
)

app = FastAPI(
    title="GNS3 Cloud - EC2 API",
    description="API สำหรับสร้างและจัดการ GNS3 VM บน AWS EC2 ให้นักศึกษา",
    version="1.0.0",
)

# เปิด CORS ให้ frontend (เว็บที่นักศึกษาใช้ขอสร้าง VM) เรียกเข้ามาได้
# ในโปรดักชันควรระบุ origin ของเว็บจริงแทน "*"
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.post("/instances", response_model=InstanceInfo, status_code=201)
def create_instance(payload: LaunchInstanceRequest):
    """สร้าง (launch) GNS3 VM instance ใหม่บน EC2 ตามคำขอของนักศึกษา"""
    return ec2_service.launch_instance(
        student_id=payload.student_id,
        instance_name=payload.instance_name,
        instance_type=payload.instance_type,
        ami_id=payload.ami_id,
    )


@app.get("/instances", response_model=InstanceListResponse)
def get_instances(
    student_id: Optional[str] = Query(
        None, description="ระบุเพื่อ filter ดูเฉพาะ instance ของนักศึกษาคนนั้น"
    )
):
    """List instance ทั้งหมดของระบบ (หรือ filter ตาม student_id) พร้อมสถานะปัจจุบัน"""
    instances = ec2_service.list_instances(student_id=student_id)
    return InstanceListResponse(count=len(instances), instances=instances)


@app.post("/instances/{instance_id}/start", response_model=InstanceActionResponse)
def start_instance(instance_id: str):
    """เปิดเครื่อง instance ที่ถูก stop ไว้"""
    return ec2_service.start_instance(instance_id)


@app.post("/instances/{instance_id}/stop", response_model=InstanceActionResponse)
def stop_instance(instance_id: str):
    """ปิดเครื่อง instance ชั่วคราว (ยังไม่ลบ ยังเสียค่า storage อยู่)"""
    return ec2_service.stop_instance(instance_id)


@app.delete("/instances/{instance_id}", response_model=InstanceActionResponse)
def delete_instance(instance_id: str):
    """ลบ (terminate) instance ถาวร - ใช้ตอนนักศึกษาเลิกใช้ VM แล้ว"""
    return ec2_service.terminate_instance(instance_id)
