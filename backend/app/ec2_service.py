"""
ec2_service.py
---------------
รวม logic การคุย AWS EC2 ทั้งหมดไว้ที่นี่ที่เดียว (แยกออกจาก main.py / routes)
ทุก instance ที่สร้างผ่านระบบนี้จะถูกติด Tag ไว้เสมอ:
  - Project = gns3-cloud       -> ใช้ filter ว่า instance ไหนเป็นของระบบเรา
  - Name    = <instance_name>  -> ชื่อที่นักศึกษาตั้ง
  - StudentId = <student_id>   -> ใครเป็นเจ้าของ

การ filter ด้วย Tag:Project ป้องกันไม่ให้ API ของเราไป list/stop/terminate
EC2 instance ตัวอื่นที่ไม่เกี่ยวกับโปรเจคนี้ในบัญชี AWS เดียวกันโดยไม่ตั้งใจ
"""

from datetime import datetime
from typing import Optional

import boto3
from botocore.exceptions import ClientError
from fastapi import HTTPException

from app.config import get_settings
from app.models import InstanceInfo

PROJECT_TAG_VALUE = "gns3-cloud"


def get_ec2_client():
    settings = get_settings()

    client_kwargs = dict(
        region_name=settings.aws_region,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
    )

    # >>> LEARNER LAB ONLY <<<
    # credentials ของ Learner Lab เป็นแบบชั่วคราว (STS) ต้องแนบ session token
    # เข้าไปด้วยไม่งั้น boto3 จะ auth ไม่ผ่าน (error: InvalidClientTokenId)
    # ถ้าใช้ AWS account จริงกับ IAM user ปกติ aws_session_token จะเป็น None
    # และโค้ดส่วนนี้จะไม่ทำอะไร -> ไม่ต้องแก้อะไรตอนย้ายไป account จริง
    if settings.aws_session_token:
        client_kwargs["aws_session_token"] = settings.aws_session_token

    return boto3.client("ec2", **client_kwargs)


def _get_tag(tags: Optional[list[dict]], key: str) -> Optional[str]:
    if not tags:
        return None
    for tag in tags:
        if tag.get("Key") == key:
            return tag.get("Value")
    return None


def _instance_to_info(instance: dict) -> InstanceInfo:
    tags = instance.get("Tags", [])
    return InstanceInfo(
        instance_id=instance["InstanceId"],
        name=_get_tag(tags, "Name"),
        state=instance["State"]["Name"],
        instance_type=instance["InstanceType"],
        public_ip=instance.get("PublicIpAddress"),
        private_ip=instance.get("PrivateIpAddress"),
        launch_time=instance["LaunchTime"].isoformat()
        if instance.get("LaunchTime")
        else None,
        student_id=_get_tag(tags, "StudentId"),
    )


def _count_active_project_instances(client) -> int:
    """นับ instance ของโปรเจคที่ยังไม่ terminated/terminating เพื่อกัน quota บาน"""
    resp = client.describe_instances(
        Filters=[
            {"Name": "tag:Project", "Values": [PROJECT_TAG_VALUE]},
            {
                "Name": "instance-state-name",
                "Values": ["pending", "running", "stopping", "stopped"],
            },
        ]
    )
    return sum(len(r["Instances"]) for r in resp["Reservations"])


def launch_instance(
    student_id: str,
    instance_name: str,
    instance_type: Optional[str] = None,
    ami_id: Optional[str] = None,
) -> InstanceInfo:
    settings = get_settings()
    client = get_ec2_client()

    if _count_active_project_instances(client) >= settings.max_concurrent_instances:
        raise HTTPException(
            status_code=429,
            detail=(
                f"ถึงจำนวน instance สูงสุดที่อนุญาต "
                f"({settings.max_concurrent_instances}) แล้ว "
                "กรุณา terminate instance เก่าก่อนสร้างใหม่"
            ),
        )

    run_instances_kwargs = dict(
        ImageId=ami_id or settings.default_ami_id,
        InstanceType=instance_type or settings.default_instance_type,
        KeyName=settings.default_key_name,
        SecurityGroupIds=[settings.default_security_group_id],
        MinCount=1,
        MaxCount=1,
    )

    # >>> LEARNER LAB ONLY <<<
    # แนบ instance profile "LabRole" ที่ Lab เตรียมไว้ให้ (จำเป็นถ้า GNS3 VM ต้อง
    # เรียก AWS service อื่น เช่น อ่าน/เขียน S3) Learner Lab ไม่ให้สร้าง Role เอง
    # ถ้าใช้ AWS account จริง ให้เปลี่ยน instance_profile_name ใน config.py เป็น
    # role ที่สร้างเองตาม least-privilege หรือปล่อย None ถ้าไม่ต้องใช้เลย
    if settings.instance_profile_name:
        run_instances_kwargs["IamInstanceProfile"] = {
            "Name": settings.instance_profile_name
        }

    try:
        resp = client.run_instances(
            **run_instances_kwargs,
            TagSpecifications=[
                {
                    "ResourceType": "instance",
                    "Tags": [
                        {"Key": "Name", "Value": instance_name},
                        {"Key": "Project", "Value": PROJECT_TAG_VALUE},
                        {"Key": "StudentId", "Value": student_id},
                        {"Key": "CreatedAt", "Value": datetime.utcnow().isoformat()},
                    ],
                }
            ],
        )
    except ClientError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    instance = resp["Instances"][0]
    return InstanceInfo(
        instance_id=instance["InstanceId"],
        name=instance_name,
        state=instance["State"]["Name"],
        instance_type=instance["InstanceType"],
        public_ip=instance.get("PublicIpAddress"),
        private_ip=instance.get("PrivateIpAddress"),
        launch_time=None,
        student_id=student_id,
    )


def list_instances(student_id: Optional[str] = None) -> list[InstanceInfo]:
    client = get_ec2_client()

    filters = [{"Name": "tag:Project", "Values": [PROJECT_TAG_VALUE]}]
    if student_id:
        filters.append({"Name": "tag:StudentId", "Values": [student_id]})

    try:
        resp = client.describe_instances(Filters=filters)
    except ClientError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    instances: list[InstanceInfo] = []
    for reservation in resp["Reservations"]:
        for instance in reservation["Instances"]:
            instances.append(_instance_to_info(instance))
    return instances


def _ensure_owned_by_project(client, instance_id: str) -> None:
    """กันไม่ให้ยิง action ใส่ instance ที่ไม่ได้สร้างผ่านระบบนี้"""
    resp = client.describe_instances(InstanceIds=[instance_id])
    reservations = resp.get("Reservations", [])
    if not reservations or not reservations[0]["Instances"]:
        raise HTTPException(status_code=404, detail="ไม่พบ instance นี้")

    tags = reservations[0]["Instances"][0].get("Tags", [])
    if _get_tag(tags, "Project") != PROJECT_TAG_VALUE:
        raise HTTPException(
            status_code=403,
            detail="Instance นี้ไม่ได้ถูกสร้างผ่านระบบ GNS3-Cloud",
        )


def start_instance(instance_id: str) -> dict:
    client = get_ec2_client()
    _ensure_owned_by_project(client, instance_id)
    try:
        resp = client.start_instances(InstanceIds=[instance_id])
    except ClientError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    state = resp["StartingInstances"][0]["CurrentState"]["Name"]
    return {"instance_id": instance_id, "state": state, "message": "instance กำลังเริ่มทำงาน"}


def stop_instance(instance_id: str) -> dict:
    client = get_ec2_client()
    _ensure_owned_by_project(client, instance_id)
    try:
        resp = client.stop_instances(InstanceIds=[instance_id])
    except ClientError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    state = resp["StoppingInstances"][0]["CurrentState"]["Name"]
    return {"instance_id": instance_id, "state": state, "message": "instance กำลังปิดเครื่อง"}


def terminate_instance(instance_id: str) -> dict:
    client = get_ec2_client()
    _ensure_owned_by_project(client, instance_id)
    try:
        resp = client.terminate_instances(InstanceIds=[instance_id])
    except ClientError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    state = resp["TerminatingInstances"][0]["CurrentState"]["Name"]
    return {
        "instance_id": instance_id,
        "state": state,
        "message": "instance กำลังถูกลบ (terminate)",
    }
