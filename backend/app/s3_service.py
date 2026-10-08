"""
s3_service.py
-------------
เก็บ/ดึง/ลบ Snapshot ของแบบฝึกหัด (ไฟล์ .gns3project) ใน S3 bucket ส่วนตัว
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


def build_exercise_key(exercise_id: str) -> str:
    prefix = get_settings().snapshots_prefix.strip("/")
    return f"{prefix}/{exercise_id}.gns3project" if prefix else f"{exercise_id}.gns3project"


def upload_fileobj(fileobj: BinaryIO, key: str) -> None:
    get_s3_client().upload_fileobj(
        fileobj, _bucket(), key, ExtraArgs={"ContentType": "application/zip"}
    )


def presign_get(key: str, expires: Optional[int] = None) -> str:
    settings = get_settings()
    return get_s3_client().generate_presigned_url(
        "get_object",
        Params={"Bucket": _bucket(), "Key": key},
        ExpiresIn=expires or settings.snapshot_url_expires,
    )


def delete_object(key: str) -> None:
    """ลบไฟล์ snapshot (best-effort: ไม่ให้การลบ exercise ล้มเพราะ S3)"""
    try:
        get_s3_client().delete_object(Bucket=_bucket(), Key=key)
    except (ClientError, HTTPException):
        pass