"""
gns3_service.py
---------------
คุยกับ GNS3 REST API (port 3080) บน VM ของอาจารย์ เพื่อ Export โปรเจ็คขึ้น S3
- 1 แบบฝึกหัด = 1 ไฟล์ bundle (.zip) บน S3 ที่มัดรวมหลาย .gns3project ไว้ข้างใน
- ใช้รหัสผ่าน GNS3 ของ VM ที่เก็บไว้ใน DynamoDB (ตั้งตอน launch)
- ลอง private IP ก่อน (backend อยู่ VPC เดียวกัน) แล้วค่อย public IP
- ไฟล์ export ถูกเขียนลง temp file บนดิสก์ก่อน แล้วอัปโหลดขึ้น S3 (ไม่กิน RAM)
"""

import tempfile
import zipfile
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


def select_projects(
    projects: list[dict],
    project_ids: Optional[list[str]] = None,
    export_all: bool = False,
) -> list[dict]:
    """เลือกโปรเจ็คที่จะ export: ทุกโปรเจ็ค (export_all) หรือเฉพาะ project_ids ที่ระบุ"""
    if not projects:
        raise HTTPException(status_code=400, detail="ไม่พบโปรเจ็คใน GNS3 บน VM นี้ ให้สร้างโปรเจ็คก่อน")
    if export_all:
        return projects
    if not project_ids:
        raise HTTPException(
            status_code=400,
            detail="กรุณาระบุ project_ids หรือตั้ง export_all=true",
        )
    by_id = {p["project_id"]: p for p in projects}
    # ตัดค่าซ้ำแต่คงลำดับที่ผู้ใช้ส่งมา
    wanted = list(dict.fromkeys(project_ids))
    missing = [pid for pid in wanted if pid not in by_id]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"ไม่พบโปรเจ็คเหล่านี้บน VM: {', '.join(missing)}",
        )
    return [by_id[pid] for pid in wanted]


def _error_text(e: Exception) -> str:
    return str(getattr(e, "detail", None) or e)[:500]


def _bundle_member_name(index: int, project_name: Optional[str]) -> str:
    """ชื่อไฟล์ใน bundle: ใช้ ASCII ล้วนกันปัญหา encoding (ชื่อโปรเจ็คจริงอยู่ในไฟล์ .gns3project เอง)"""
    safe = "".join(
        c if (c.isascii() and (c.isalnum() or c in "-_")) else "_" for c in (project_name or "")
    ).strip("_")[:40]
    return f"{index:02d}-{safe or 'project'}.gns3project"


def _export_project_into_zip(
    base: str,
    auth: httpx.BasicAuth,
    project: dict,
    zf: zipfile.ZipFile,
    member_name: str,
    timeout: httpx.Timeout,
) -> None:
    """export 1 โปรเจ็คจาก GNS3 แล้วสตรีมเขียนเป็นไฟล์ .gns3project ใน zip (ไม่กิน RAM)"""
    pid = project["project_id"]
    label = project.get("name") or pid

    # โปรเจ็คที่ปิดอยู่ต้องเปิดก่อนถึงจะ export ได้ (เปิดซ้ำที่เปิดอยู่แล้วไม่เป็นไร)
    try:
        httpx.post(f"{base}/projects/{pid}/open", auth=auth, timeout=120.0)
    except httpx.HTTPError:
        pass

    params = {
        "include_snapshots": "false",
        "include_images": "false",
        "reset_mac_addresses": "true",
        "compression": "zip",
    }
    written = 0
    with httpx.stream(
        "GET", f"{base}/projects/{pid}/export", params=params, auth=auth, timeout=timeout
    ) as resp:
        if resp.status_code == 409:
            raise RuntimeError(
                f"โปรเจ็ค '{label}': GNS3 ไม่ยอม export โปรเจ็คที่กำลังรัน ให้ stop node ทั้งหมดก่อนแล้วลองใหม่"
            )
        if resp.status_code != 200:
            body = resp.read().decode("utf-8", errors="ignore")[:300]
            raise RuntimeError(f"โปรเจ็ค '{label}': export ล้มเหลว (HTTP {resp.status_code}): {body}")
        # .gns3project เป็น zip อยู่แล้ว จึงเก็บแบบ STORED (ไม่บีบซ้ำ)
        with zf.open(member_name, "w", force_zip64=True) as dest:
            for chunk in resp.iter_bytes(1024 * 1024):
                dest.write(chunk)
                written += len(chunk)
    if written == 0:
        raise RuntimeError(f"โปรเจ็ค '{label}': ไฟล์ที่ export ว่างเปล่า")


def export_exercise_to_s3(
    exercise_id: str, instance_rec: dict, projects: list[dict], s3_key: str
) -> None:
    """
    รันเบื้องหลัง: export ทุกโปรเจ็คที่เลือก -> bundle .zip (temp file) -> S3 แล้วอัปเดตสถานะแบบฝึกหัด
    all-or-nothing: ถ้าโปรเจ็คใดล้มเหลว จะไม่อัปโหลดอะไรและตั้ง status = failed (ดู status_detail)
    """
    settings = get_settings()
    try:
        base, auth = _find_base(instance_rec)
        timeout = httpx.Timeout(30.0, read=float(settings.gns3_export_timeout))

        with tempfile.TemporaryFile() as bundle:
            with zipfile.ZipFile(
                bundle, "w", compression=zipfile.ZIP_STORED, allowZip64=True
            ) as zf:
                for idx, project in enumerate(projects, start=1):
                    member = _bundle_member_name(idx, project.get("name"))
                    _export_project_into_zip(base, auth, project, zf, member, timeout)

            if bundle.tell() == 0:
                raise RuntimeError("ไฟล์ bundle ว่างเปล่า")
            bundle.seek(0)
            s3_service.upload_fileobj(bundle, s3_key)

        update_exercise_status(exercise_id, "available")
    except Exception as e:  # noqa: BLE001 - ต้องจับทุกอย่างเพื่อไม่ให้ค้าง pending
        try:
            update_exercise_status(exercise_id, "failed", detail=_error_text(e))
        except Exception:  # noqa: BLE001
            pass