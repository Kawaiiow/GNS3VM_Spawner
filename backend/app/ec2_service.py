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

import secrets
import string
from urllib.parse import quote
from datetime import datetime, timezone
from typing import Optional

import boto3
from botocore.exceptions import ClientError, WaiterError
from fastapi import HTTPException

from app import s3_service
from app.config import get_settings
from app.dynamodb_service import (
    EXERCISE_SLOT,
    SANDBOX_SLOT,
    assign_user_vm,
    create_instance_record,
    get_exercise_record,
    get_instance_record,
    get_user_by_id,
    list_all_instances as db_list_all_instances,
    list_instances_by_exercise as db_list_instances_by_exercise,
    list_instances_by_user as db_list_instances_by_user,
    mark_instance_terminated,
    release_user_vm,
    reserve_user_vm_slot,
    update_exercise_status,
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


def _generate_vm_password(length: int = 16) -> str:
    """สุ่มรหัสผ่านตัวอักษร+ตัวเลขเท่านั้น (ปลอดภัยต่อ sed / ไฟล์ ini)"""
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


_GNS3_USER_DATA_TEMPLATE = r"""#!/bin/bash
# NetLab: set a unique GNS3 login for this VM (runs on first boot)
CONF="__CONF__"
for i in $(seq 1 60); do [ -f "$CONF" ] && break; sleep 2; done
if [ -f "$CONF" ]; then
  sed -i -E '/^(auth|user|password)[[:space:]]*=/d' "$CONF"
  sed -i -e '/^\[Server\]/a password = __PASSWORD__' \
         -e '/^\[Server\]/a user = __USER__' \
         -e '/^\[Server\]/a auth = True' "$CONF"
  systemctl restart __SERVICE__
fi
"""


def _build_gns3_user_data(user: str, password: str) -> str:
    settings = get_settings()
    return (
        _GNS3_USER_DATA_TEMPLATE.replace("__CONF__", settings.gns3_config_path)
        .replace("__USER__", user)
        .replace("__PASSWORD__", password)
        .replace("__SERVICE__", settings.gns3_service_name)
    )

# ต่อท้าย UserData ของ VM แบบฝึกหัด: ดาวน์โหลดไฟล์ .gns3project จาก S3 (presigned URL)
# แล้ว import เข้า GNS3 ผ่าน REST API ของเครื่องตัวเอง (first boot เท่านั้น)
# log อยู่ที่ /var/log/netlab-import.log
_GNS3_IMPORT_USER_DATA_TEMPLATE = r"""
# NetLab: import exercise project from S3
exec >>/var/log/netlab-import.log 2>&1
AUTH="__USER__:__PASSWORD__"
API="http://127.0.0.1:__PORT__/v2"
for i in $(seq 1 150); do
  code=$(curl -s -o /dev/null -w "%{http_code}" -u "$AUTH" "$API/version")
  [ "$code" = "200" ] && break
  sleep 2
done
curl -fsSL -o /tmp/exercise.gns3project "__URL__" || { echo "download failed"; exit 1; }
PID=$(cat /proc/sys/kernel/random/uuid)
curl -fsS -u "$AUTH" -X POST -H "Content-Type: application/octet-stream" \
  --data-binary @/tmp/exercise.gns3project \
  "$API/projects/$PID/import?name=__NAME__" && echo "import ok"
rm -f /tmp/exercise.gns3project
"""

def _build_import_user_data(user: str, password: str, s3_key: str, title: Optional[str]) -> str:
    settings = get_settings()
    url = s3_service.presign_get(s3_key)
    name = "".join(c for c in (title or "") if c.isalnum() or c in ("-", "_")).strip()
    name = quote(name[:40] or "exercise", safe="")
    return (
        _GNS3_IMPORT_USER_DATA_TEMPLATE.replace("__USER__", user)
        .replace("__PASSWORD__", password)
        .replace("__PORT__", str(settings.gns3_api_port))
        .replace("__URL__", url)
        .replace("__NAME__", name)
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
    role: Optional[str] = None,
) -> InstanceInfo:
    """
    กฎจำนวน VM:
    - student:    Sandbox 1 เครื่อง + Exercise 1 เครื่อง (ล็อกแยกกัน)
    - instructor: ไม่จำกัด
    (admin สร้าง VM ไม่ได้ ถูกบล็อกที่ชั้น API)
    """
    settings = get_settings()
    client = get_ec2_client()

    # ตรวจสอบ exercise_id (ถ้ามีส่งมา)
    resolved_ami = ami_id
    exercise_s3_key: Optional[str] = None
    exercise_title: Optional[str] = None

    if exercise_id:
        exercise = get_exercise_record(exercise_id)
        if not exercise or not exercise.get("is_active"):
            raise HTTPException(
                status_code=400,
                detail=f"Exercise '{exercise_id}' not found or inactive.",
            )
        # Snapshot ต้องพร้อมใช้งาน (available) ก่อนถึงจะสร้าง VM จากแบบฝึกหัดนี้ได้
        ex_status = exercise.get("status", "available")
        if ex_status != "available":
            real_status = (
                get_image_status(exercise["ami_id"])
                if exercise.get("ami_id")
                else ex_status  # แบบ S3: ใช้สถานะที่ background export อัปเดตไว้ (pending/failed)
            )
            if real_status in ("available", "failed"):
                update_exercise_status(exercise_id, real_status)
            if real_status != "available":
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "แบบฝึกหัดนี้ยังไม่พร้อมใช้งาน "
                        f"(snapshot สถานะ: {real_status}) กรุณารอสักครู่แล้วลองใหม่"
                    ),
                )
        if not resolved_ami:
            resolved_ami = exercise.get("ami_id")
        # แบบฝึกหัดที่ export ไว้ที่ S3: launch จาก base AMI แล้ว import โปรเจ็คตอน first boot
        exercise_s3_key = exercise.get("s3_key")
        exercise_title = exercise.get("title")
        if exercise_s3_key and not settings.gns3_set_vm_password:
            raise HTTPException(
                status_code=500,
                detail="ต้องเปิด GNS3_SET_VM_PASSWORD=true เพื่อ import แบบฝึกหัดจาก S3",
            )

    # 1. Atomic reservation in DynamoDB (เฉพาะ student) แยกช่อง Sandbox / Exercise
    slot = EXERCISE_SLOT if exercise_id else SANDBOX_SLOT
    limited = (role or "student") == "student"
    if limited:
        reserve_user_vm_slot(user_id, slot)

    def _rollback():
        if limited:
            release_user_vm(user_id, slot)

    # 2. Check project concurrent instance limits
    try:
        if _count_active_project_instances(client) >= settings.max_concurrent_instances:
            _rollback()
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
            _rollback()
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

    # รหัสผ่าน GNS3 เฉพาะ VM เครื่องนี้ (ตั้งผ่าน UserData ตอน first boot)
    gns3_user: Optional[str] = None
    gns3_password: Optional[str] = None
    if settings.gns3_set_vm_password:
        gns3_user = settings.gns3_vm_user
        gns3_password = _generate_vm_password()
        user_data = _build_gns3_user_data(gns3_user, gns3_password)
        if exercise_s3_key:
            try:
                user_data += _build_import_user_data(
                    gns3_user, gns3_password, exercise_s3_key, exercise_title
                )
            except Exception as e:
                _rollback()
                raise HTTPException(
                    status_code=500, detail=f"สร้าง presigned URL ของแบบฝึกหัดไม่สำเร็จ: {e}"
                ) from e
        run_instances_kwargs["UserData"] = user_data

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
        _rollback()
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
        gns3_user=gns3_user,
        gns3_password=gns3_password,
    )

    # 4. Finalize ช่องล็อกของ student (instructor ไม่มีล็อก)
    if limited:
        assign_user_vm(user_id, instance_id, slot)

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
        gns3_user=gns3_user,
        gns3_password=gns3_password,
    )


def list_instances(
    user_id: Optional[str] = None,
    sync_with_ec2: bool = True,
    include_credentials: bool = False,
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
                    update_instance_state(
                        iid, istate, pub_ip, priv_ip, clear_public_ip=pub_ip is None
                    )
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
                gns3_user=r.get("gns3_user") if include_credentials else None,
                gns3_password=r.get("gns3_password") if include_credentials else None,
            )
        )
    return results


def get_instance_details(instance_id: str) -> Optional[dict]:
    return get_instance_record(instance_id)


def _sync_instance_from_ec2(client, instance_id: str) -> tuple[str, Optional[str]]:
    """อ่านสถานะ + IP จริงจาก EC2 แล้วบันทึกลง DynamoDB คืนค่า (state, public_ip)"""
    resp = client.describe_instances(InstanceIds=[instance_id])
    inst = resp["Reservations"][0]["Instances"][0]
    state = inst["State"]["Name"]
    pub_ip = inst.get("PublicIpAddress")
    priv_ip = inst.get("PrivateIpAddress")
    update_instance_state(
        instance_id, state, pub_ip, priv_ip, clear_public_ip=pub_ip is None
    )
    return state, pub_ip


def start_instance(instance_id: str) -> dict:
    client = get_ec2_client()
    try:
        resp = client.start_instances(InstanceIds=[instance_id])
    except ClientError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    state = resp["StartingInstances"][0]["CurrentState"]["Name"]
    update_instance_state(instance_id, state)

    # รอให้เครื่องเป็น running เพื่อให้ได้ public IP ใหม่ แล้วบันทึกลง DB ก่อนตอบกลับ
    public_ip: Optional[str] = None
    try:
        client.get_waiter("instance_running").wait(
            InstanceIds=[instance_id],
            WaiterConfig={"Delay": 3, "MaxAttempts": 40},
        )
        state, public_ip = _sync_instance_from_ec2(client, instance_id)
    except (WaiterError, ClientError):
        pass  # ยังไม่พร้อม: ตอบ state ปัจจุบัน แล้วให้ GET /instances sync ภายหลัง

    return {
        "instance_id": instance_id,
        "state": state,
        "public_ip": public_ip,
        "message": (
            "instance เริ่มทำงานแล้ว" if state == "running" else "instance กำลังเริ่มทำงาน"
        ),
    }


def stop_instance(instance_id: str) -> dict:
    client = get_ec2_client()
    try:
        resp = client.stop_instances(InstanceIds=[instance_id])
    except ClientError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    state = resp["StoppingInstances"][0]["CurrentState"]["Name"]

    # Public IP จะถูกปล่อยเมื่อ stop -> เซ็ต public_ip เป็น None ใน DB ทันที
    update_instance_state(instance_id, state, clear_public_ip=True)
    return {
        "instance_id": instance_id,
        "state": state,
        "public_ip": None,
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

    # 2. คืนช่องล็อกที่ผูกกับ instance นี้ (Sandbox หรือ Exercise) เพื่อให้สร้างใหม่ได้
    _release_user_slots(instance_id)

    return {
        "instance_id": instance_id,
        "state": state,
        "message": "instance กำลังถูกลบ (terminate) และปล่อยโควตา VM เรียบร้อยแล้ว",
    }


def _release_user_slots(instance_id: str) -> None:
    """คืนช่องล็อก (Sandbox / Exercise) ที่ผูกกับ instance นี้ให้เจ้าของ"""
    instance_rec = get_instance_record(instance_id)
    if instance_rec and instance_rec.get("user_id"):
        owner = get_user_by_id(instance_rec["user_id"])
        if owner:
            for slot in (SANDBOX_SLOT, EXERCISE_SLOT):
                if owner.get(slot) == instance_id:
                    release_user_vm(owner["user_id"], slot)


def terminate_instances_for_exercise(exercise_id: str) -> list[str]:
    """
    terminate ทุก VM ที่สร้างจากแบบฝึกหัดนี้ (เฉพาะ exercise_id เดียวกัน) และคืนโควตาให้เจ้าของ
    คืนค่ารายการ instance_id ที่ถูกลบ ถ้ามีบางเครื่องลบไม่สำเร็จจะ raise 500
    (เรียกซ้ำได้ เพราะเครื่องที่ลบไปแล้วจะไม่ถูกนับอีก)
    """
    terminated: list[str] = []
    failed: list[str] = []
    for rec in db_list_instances_by_exercise(exercise_id):
        iid = rec["instance_id"]
        try:
            terminate_instance(iid)
        except HTTPException as e:
            if "InvalidInstanceID.NotFound" in str(e.detail):
                # EC2 ไม่รู้จักเครื่องนี้แล้ว (หายไปเอง เช่น Lab ถูกรีเซ็ต) เก็บกวาดฝั่ง DB อย่างเดียว
                mark_instance_terminated(iid)
                _release_user_slots(iid)
            else:
                failed.append(iid)
                continue
        terminated.append(iid)
    if failed:
        raise HTTPException(
            status_code=500,
            detail=(
                f"terminate VM ของแบบฝึกหัดไม่สำเร็จ {failed} "
                "แบบฝึกหัดยังไม่ถูกลบ กรุณาลองใหม่อีกครั้ง"
            ),
        )
    return terminated


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