"""
exercise_service.py
-------------------
สร้าง "ต้นแบบ VM" ของแบบฝึกหัด แล้วสำรองลง S3 (รันเบื้องหลังจาก POST /exercises)

ขั้นตอน (status = pending -> available | failed, ความคืบหน้าอยู่ใน status_detail):
  1) snapshot VM ของอาจารย์เป็น AMI (มีทุกโปรเจ็คครบ รวมดิสก์/อิมเมจของ node)
  2) ถ้าเลือกเฉพาะบางโปรเจ็ค: เปิด VM ชั่วคราวจาก AMI นั้น -> ลบโปรเจ็คที่ไม่เลือกออก -> snapshot เป็น AMI ใหม่
     (ถ้าเลือกทุกโปรเจ็ค/ไม่ระบุ ข้ามขั้นนี้ ใช้ AMI จากข้อ 1 เลย)
  3) สำรอง AMI ลง S3 (EC2 CreateStoreImageTask) -> ได้ s3_key
  4) บันทึก ami_id + s3_key ลง DynamoDB แล้ว status = available
ตอนสร้าง VM นักศึกษา: ใช้ AMI นี้ได้ทันที ถ้า AMI หายไปจะกู้คืนจาก S3 ให้อัตโนมัติ (ดู ec2_service._ensure_template_ready)
"""

from typing import Optional

from app import ec2_service, gns3_service
from app.dynamodb_service import update_exercise_fields, update_exercise_status


def _error_text(e: Exception) -> str:
    return str(getattr(e, "detail", None) or e)[:500]


def _progress(exercise_id: str, text: str) -> None:
    try:
        update_exercise_status(exercise_id, "pending", detail=text)
    except Exception:  # noqa: BLE001 - อัปเดตความคืบหน้าพลาดไม่ควรทำให้งานล้ม
        pass


def build_exercise_template(
    exercise_id: str,
    instructor_id: str,
    instance_rec: dict,
    selected_project_ids: list[str],
    export_all: bool,
) -> None:
    settings_key = f"netlab-ex-{exercise_id}"
    src_ami: Optional[str] = None      # AMI ชั่วคราวของ VM อาจารย์ (ขั้น 1)
    final_ami: Optional[str] = None    # AMI ต้นแบบที่จะเก็บ
    builder_id: Optional[str] = None   # VM ชั่วคราว
    stored = False
    try:
        # 1) snapshot VM อาจารย์
        _progress(exercise_id, "1/3 กำลังสร้าง snapshot (AMI) จาก VM ของอาจารย์")
        src_ami = ec2_service.create_instance_image(
            instance_rec["instance_id"],
            name=f"{settings_key}-src",
            description=f"NetLab exercise {exercise_id} (source snapshot)",
            no_reboot=True,
        )
        ec2_service.wait_for_image(src_ami)

        if export_all:
            final_ami, src_ami = src_ami, None
        else:
            # 2) clone -> ลบโปรเจ็คที่ไม่เลือก -> snapshot ใหม่
            _progress(exercise_id, "2/3 กำลังเตรียมต้นแบบเฉพาะโปรเจ็คที่เลือก (VM ชั่วคราว)")
            builder = ec2_service.launch_builder_instance(
                src_ami,
                instance_name=f"{settings_key}-builder",
                instance_type=instance_rec.get("instance_type") or None,
                user_id=instructor_id,
            )
            builder_id = builder["instance_id"]
            base, auth = gns3_service.wait_until_ready(builder)
            remaining = gns3_service.keep_only_projects(base, auth, selected_project_ids)
            if set(remaining) != set(selected_project_ids):
                raise RuntimeError("โปรเจ็คที่เหลือใน VM ชั่วคราวไม่ตรงกับที่เลือก")
            # VM ชั่วคราวรีบูตได้ -> ได้ image ที่ filesystem สมบูรณ์
            final_ami = ec2_service.create_instance_image(
                builder_id,
                name=settings_key,
                description=f"NetLab exercise {exercise_id}",
                no_reboot=False,
            )
            ec2_service.wait_for_image(final_ami)
            ec2_service.terminate_builder_instance(builder_id)
            builder_id = None
            ec2_service.deregister_image(src_ami)
            src_ami = None

        # 3) สำรองลง S3
        _progress(exercise_id, "3/3 กำลังสำรองต้นแบบ VM ลง S3 (อาจใช้เวลาหลายนาที)")
        s3_key = ec2_service.store_image_to_s3(final_ami)
        stored = True

        update_exercise_fields(exercise_id, {"ami_id": final_ami, "s3_key": s3_key})
        update_exercise_status(exercise_id, "available")
    except Exception as e:  # noqa: BLE001 - ต้องจับทุกอย่างเพื่อไม่ให้ค้าง pending
        # เก็บกวาดทรัพยากรที่สร้างค้างไว้
        if builder_id:
            ec2_service.terminate_builder_instance(builder_id)
        for ami in (src_ami, final_ami if not stored else None):
            if ami:
                try:
                    ec2_service.deregister_image(ami)
                except Exception:  # noqa: BLE001
                    pass
        try:
            update_exercise_status(exercise_id, "failed", detail=_error_text(e))
        except Exception:  # noqa: BLE001
            pass