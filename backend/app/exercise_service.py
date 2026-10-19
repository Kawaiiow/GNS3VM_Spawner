"""
exercise_service.py
-------------------
สร้าง "ต้นแบบ VM" ของแบบฝึกหัด แล้วสำรองลง S3 (รันเบื้องหลังจาก POST /exercises)

ขั้นตอน (status = pending -> available | failed, ความคืบหน้าอยู่ใน status_detail):
  1) snapshot VM ของอาจารย์เป็น AMI (มีทุกโปรเจ็คครบ รวมดิสก์/อิมเมจของ node)
  2) ถ้าเลือกเฉพาะบางโปรเจ็ค: เปิด VM ชั่วคราวจาก AMI นั้น -> ลบโปรเจ็คที่ไม่เลือกออก -> snapshot เป็น AMI ใหม่
     (ถ้าเลือกทุกโปรเจ็ค/ไม่ระบุ ข้ามขั้นนี้ ใช้ AMI จากข้อ 1 เลย)
  3) สำรอง AMI ลง S3 (EC2 CreateStoreImageTask) -> ได้ s3_key (ไม่บังคับ: ข้าม/ล้มเหลวได้ AMI ยังใช้งานได้)
  4) บันทึก ami_id (+ s3_key ถ้ามี) ลง DynamoDB แล้ว status = available
ตอนสร้าง VM นักศึกษา: ใช้ AMI นี้ได้ทันที ถ้า AMI หายไปจะกู้คืนจาก S3 ให้อัตโนมัติ (ดู ec2_service._ensure_template_ready)
"""

import json
import os
import tempfile
from typing import Optional

from app import ec2_service, gns3_service, image_service, s3_service
from app.config import get_settings
from app.dynamodb_service import update_exercise_fields, update_exercise_status


def _error_text(e: Exception) -> str:
    return str(getattr(e, "detail", None) or e)[:500]


def _progress(exercise_id: str, text: str) -> None:
    try:
        update_exercise_status(exercise_id, "pending", detail=text)
    except Exception:  # noqa: BLE001 - อัปเดตความคืบหน้าพลาดไม่ควรทำให้งานล้ม
        pass


def build_exercise_export(
    exercise_id: str,
    instance_rec: dict,
    selected_projects: list[dict],
) -> None:
    """
    ทำต้นแบบแบบ "ไฟล์โปรเจ็ค" (รันเบื้องหลังจาก POST /exercises เมื่อ EXERCISE_TEMPLATE_MODE=gns3project)
      ต่อโปรเจ็ค: export จาก GNS3 ของอาจารย์ -> .gns3project -> อัปโหลดขึ้น S3
      สำเร็จครบทุกโปรเจ็ค -> บันทึก s3_keys (เรียงตามโปรเจ็ค) แล้ว status = available
      ล้มเหลวที่โปรเจ็คใด -> ลบไฟล์ที่อัปโหลดไปแล้ว แล้ว status = failed (ดูสาเหตุที่ status_detail)
      image (IOS/IOU/QEMU) ถูกแยกไปเก็บใน S3 library กลาง (ไม่ลบตอนล้มเหลว เพราะ exercise อื่นใช้ร่วมได้)
    VM นักศึกษาเปิดจาก Base AMI แล้ว import ไฟล์เหล่านี้ตอน first boot (ดู ec2_service.launch_instance)
    """
    uploaded: list[str] = []
    stored_images: list[dict] = []
    templates_key: Optional[str] = None
    template_names: list[str] = []
    note: Optional[str] = None
    total = len(selected_projects)
    try:
        # 0) สำรอง image (IOS/IOU/QEMU) ของ node ที่โปรเจ็คใช้ขึ้น S3 library กลาง
        #    ทำก่อน export เพื่อให้ล้มเหลวเร็ว (เช่น SSM ใช้ไม่ได้ / หา image ไม่เจอ)
        if get_settings().gns3_images_separate:
            _progress(exercise_id, "กำลังตรวจสอบ image (IOS/IOU/QEMU) ที่โปรเจ็คใช้")
            wanted: dict[tuple[str, str], dict] = {}
            for p in selected_projects:
                for img in gns3_service.collect_project_images(instance_rec, p["project_id"]):
                    wanted[(img["kind"], img["filename"])] = img
            if wanted:
                _progress(
                    exercise_id,
                    f"กำลังสำรอง image {len(wanted)} ไฟล์ขึ้น S3 (อาจใช้เวลาหลายนาที)",
                )
                stored_images = image_service.sync_images_to_s3(instance_rec, list(wanted.values()))

        # 0.5) GNS3 template (เช่น QEMU VM template) -> templates.json บน S3 (best-effort)
        #      VM นักศึกษาจะสร้าง template เหล่านี้คืนให้ตอน first boot
        try:
            tpls = gns3_service.collect_templates(
                instance_rec, [p["project_id"] for p in selected_projects], stored_images
            )
            if tpls:
                _progress(exercise_id, f"กำลังสำรอง template {len(tpls)} รายการขึ้น S3")
                templates_key = s3_service.build_templates_key(exercise_id)
                s3_service.put_bytes(json.dumps(tpls, ensure_ascii=False).encode("utf-8"), templates_key)
                template_names = [x.get("name") or x.get("template_id") for x in tpls]
        except Exception as e:  # noqa: BLE001
            templates_key, template_names = None, []
            note = f"สำรอง template ไม่สำเร็จ (โปรเจ็คและ image ยังใช้ได้): {_error_text(e)}"

        with tempfile.TemporaryDirectory(prefix="netlab-export-") as tmp:
            for idx, p in enumerate(selected_projects, start=1):
                pid = p["project_id"]
                pname = p.get("name") or pid
                path = os.path.join(tmp, f"{pid}.gns3project")

                _progress(exercise_id, f"{idx}/{total} กำลัง export โปรเจ็ค '{pname}' จาก GNS3")
                gns3_service.export_project_to_file(instance_rec, pid, path)

                _progress(exercise_id, f"{idx}/{total} กำลังอัปโหลด '{pname}' ขึ้น S3")
                key = s3_service.build_exercise_key(exercise_id, pid)
                s3_service.upload_file(path, key)
                uploaded.append(key)
                os.remove(path)  # ล้างดิสก์ของ backend ทีละไฟล์

        fields: dict = {"s3_keys": uploaded, "s3_key": uploaded[0]}
        if stored_images:
            fields["images"] = stored_images  # [{"kind","filename","s3_key"}] ให้ VM ใหม่โหลดก่อน import
        if templates_key:
            fields["templates_key"] = templates_key
            fields["template_names"] = template_names
        update_exercise_fields(exercise_id, fields)
        update_exercise_status(exercise_id, "available", detail=note)
    except Exception as e:  # noqa: BLE001 - ต้องจับทุกอย่างเพื่อไม่ให้ค้าง pending
        for key in uploaded:
            s3_service.delete_object(key)
        if templates_key:
            s3_service.delete_object(templates_key)
        try:
            update_exercise_status(exercise_id, "failed", detail=_error_text(e))
        except Exception:  # noqa: BLE001
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

        # 3) สำรองลง S3 (best-effort): AMI พร้อมใช้แล้ว ถ้าสำรองลง S3 ไม่ได้ก็ยังต้องใช้สร้าง VM ได้
        #    (ผลเสียคือ ถ้า AMI ถูกลบภายหลังจะกู้คืนจาก S3 ไม่ได้)
        s3_key: Optional[str] = None
        note: Optional[str] = None
        if get_settings().snapshots_bucket:
            _progress(exercise_id, "3/3 กำลังสำรองต้นแบบ VM ลง S3 (อาจใช้เวลาหลายนาที)")
            try:
                s3_key = ec2_service.store_image_to_s3(final_ami)
            except Exception as e:  # noqa: BLE001
                note = f"ต้นแบบพร้อมใช้ แต่สำรองลง S3 ไม่สำเร็จ: {_error_text(e)}"
        else:
            note = "ต้นแบบพร้อมใช้ (ไม่ได้ตั้ง SNAPSHOTS_BUCKET จึงไม่ได้สำรองลง S3)"

        fields = {"ami_id": final_ami}
        if s3_key:
            fields["s3_key"] = s3_key
        update_exercise_fields(exercise_id, fields)
        stored = True  # AMI ถูกผูกกับ exercise แล้ว ห้ามลบทิ้งในส่วน cleanup
        update_exercise_status(exercise_id, "available", detail=note)
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