"""
gns3_service.py
---------------
คุยกับ GNS3 REST API (port 3080) บน VM เพื่อดู/เลือก/ลบโปรเจ็ค (ใช้สร้างต้นแบบ VM ของแบบฝึกหัด)
- ใช้รหัสผ่าน GNS3 ของ VM ที่เก็บไว้ใน DynamoDB (ตั้งตอน launch)
- ลอง private IP ก่อน (backend อยู่ VPC เดียวกัน) แล้วค่อย public IP
"""

import time
import zipfile
from typing import Optional

import httpx
from fastapi import HTTPException

from app.config import get_settings


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
    project_names: Optional[list[str]] = None,
) -> list[dict]:
    """
    เลือกโปรเจ็คที่จะอยู่ในต้นแบบ VM
    - ไม่ระบุทั้ง project_ids และ project_names = ทุกโปรเจ็ค (ค่าเริ่มต้น)
    - ระบุ = เฉพาะที่เลือก (ชื่อไม่แยกตัวพิมพ์เล็ก/ใหญ่; ถ้าชื่อซ้ำให้ใช้ project_id)
    """
    if not projects:
        raise HTTPException(status_code=400, detail="ไม่พบโปรเจ็คใน GNS3 บน VM นี้ ให้สร้างโปรเจ็คก่อน")
    if not project_ids and not project_names:
        return projects

    chosen: dict[str, dict] = {}
    by_id = {p["project_id"]: p for p in projects}

    missing_ids = [pid for pid in dict.fromkeys(project_ids or []) if pid not in by_id]
    if missing_ids:
        raise HTTPException(
            status_code=400, detail=f"ไม่พบโปรเจ็คเหล่านี้บน VM: {', '.join(missing_ids)}"
        )
    for pid in dict.fromkeys(project_ids or []):
        chosen[pid] = by_id[pid]

    for name in dict.fromkeys(project_names or []):
        matches = [p for p in projects if (p.get("name") or "").casefold() == name.strip().casefold()]
        if not matches:
            names = ", ".join(p.get("name") or p["project_id"] for p in projects)
            raise HTTPException(
                status_code=400, detail=f"ไม่พบโปรเจ็คชื่อ '{name}' บน VM นี้ (มี: {names})"
            )
        if len(matches) > 1:
            ids = ", ".join(m["project_id"] for m in matches)
            raise HTTPException(
                status_code=400,
                detail=f"มีโปรเจ็คชื่อ '{name}' ซ้ำกัน กรุณาระบุ project_id แทน: {ids}",
            )
        chosen[matches[0]["project_id"]] = matches[0]

    # คงลำดับเดียวกับที่ GNS3 ส่งมา
    return [p for p in projects if p["project_id"] in chosen]


def export_project_to_file(instance_rec: dict, project_id: str, dest_path: str) -> None:
    """
    export โปรเจ็คจาก GNS3 ของ VM อาจารย์ (GET /v2/projects/{id}/export) เขียนลงไฟล์ .gns3project (zip)
    - stream ลงดิสก์ ไม่โหลดทั้งไฟล์เข้า RAM
    - ถ้า GNS3 ปฏิเสธ (เช่น node ยังรันอยู่) จะ raise พร้อมข้อความจาก GNS3
    """
    settings = get_settings()
    base, auth = _find_base(instance_rec)
    params = {
        "include_snapshots": str(settings.gns3_export_include_snapshots).lower(),
        "include_images": str(settings.gns3_export_include_images).lower(),
        "reset_mac_addresses": "true",
        "compression": "zip",
    }
    timeout = httpx.Timeout(
        connect=10.0, read=float(settings.gns3_export_timeout), write=60.0, pool=10.0
    )
    try:
        with httpx.stream(
            "GET", f"{base}/projects/{project_id}/export", params=params, auth=auth, timeout=timeout
        ) as r:
            if r.status_code != 200:
                body = r.read().decode("utf-8", errors="replace")[:300]
                raise RuntimeError(f"GNS3 export ไม่สำเร็จ (HTTP {r.status_code}): {body}")
            with open(dest_path, "wb") as f:
                for chunk in r.iter_bytes(1024 * 1024):
                    f.write(chunk)
    except httpx.HTTPError as e:
        raise RuntimeError(f"รับไฟล์ export จาก GNS3 ไม่สำเร็จ: {e}") from e

    if not zipfile.is_zipfile(dest_path):
        raise RuntimeError("ไฟล์ที่ export จาก GNS3 ไม่ใช่ไฟล์ zip ที่สมบูรณ์")


def wait_until_ready(instance_rec: dict, timeout: int = 900, interval: int = 5) -> tuple[str, httpx.BasicAuth]:
    """
    รอ GNS3 บน VM ใหม่พร้อมใช้งาน (ตอบ /version = 200 ด้วยรหัสผ่านใหม่)
    หมายเหตุ: VM ที่ clone จาก AMI จะตอบ 401 ชั่วคราวจนกว่า UserData จะเปลี่ยนรหัสผ่านเสร็จ จึงรอต่อ
    """
    auth = httpx.BasicAuth(instance_rec["gns3_user"], instance_rec["gns3_password"])
    deadline = time.time() + timeout
    while time.time() < deadline:
        for base in _candidate_bases(instance_rec):
            try:
                r = httpx.get(f"{base}/version", auth=auth, timeout=5.0)
            except httpx.HTTPError:
                continue
            if r.status_code == 200:
                return base, auth
        time.sleep(interval)
    raise RuntimeError("GNS3 บน VM ชั่วคราวไม่พร้อมภายในเวลาที่กำหนด")


def keep_only_projects(base: str, auth: httpx.BasicAuth, keep_ids: list[str]) -> list[str]:
    """ลบโปรเจ็คที่ไม่ได้เลือกออกจาก VM (ใช้กับ VM ชั่วคราวที่ clone มา เท่านั้น!) คืนรายชื่อ id ที่เหลือ"""
    r = httpx.get(f"{base}/projects", auth=auth, timeout=30.0)
    r.raise_for_status()
    existing = {p["project_id"]: p for p in r.json()}
    missing = [pid for pid in keep_ids if pid not in existing]
    if missing:
        raise RuntimeError(f"ไม่พบโปรเจ็คใน VM ที่ clone มา: {', '.join(missing)}")

    for pid, p in existing.items():
        if pid in keep_ids:
            continue
        d = httpx.delete(f"{base}/projects/{pid}", auth=auth, timeout=300.0)
        if d.status_code not in (200, 204):
            raise RuntimeError(
                f"ลบโปรเจ็ค '{p.get('name') or pid}' ออกจาก VM ชั่วคราวไม่สำเร็จ (HTTP {d.status_code})"
            )

    r = httpx.get(f"{base}/projects", auth=auth, timeout=30.0)
    r.raise_for_status()
    return [p["project_id"] for p in r.json()]