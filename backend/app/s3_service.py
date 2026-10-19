"""
s3_service.py
-------------
เก็บ/ดึง/ลบ Snapshot ของแบบฝึกหัดใน S3 bucket ส่วนตัว
- แบบใหม่: ต้นแบบ VM (AMI ที่ EC2 สำรองลง S3 ด้วย CreateStoreImageTask)
- แบบเก่า: ไฟล์ .gns3project เดี่ยว (ยังรองรับ)
- backend อัปโหลดไฟล์ที่ export จาก GNS3 ของอาจารย์
- VM นักศึกษาดาวน์โหลดผ่าน presigned URL อายุสั้น (ไม่ต้องให้สิทธิ์ S3 กับ VM)
"""

from typing import BinaryIO, Optional

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError
from fastapi import HTTPException

from app.config import get_settings


def get_s3_client():
    settings = get_settings()
    kwargs = dict(
        region_name=settings.aws_region,
        config=Config(signature_version="s3v4"),
    )
    # ถ้าไม่ได้ใส่ key ใน .env boto3 จะใช้ Instance Profile ของ EC2 เอง
    if settings.aws_access_key_id and settings.aws_secret_access_key:
        kwargs["aws_access_key_id"] = settings.aws_access_key_id
        kwargs["aws_secret_access_key"] = settings.aws_secret_access_key
        if settings.aws_session_token:
            kwargs["aws_session_token"] = settings.aws_session_token
    return boto3.client("s3", **kwargs)


def _bucket() -> str:
    bucket = get_settings().snapshots_bucket
    if not bucket:
        raise HTTPException(status_code=500, detail="ยังไม่ได้ตั้งค่า SNAPSHOTS_BUCKET ใน .env")
    return bucket


def build_exercise_key(exercise_id: str, project_id: Optional[str] = None) -> str:
    """key ของไฟล์ .gns3project (หนึ่งไฟล์ต่อหนึ่งโปรเจ็ค ถ้าระบุ project_id)"""
    prefix = get_settings().snapshots_prefix.strip("/")
    name = f"{exercise_id}/{project_id}.gns3project" if project_id else f"{exercise_id}.gns3project"
    return f"{prefix}/{name}" if prefix else name


def build_templates_key(exercise_id: str) -> str:
    """key ของไฟล์ templates.json (GNS3 template ที่ใช้กับแบบฝึกหัดนี้)"""
    prefix = get_settings().snapshots_prefix.strip("/")
    name = f"{exercise_id}/templates.json"
    return f"{prefix}/{name}" if prefix else name


def build_image_key(kind: str, filename: str) -> str:
    """key ของ image ใน library กลาง (kind = IOS | IOU | QEMU) ใช้ร่วมกันหลาย exercise"""
    prefix = get_settings().snapshots_prefix.strip("/")
    name = f"_images/{kind}/{filename}"
    return f"{prefix}/{name}" if prefix else name


def object_exists(key: str) -> bool:
    """เช็คว่ามีไฟล์นี้ใน S3 จริงไหม"""
    try:
        get_s3_client().head_object(Bucket=_bucket(), Key=key)
        return True
    except (ClientError, HTTPException):
        return False


def upload_fileobj(fileobj: BinaryIO, key: str) -> None:
    get_s3_client().upload_fileobj(
        fileobj, _bucket(), key, ExtraArgs={"ContentType": "application/zip"}
    )


def upload_file(path: str, key: str) -> None:
    """อัปโหลดไฟล์จากดิสก์ (multipart อัตโนมัติ เหมาะกับไฟล์ใหญ่)"""
    get_s3_client().upload_file(
        path, _bucket(), key, ExtraArgs={"ContentType": "application/zip"}
    )


def put_bytes(data: bytes, key: str, content_type: str = "application/json") -> None:
    get_s3_client().put_object(Bucket=_bucket(), Key=key, Body=data, ContentType=content_type)


def presign_get(key: str, expires: Optional[int] = None) -> str:
    settings = get_settings()
    return get_s3_client().generate_presigned_url(
        "get_object",
        Params={"Bucket": _bucket(), "Key": key},
        ExpiresIn=expires or settings.snapshot_url_expires,
    )


def presign_put(key: str, expires: Optional[int] = None) -> str:
    """presigned URL สำหรับ PUT (ให้ VM อาจารย์อัปโหลดด้วย curl โดยไม่ต้องมีสิทธิ์ S3)"""
    settings = get_settings()
    return get_s3_client().generate_presigned_url(
        "put_object",
        Params={"Bucket": _bucket(), "Key": key},
        ExpiresIn=expires or settings.snapshot_url_expires,
    )


def delete_object(key: str) -> None:
    """ลบไฟล์ snapshot (best-effort: ไม่ให้การลบ exercise ล้มเพราะ S3)"""
    try:
        get_s3_client().delete_object(Bucket=_bucket(), Key=key)
    except (ClientError, HTTPException):
        pass