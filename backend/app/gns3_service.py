"""
gns3_service.py
---------------
คุยกับ GNS3 REST API (port 3080) บน VM ของอาจารย์ เพื่อ Export โปรเจ็คขึ้น S3
- ใช้รหัสผ่าน GNS3 ของ VM ที่เก็บไว้ใน DynamoDB (ตั้งตอน launch)
- ลอง private IP ก่อน (backend อยู่ VPC เดียวกัน) แล้วค่อย public IP
- ไฟล์ export ถูกเขียนลง temp file บนดิสก์ก่อน แล้วอัปโหลดขึ้น S3 (ไม่กิน RAM)
"""

import tempfile
from typing import Optional

import httpx
from fastapi import HTTPException

from app import s3_service
from app.config import get_settings
from app.dynamodb_service import update_exercise_status


def _candidate_bases(instance_rec: dict) -> list[str]:
    settings = get_settings()
    ips = [instance_rec.get("private_ip"), instance_rec.get("public_ip")]
    if not settings.gns3_prefer_private_ip:
        ips.reverse()
    return [f"http://{ip}:{settings.gns3_api_port}/v2" for ip in ips if ip]


def _find_base(instance_rec: dict) -> tuple[str, httpx.BasicAuth]:
    user = instance_rec.get("gns3_user")
    password = instance_rec.get("gns3_password")
    if not user or not password:
        raise HTTPException(
            status_code=400,
            detail="VM นี้ไม่มีรหัสผ่าน GNS3 ในระบบ (ต้อง launch ด้วย GNS3_SET_VM_PASSWORD=true)",
        )
    auth = httpx.BasicAuth(user, password)

    for base in _candidate_bases(instance_rec):
        try:
            r = httpx.get(f"{base}/version", auth=auth, timeout=5.0)
        except httpx.HTTPError:
            continue
        if r.status_code == 401:
            raise HTTPException(status_code=502, detail="GNS3 บน VM ปฏิเสธรหัสผ่าน (401)")
        if r.status_code == 200:
            return base, auth

    raise HTTPException(
        status_code=502,
        detail="เชื่อมต่อ GNS3 server บน VM ไม่ได้ (VM ต้อง running และเปิด port 3080 ให้ backend เข้าถึง)",
    )


def list_projects(instance_rec: dict) -> list[dict]:
    base, auth = _find_base(instance_rec)
    try:
        r = httpx.get(f"{base}/projects", auth=auth, timeout=15.0)
        r.raise_for_status()
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"อ่านรายการโปรเจ็คจาก GNS3 ไม่ได้: {e}") from e
    return [
        {"project_id": p["project_id"], "name": p.get("name"), "status": p.get("status")}
        for p in r.json()
    ]


def pick_project(projects: list[dict], project_id: Optional[str]) -> dict:
    if project_id:
        for p in projects:
            if p["project_id"] == project_id:
                return p
        raise HTTPException(status_code=400, detail=f"ไม่พบโปรเจ็ค {project_id} บน VM นี้")
    if not projects:
        raise HTTPException(status_code=400, detail="ไม่พบโปรเจ็คใน GNS3 บน VM นี้ ให้สร้างโปรเจ็คก่อน")
    if len(projects) > 1:
        listing = ", ".join(f"{p['name']} ({p['project_id']})" for p in projects)
        raise HTTPException(
            status_code=400,
            detail=f"มีหลายโปรเจ็ค กรุณาระบุ project_id: {listing}",
        )
    return projects[0]


def _error_text(e: Exception) -> str:
    return str(getattr(e, "detail", None) or e)[:500]


def export_exercise_to_s3(
    exercise_id: str, instance_rec: dict, project_id: str, s3_key: str
) -> None:
    """รันเบื้องหลัง: export โปรเจ็คจาก GNS3 -> temp file -> S3 แล้วอัปเดตสถานะแบบฝึกหัด"""
    settings = get_settings()
    try:
        base, auth = _find_base(instance_rec)

        # โปรเจ็คที่ปิดอยู่ต้องเปิดก่อนถึงจะ export ได้ (เปิดซ้ำที่เปิดอยู่แล้วไม่เป็นไร)
        try:
            httpx.post(f"{base}/projects/{project_id}/open", auth=auth, timeout=120.0)
        except httpx.HTTPError:
            pass

        params = {
            "include_snapshots": "false",
            "include_images": "false",
            "reset_mac_addresses": "true",
            "compression": "zip",
        }
        timeout = httpx.Timeout(30.0, read=float(settings.gns3_export_timeout))

        with tempfile.TemporaryFile() as tmp:
            with httpx.stream(
                "GET",
                f"{base}/projects/{project_id}/export",
                params=params,
                auth=auth,
                timeout=timeout,
            ) as resp:
                if resp.status_code == 409:
                    raise RuntimeError(
                        "GNS3 ไม่ยอม export โปรเจ็คที่กำลังรัน: ให้ stop node ทั้งหมดก่อนแล้วลองใหม่"
                    )
                if resp.status_code != 200:
                    body = resp.read().decode("utf-8", errors="ignore")[:300]
                    raise RuntimeError(f"GNS3 export ล้มเหลว (HTTP {resp.status_code}): {body}")
                for chunk in resp.iter_bytes(1024 * 1024):
                    tmp.write(chunk)

            if tmp.tell() == 0:
                raise RuntimeError("ไฟล์ที่ export ว่างเปล่า")
            tmp.seek(0)
            s3_service.upload_fileobj(tmp, s3_key)

        update_exercise_status(exercise_id, "available")
    except Exception as e:  # noqa: BLE001 - ต้องจับทุกอย่างเพื่อไม่ให้ค้าง pending
        try:
            update_exercise_status(exercise_id, "failed", detail=_error_text(e))
        except Exception:  # noqa: BLE001
            pass