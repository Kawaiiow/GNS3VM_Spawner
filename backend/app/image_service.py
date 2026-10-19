"""
image_service.py
----------------
สำรอง image (IOS/IOU/QEMU) จาก VM อาจารย์ขึ้น S3 library กลาง
- สั่งผ่าน SSM Run Command ให้ VM อัปโหลดเองด้วย curl + presigned PUT URL (VM ไม่ต้องมีสิทธิ์ S3)
- ข้ามไฟล์ที่มีใน S3 แล้ว (ถ้า SSM ใช้ไม่ได้ อัปโหลดมือไปที่ key เดียวกันได้ เช่น
  s3://<bucket>/exercises/_images/IOS/<ชื่อไฟล์> ระบบจะเห็นว่ามีแล้วและข้ามไป)
- ต้องการ: SSM Agent บน VM อาจารย์ + instance profile ที่มีสิทธิ์ SSM,
  และ credentials ของ backend ที่เรียก ssm:SendCommand / ssm:GetCommandInvocation ได้
"""

import shlex
import time

import boto3
from botocore.exceptions import ClientError

from app import s3_service
from app.config import get_settings


def _ssm_client():
    settings = get_settings()
    kwargs = dict(region_name=settings.aws_region)
    # ถ้าไม่ได้ใส่ key ใน .env boto3 จะใช้ Instance Profile ของเครื่อง backend เอง
    if settings.aws_access_key_id and settings.aws_secret_access_key:
        kwargs["aws_access_key_id"] = settings.aws_access_key_id
        kwargs["aws_secret_access_key"] = settings.aws_secret_access_key
        if settings.aws_session_token:
            kwargs["aws_session_token"] = settings.aws_session_token
    return boto3.client("ssm", **kwargs)


def sync_images_to_s3(instance_rec: dict, images: list[dict]) -> list[dict]:
    """
    คืน [{"kind","filename","s3_key"}] ของ image ทั้งหมดที่อยู่ใน S3 แล้ว
    raise RuntimeError ถ้าอัปโหลดไม่สำเร็จ (หาไฟล์ไม่เจอบน VM / SSM ใช้ไม่ได้ / หมดเวลา)
    """
    settings = get_settings()
    entries: list[dict] = []
    todo: list[dict] = []
    for img in images:
        key = s3_service.build_image_key(img["kind"], img["filename"])
        entry = {**img, "s3_key": key}
        entries.append(entry)
        if not s3_service.object_exists(key):
            todo.append(entry)
    if not todo:
        return entries

    lines = ["#!/bin/bash"]
    for e in todo:
        fn = e["filename"]  # ผ่านการตรวจชื่อ (A-Za-z0-9._-) มาแล้วใน gns3_service.collect_project_images
        url = s3_service.presign_put(e["s3_key"], expires=settings.ssm_command_timeout)
        lines += [
            f"f=$(find {shlex.quote(settings.gns3_images_dir)} -type f -name {shlex.quote(fn)} 2>/dev/null | head -n1)",
            f'if [ -z "$f" ]; then echo "NOT FOUND: {fn}"; else',
            f'  curl -fsS -X PUT --upload-file "$f" "{url}" && echo "UPLOADED: {fn}" || echo "UPLOAD FAILED: {fn}"',
            "fi",
        ]

    ssm = _ssm_client()
    iid = instance_rec["instance_id"]
    try:
        resp = ssm.send_command(
            InstanceIds=[iid],
            DocumentName="AWS-RunShellScript",
            Parameters={
                "commands": lines,
                "executionTimeout": [str(settings.ssm_command_timeout)],
            },
        )
    except ClientError as e:
        raise RuntimeError(
            "สั่ง SSM ไปที่ VM อาจารย์ไม่ได้ (ต้องมี SSM Agent + instance profile ที่มีสิทธิ์ SSM "
            f"และ backend ต้องมีสิทธิ์ ssm:SendCommand): {e.response['Error']['Message']}"
        ) from e

    cmd_id = resp["Command"]["CommandId"]
    deadline = time.time() + settings.ssm_command_timeout
    inv: dict = {}
    while time.time() < deadline:
        time.sleep(5)
        try:
            inv = ssm.get_command_invocation(CommandId=cmd_id, InstanceId=iid)
        except ClientError as e:
            if e.response["Error"]["Code"] == "InvocationDoesNotExist":
                continue  # ยังลงทะเบียนคำสั่งไม่เสร็จ
            raise
        if inv.get("Status") in ("Success", "Failed", "Cancelled", "TimedOut"):
            break
    else:
        raise RuntimeError("รออัปโหลด image จาก VM อาจารย์ไม่ทันเวลาที่กำหนด")

    missing = [e["filename"] for e in todo if not s3_service.object_exists(e["s3_key"])]
    if missing:
        tail = (inv.get("StandardOutputContent") or "")[-300:]
        raise RuntimeError(f"อัปโหลด image ขึ้น S3 ไม่สำเร็จ: {', '.join(missing)} | {tail}")
    return entries
