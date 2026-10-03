"""
ec2_service.py
---------------
รวม logic การคุย AWS EC2 และการ sync สถานะกับ DynamoDB:
- ทุก instance ที่สร้างผ่านระบบนี้จะถูกติด Tag:
  - Project   = gns3-cloud
  - Name      = <instance_name>
  - UserId    = <user_id>
  - ExerciseId = <exercise_id> (ถ้ามี)
- จัดการ 1-VM per user constraint ร่วมกับ dynamodb_service
"""

from datetime import datetime, timezone
from typing import Optional

import boto3
from botocore.exceptions import ClientError
from fastapi import HTTPException

from app.config import get_settings
from app.dynamodb_service import (
    assign_user_vm,
    create_instance_record,
    get_exercise_record,
    get_instance_record,
    list_all_instances as db_list_all_instances,
    list_instances_by_user as db_list_instances_by_user,
    mark_instance_terminated,
    release_user_vm,
    reserve_user_vm_slot,
    update_instance_state,
)
from app.models import InstanceInfo

PROJECT_TAG_VALUE = "gns3-cloud"


def get_ec2_client():
    settings = get_settings()

    client_kwargs = dict(
        region_name=settings.aws_region,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
    )

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
    launch_time_str = (
        instance["LaunchTime"].isoformat() if instance.get("LaunchTime") else None
    )
    return InstanceInfo(
        instance_id=instance["InstanceId"],
        name=_get_tag(tags, "Name"),
        state=instance["State"]["Name"],
        instance_type=instance["InstanceType"],
        public_ip=instance.get("PublicIpAddress"),
        private_ip=instance.get("PrivateIpAddress"),
        launch_time=launch_time_str,
        user_id=_get_tag(tags, "UserId"),
        exercise_id=_get_tag(tags, "ExerciseId"),
        created_at=launch_time_str,
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
    user_id: str,
    instance_name: str,
    instance_type: Optional[str] = None,
    ami_id: Optional[str] = None,
    exercise_id: Optional[str] = None,
) -> InstanceInfo:
    settings = get_settings()
    client = get_ec2_client()

    # ตรวจสอบ exercise_id (ถ้ามีส่งมา)
    resolved_ami = ami_id
    if exercise_id:
        exercise = get_exercise_record(exercise_id)
        if not exercise or not exercise.get("is_active"):
            raise HTTPException(
                status_code=400,
                detail=f"Exercise '{exercise_id}' not found or inactive.",
            )
        if not resolved_ami:
            resolved_ami = exercise.get("ami_id")

    # 1. Atomic reservation in DynamoDB: checks if user already has an active VM
    reserve_user_vm_slot(user_id)

    # 2. Check project concurrent instance limits
    try:
        if _count_active_project_instances(client) >= settings.max_concurrent_instances:
            release_user_vm(user_id)
            raise HTTPException(
                status_code=429,
                detail=(
                    f"ถึงจำนวน instance สูงสุดที่อนุญาต "
                    f"({settings.max_concurrent_instances}) แล้ว "
                    "กรุณา terminate instance เก่าก่อนสร้างใหม่"
                ),
            )
    except Exception as e:
        if not isinstance(e, HTTPException):
            release_user_vm(user_id)
        raise e

    target_ami = resolved_ami or settings.default_ami_id
    target_type = instance_type or settings.default_instance_type

    run_instances_kwargs = dict(
        ImageId=target_ami,
        InstanceType=target_type,
        KeyName=settings.default_key_name,
        SecurityGroupIds=[settings.default_security_group_id],
        MinCount=1,
        MaxCount=1,
    )

    if settings.instance_profile_name:
        run_instances_kwargs["IamInstanceProfile"] = {
            "Name": settings.instance_profile_name
        }

    now_iso = datetime.now(timezone.utc).isoformat()

    tags = [
        {"Key": "Name", "Value": instance_name},
        {"Key": "Project", "Value": PROJECT_TAG_VALUE},
        {"Key": "UserId", "Value": user_id},
        {"Key": "CreatedAt", "Value": now_iso},
    ]
    if exercise_id:
        tags.append({"Key": "ExerciseId", "Value": exercise_id})

    try:
        resp = client.run_instances(
            **run_instances_kwargs,
            TagSpecifications=[
                {
                    "ResourceType": "instance",
                    "Tags": tags,
                }
            ],
        )
    except ClientError as e:
        # Rollback reservation in DynamoDB if EC2 creation fails
        release_user_vm(user_id)
        raise HTTPException(status_code=400, detail=str(e)) from e

    instance = resp["Instances"][0]
    instance_id = instance["InstanceId"]
    state = instance["State"]["Name"]

    # 3. Save instance metadata to DynamoDB
    create_instance_record(
        instance_id=instance_id,
        user_id=user_id,
        exercise_id=exercise_id,
        instance_name=instance_name,
        instance_type=target_type,
        ami_id=target_ami,
        state=state,
        public_ip=instance.get("PublicIpAddress"),
        private_ip=instance.get("PrivateIpAddress"),
        launch_time=now_iso,
    )

    # 4. Finalize user's active_instance_id
    assign_user_vm(user_id, instance_id)

    return InstanceInfo(
        instance_id=instance_id,
        user_id=user_id,
        exercise_id=exercise_id,
        name=instance_name,
        state=state,
        instance_type=target_type,
        public_ip=instance.get("PublicIpAddress"),
        private_ip=instance.get("PrivateIpAddress"),
        launch_time=now_iso,
        created_at=now_iso,
    )


def list_instances(
    user_id: Optional[str] = None,
    sync_with_ec2: bool = True,
) -> list[InstanceInfo]:
    """
    List instances from DynamoDB (or EC2) with updated runtime status.
    """
    if user_id:
        records = db_list_instances_by_user(user_id)
    else:
        records = db_list_all_instances()

    # Optionally sync real-time status with EC2 for non-terminated instances
    client = get_ec2_client()
    instance_ids_to_sync = [
        r["instance_id"] for r in records if r.get("state") != "terminated"
    ]

    ec2_status_map = {}
    if sync_with_ec2 and instance_ids_to_sync:
        try:
            resp = client.describe_instances(InstanceIds=instance_ids_to_sync)
            for res in resp.get("Reservations", []):
                for inst in res.get("Instances", []):
                    iid = inst["InstanceId"]
                    istate = inst["State"]["Name"]
                    pub_ip = inst.get("PublicIpAddress")
                    priv_ip = inst.get("PrivateIpAddress")
                    ec2_status_map[iid] = {
                        "state": istate,
                        "public_ip": pub_ip,
                        "private_ip": priv_ip,
                    }
                    # Update DynamoDB with latest state and IPs
                    update_instance_state(iid, istate, pub_ip, priv_ip)
        except ClientError:
            pass  # Fallback to DynamoDB record if describe fails

    results: list[InstanceInfo] = []
    for r in records:
        iid = r["instance_id"]
        latest = ec2_status_map.get(iid, {})
        results.append(
            InstanceInfo(
                instance_id=iid,
                user_id=r.get("user_id"),
                exercise_id=r.get("exercise_id"),
                name=r.get("name"),
                state=latest.get("state", r.get("state", "unknown")),
                instance_type=r.get("instance_type", ""),
                public_ip=latest.get("public_ip", r.get("public_ip")),
                private_ip=latest.get("private_ip", r.get("private_ip")),
                launch_time=r.get("launch_time"),
                created_at=r.get("created_at"),
                terminated_at=r.get("terminated_at"),
            )
        )
    return results


def get_instance_details(instance_id: str) -> Optional[dict]:
    return get_instance_record(instance_id)


def start_instance(instance_id: str) -> dict:
    client = get_ec2_client()
    try:
        resp = client.start_instances(InstanceIds=[instance_id])
    except ClientError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    state = resp["StartingInstances"][0]["CurrentState"]["Name"]

    # Sync state in DynamoDB
    update_instance_state(instance_id, state)
    return {
        "instance_id": instance_id,
        "state": state,
        "message": "instance กำลังเริ่มทำงาน",
    }


def stop_instance(instance_id: str) -> dict:
    client = get_ec2_client()
    try:
        resp = client.stop_instances(InstanceIds=[instance_id])
    except ClientError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    state = resp["StoppingInstances"][0]["CurrentState"]["Name"]

    # Sync state in DynamoDB
    update_instance_state(instance_id, state)
    return {
        "instance_id": instance_id,
        "state": state,
        "message": "instance กำลังปิดเครื่อง",
    }


def terminate_instance(instance_id: str) -> dict:
    client = get_ec2_client()
    try:
        resp = client.terminate_instances(InstanceIds=[instance_id])
    except ClientError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    state = resp["TerminatingInstances"][0]["CurrentState"]["Name"]

    # 1. Update DynamoDB instance record as terminated
    mark_instance_terminated(instance_id)

    # 2. Free user's active_instance_id slot in DynamoDB so they can launch a new VM
    instance_rec = get_instance_record(instance_id)
    if instance_rec and instance_rec.get("user_id"):
        release_user_vm(instance_rec["user_id"])

    return {
        "instance_id": instance_id,
        "state": state,
        "message": "instance กำลังถูกลบ (terminate) และปล่อยโควตา VM เรียบร้อยแล้ว",
    }


def create_instance_image(
    instance_id: str,
    name: str,
    description: str = "",
    no_reboot: bool = True,
) -> str:
    """
    สั่ง AWS EC2 สร้าง AMI (Snapshot) จาก EC2 Instance
    - instance_id: รหัส instance ที่ต้องการ snapshot
    - name: ชื่อของ AMI (ห้ามซ้ำ)
    - description: คำอธิบาย AMI
    - no_reboot: True เพื่อไม่ต้องสั่ง restart instance ขณะทำ snapshot
    คืนค่า ImageId (ami-xxxxxxxxx)
    """
    client = get_ec2_client()
    try:
        resp = client.create_image(
            InstanceId=instance_id,
            Name=name,
            Description=description,
            NoReboot=no_reboot,
            TagSpecifications=[
                {
                    "ResourceType": "image",
                    "Tags": [
                        {"Key": "Project", "Value": PROJECT_TAG_VALUE},
                        {"Key": "Name", "Value": name},
                        {"Key": "SourceInstanceId", "Value": instance_id},
                    ],
                }
            ],
        )
        return resp["ImageId"]
    except ClientError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


def get_image_status(ami_id: str) -> str:
    """
    ตรวจสอบสถานะของ AMI บน AWS EC2
    คืนค่าสถานะ เช่น "pending", "available", "failed", หรือ "not_found"
    """
    client = get_ec2_client()
    try:
        resp = client.describe_images(ImageIds=[ami_id])
        images = resp.get("Images", [])
        if not images:
            return "not_found"
        return images[0]["State"]
    except ClientError as e:
        if e.response["Error"]["Code"] in ("InvalidAMIID.NotFound", "InvalidAMIID.Malformed"):
            return "not_found"
        return "unknown"


def deregister_image(ami_id: str) -> None:
    """
    ยกเลิกการลงทะเบียน (De-register) AMI บน AWS EC2 เมื่อลบแบบฝึกหัด
    """
    client = get_ec2_client()
    try:
        client.deregister_image(ImageId=ami_id)
    except ClientError as e:
        if e.response["Error"]["Code"] != "InvalidAMIID.NotFound":
            raise HTTPException(status_code=400, detail=str(e)) from e
