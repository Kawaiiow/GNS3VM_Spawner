"""
dynamodb_service.py
-------------------
Logic สำหรับการเชื่อมต่อและจัดการข้อมูลใน DynamoDB:
- Users table: จัดการข้อมูลผู้ใช้, รหัสผ่าน (member_id), และการล็อก 1-VM per user แบบ atomic
- Instances table: บันทึกข้อมูลและสถานะของ EC2 instance (ลด key ที่ซ้ำซ้อน โดยผูกตรงกับ user_id เท่านั้น)
- Exercises table: แบบฝึกหัด Lab ที่สร้างจาก Snapshot AMI
"""

from datetime import datetime, timezone
from typing import Any, Optional
import uuid
import boto3
from boto3.dynamodb.conditions import Key, Attr
from botocore.exceptions import ClientError
from fastapi import HTTPException, status
from functools import lru_cache

from app.config import get_settings

# 1. Cache the settings so it only reads the environment once
@lru_cache()
def get_cached_settings():
    return get_settings()

def _get_boto3_kwargs() -> dict[str, Any]:
    settings = get_cached_settings()
    kwargs: dict[str, Any] = {
        "region_name": settings.aws_region,
        "aws_access_key_id": settings.aws_access_key_id,
        "aws_secret_access_key": settings.aws_secret_access_key,
    }
    if settings.aws_session_token:
        kwargs["aws_session_token"] = settings.aws_session_token
    if settings.dynamodb_endpoint_url:
        kwargs["endpoint_url"] = settings.dynamodb_endpoint_url
    return kwargs

# 2. Global variables to maintain the HTTP Keep-Alive connection pool
_dynamodb_resource = None
_dynamodb_client = None
_tables = {}

def get_dynamodb_resource():
    global _dynamodb_resource
    if _dynamodb_resource is None:
        _dynamodb_resource = boto3.resource("dynamodb", **_get_boto3_kwargs())
    return _dynamodb_resource

def get_dynamodb_client():
    global _dynamodb_client
    if _dynamodb_client is None:
        _dynamodb_client = boto3.client("dynamodb", **_get_boto3_kwargs())
    return _dynamodb_client

# 3. Cache the Table objects to avoid recreating them
def get_users_table():
    if "users" not in _tables:
        _tables["users"] = get_dynamodb_resource().Table(get_cached_settings().users_table_name)
    return _tables["users"]

def get_instances_table():
    if "instances" not in _tables:
        _tables["instances"] = get_dynamodb_resource().Table(get_cached_settings().instances_table_name)
    return _tables["instances"]

def get_exercises_table():
    if "exercises" not in _tables:
        _tables["exercises"] = get_dynamodb_resource().Table(get_cached_settings().exercises_table_name)
    return _tables["exercises"]

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ==========================================
# USERS CRUD & AUTH
# ==========================================

def get_user_by_id(user_id: str) -> Optional[dict]:
    table = get_users_table()
    try:
        response = table.get_item(Key={"user_id": user_id})
        return response.get("Item")
    except ClientError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"DynamoDB error: {e.response['Error']['Message']}",
        )


def get_user_by_username(username: str) -> Optional[dict]:
    table = get_users_table()
    try:
        response = table.query(
            IndexName="UsernameIndex",
            KeyConditionExpression=Key("username").eq(username),
        )
        items = response.get("Items", [])
        return items[0] if items else None
    except ClientError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"DynamoDB error querying username: {e.response['Error']['Message']}",
        )


def get_user_by_member_id(member_id: str) -> Optional[dict]:
    table = get_users_table()
    try:
        response = table.query(
            IndexName="MemberIdIndex",
            KeyConditionExpression=Key("member_id").eq(member_id),
        )
        items = response.get("Items", [])
        return items[0] if items else None
    except ClientError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"DynamoDB error querying member_id: {e.response['Error']['Message']}",
        )


def get_user_by_identifier(identifier: str) -> Optional[dict]:
    """ค้นหา user จาก username ก่อน หากไม่เจอให้ค้นหาจาก member_id"""
    user = get_user_by_username(identifier)
    if not user:
        user = get_user_by_member_id(identifier)
    return user


def create_user(
    username: str,
    member_id: str,
    password_hash: str,
    role: str = "student",
    full_name: Optional[str] = None,
) -> dict:
    table = get_users_table()

    # ตรวจสอบความซ้ำซ้อนของ username และ member_id
    if get_user_by_username(username):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Username '{username}' is already in use.",
        )
    if get_user_by_member_id(member_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Member ID '{member_id}' is already registered.",
        )

    user_id = str(uuid.uuid4())
    now = _now_iso()
    user_item = {
        "user_id": user_id,
        "username": username,
        "member_id": member_id,
        "password_hash": password_hash,
        "full_name": full_name or "",
        "role": role,
        "active_instance_id": None,
        "active_exercise_instance_id": None,
        "created_at": now,
        "updated_at": now,
    }

    try:
        table.put_item(
            Item=user_item,
            ConditionExpression="attribute_not_exists(user_id)",
        )
        return user_item
    except ClientError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error creating user in DynamoDB: {e.response['Error']['Message']}",
        )


def list_all_users() -> list[dict]:
    table = get_users_table()
    try:
        response = table.scan()
        return response.get("Items", [])
    except ClientError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"DynamoDB error scanning users: {e.response['Error']['Message']}",
        )


def update_user_fields(user_id: str, fields: dict) -> dict:
    """แก้ไขฟิลด์ของผู้ใช้ (Admin) คืนค่า item ใหม่ทั้งก้อน"""
    table = get_users_table()
    names: dict = {}
    values: dict = {":now": _now_iso()}
    sets = ["updated_at = :now"]
    for key, value in fields.items():
        names[f"#{key}"] = key
        values[f":{key}"] = value
        sets.append(f"#{key} = :{key}")
    try:
        resp = table.update_item(
            Key={"user_id": user_id},
            UpdateExpression="SET " + ", ".join(sets),
            ExpressionAttributeNames=names or None,
            ExpressionAttributeValues=values,
            ConditionExpression="attribute_exists(user_id)",
            ReturnValues="ALL_NEW",
        ) if names else table.update_item(
            Key={"user_id": user_id},
            UpdateExpression="SET " + ", ".join(sets),
            ExpressionAttributeValues=values,
            ConditionExpression="attribute_exists(user_id)",
            ReturnValues="ALL_NEW",
        )
        return resp["Attributes"]
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="ไม่พบผู้ใช้นี้"
            )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error updating user: {e.response['Error']['Message']}",
        )


def delete_user_record(user_id: str) -> None:
    table = get_users_table()
    try:
        table.delete_item(Key={"user_id": user_id})
    except ClientError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error deleting user: {e.response['Error']['Message']}",
        )


# ==========================================
# 1-VM PER USER ATOMIC LOCKING
# ==========================================

# ช่องล็อกต่อผู้ใช้ (ใช้กับ role student เท่านั้น)
SANDBOX_SLOT = "active_instance_id"
EXERCISE_SLOT = "active_exercise_instance_id"


def reserve_user_vm_slot(user_id: str, slot: str = SANDBOX_SLOT) -> None:
    table = get_users_table()
    now = _now_iso()

    try:
        table.update_item(
            Key={"user_id": user_id},
            UpdateExpression="SET #slot = :pending, updated_at = :now",
            ConditionExpression="attribute_not_exists(#slot) OR #slot = :none OR #slot = :null_str",
            ExpressionAttributeNames={"#slot": slot},
            ExpressionAttributeValues={
                ":pending": "PENDING_LAUNCH",
                ":none": None,
                ":null_str": "",
                ":now": now,
            },
        )
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            user = get_user_by_id(user_id)
            active_id = user.get(slot) if user else "existing VM"
            if slot == EXERCISE_SLOT:
                detail = (
                    f"User already owns an active exercise VM ({active_id}). "
                    "Finish the current exercise (Done) before starting another."
                )
            else:
                detail = (
                    f"User already owns an active VM instance ({active_id}). "
                    "Every student is limited to 1 active sandbox VM."
                )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=detail,
            )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to reserve VM slot in DynamoDB: {e.response['Error']['Message']}",
        )


def assign_user_vm(user_id: str, instance_id: str, slot: str = SANDBOX_SLOT) -> None:
    table = get_users_table()
    now = _now_iso()
    try:
        table.update_item(
            Key={"user_id": user_id},
            UpdateExpression="SET #slot = :inst, updated_at = :now",
            ExpressionAttributeNames={"#slot": slot},
            ExpressionAttributeValues={
                ":inst": instance_id,
                ":now": now,
            },
        )
    except ClientError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update user active instance: {e.response['Error']['Message']}",
        )


def release_user_vm(user_id: str, slot: str = SANDBOX_SLOT) -> None:
    table = get_users_table()
    now = _now_iso()
    try:
        table.update_item(
            Key={"user_id": user_id},
            UpdateExpression="SET #slot = :none, updated_at = :now",
            ExpressionAttributeNames={"#slot": slot},
            ExpressionAttributeValues={
                ":none": None,
                ":now": now,
            },
        )
    except ClientError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to release user VM slot: {e.response['Error']['Message']}",
        )


# ==========================================
# VM INSTANCES CRUD (REDUCED SCHEMA - USER_ID ONLY)
# ==========================================

def create_instance_record(
    instance_id: str,
    user_id: str,
    instance_name: str,
    instance_type: str,
    ami_id: str,
    exercise_id: Optional[str] = None,
    state: str = "pending",
    public_ip: Optional[str] = None,
    private_ip: Optional[str] = None,
    launch_time: Optional[str] = None,
    gns3_user: Optional[str] = None,
    gns3_password: Optional[str] = None,
) -> dict:
    table = get_instances_table()
    now = _now_iso()
    item = {
        "instance_id": instance_id,
        "user_id": user_id,
        "exercise_id": exercise_id,
        "name": instance_name,
        "instance_type": instance_type,
        "ami_id": ami_id,
        "state": state,
        "public_ip": public_ip,
        "private_ip": private_ip,
        "launch_time": launch_time or now,
        "created_at": now,
        "updated_at": now,
        "terminated_at": None,
    }
    if gns3_user and gns3_password:
        item["gns3_user"] = gns3_user
        item["gns3_password"] = gns3_password
    try:
        table.put_item(Item=item)
        return item
    except ClientError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error saving instance record to DynamoDB: {e.response['Error']['Message']}",
        )


def get_instance_record(instance_id: str) -> Optional[dict]:
    table = get_instances_table()
    try:
        response = table.get_item(Key={"instance_id": instance_id})
        return response.get("Item")
    except ClientError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error getting instance record: {e.response['Error']['Message']}",
        )


def update_instance_state(
    instance_id: str,
    state: str,
    public_ip: Optional[str] = None,
    private_ip: Optional[str] = None,
    clear_public_ip: bool = False,
) -> None:
    table = get_instances_table()
    now = _now_iso()

    expr_parts = ["#st = :state", "updated_at = :now"]
    attr_names = {"#st": "state"}
    attr_values = {":state": state, ":now": now}

    if public_ip is not None:
        expr_parts.append("public_ip = :pub_ip")
        attr_values[":pub_ip"] = public_ip
    elif clear_public_ip:
        # instance ถูก stop / ไม่มี public IP แล้ว -> เซ็ตเป็น None ใน DB
        expr_parts.append("public_ip = :pub_ip")
        attr_values[":pub_ip"] = None
    if private_ip is not None:
        expr_parts.append("private_ip = :priv_ip")
        attr_values[":priv_ip"] = private_ip

    update_expr = "SET " + ", ".join(expr_parts)

    try:
        table.update_item(
            Key={"instance_id": instance_id},
            UpdateExpression=update_expr,
            ExpressionAttributeNames=attr_names,
            ExpressionAttributeValues=attr_values,
        )
    except ClientError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error updating instance state: {e.response['Error']['Message']}",
        )


def mark_instance_terminated(instance_id: str) -> None:
    table = get_instances_table()
    now = _now_iso()
    try:
        table.update_item(
            Key={"instance_id": instance_id},
            UpdateExpression="SET #st = :term, terminated_at = :now, updated_at = :now",
            ExpressionAttributeNames={"#st": "state"},
            ExpressionAttributeValues={
                ":term": "terminated",
                ":now": now,
            },
        )
    except ClientError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error marking instance terminated: {e.response['Error']['Message']}",
        )


def list_instances_by_user(user_id: str, include_terminated: bool = False) -> list[dict]:
    """Query หา instances ตาม user_id ผ่าน UserIdIndex (ไม่ต้องมี StudentIdIndex ให้เปลืองทรัพยากร)"""
    table = get_instances_table()
    try:
        response = table.query(
            IndexName="UserIdIndex",
            KeyConditionExpression=Key("user_id").eq(user_id),
        )
        items = response.get("Items", [])
        if not include_terminated:
            items = [item for item in items if item.get("state") != "terminated"]
        return items
    except ClientError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error listing instances by user: {e.response['Error']['Message']}",
        )


def list_all_instances(include_terminated: bool = False) -> list[dict]:
    table = get_instances_table()
    try:
        response = table.scan()
        items = response.get("Items", [])
        if not include_terminated:
            items = [item for item in items if item.get("state") != "terminated"]
        return items
    except ClientError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error scanning instances: {e.response['Error']['Message']}",
        )


# ==========================================
# EXERCISES CRUD
# ==========================================

def create_exercise_record(
    instructor_id: str,
    title: str,
    ami_id: Optional[str] = None,
    description: Optional[str] = None,
    status: str = "available",
    is_active: bool = True,
    exercise_id: Optional[str] = None,
    s3_key: Optional[str] = None,
    project_name: Optional[str] = None,
) -> dict:
    table = get_exercises_table()
    exercise_id =  exercise_id or str(uuid.uuid4())
    now = _now_iso()
    item = {
        "exercise_id": exercise_id,
        "instructor_id": instructor_id,
        "title": title,
        "description": description or "",
        "ami_id": ami_id,
        "status": status,
        "is_active": is_active,
        "created_at": now,
        "updated_at": now,
    }
    # เก็บเฉพาะฟิลด์ที่มีค่า (แบบฝึกหัดอาจเป็น AMI หรือ S3 อย่างใดอย่างหนึ่ง)
    if ami_id:
        item["ami_id"] = ami_id
    if s3_key:
        item["s3_key"] = s3_key
    if project_name:
        item["project_name"] = project_name    
    try:
        table.put_item(Item=item)
        return item
    except ClientError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error creating exercise in DynamoDB: {e.response['Error']['Message']}",
        )


def get_exercise_record(exercise_id: str) -> Optional[dict]:
    table = get_exercises_table()
    try:
        response = table.get_item(Key={"exercise_id": exercise_id})
        return response.get("Item")
    except ClientError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error getting exercise: {e.response['Error']['Message']}",
        )


def list_all_exercises(only_active: bool = True) -> list[dict]:
    table = get_exercises_table()
    try:
        if only_active:
            response = table.scan(
                FilterExpression=Attr("is_active").eq(True)
            )
        else:
            response = table.scan()
        return response.get("Items", [])
    except ClientError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error scanning exercises: {e.response['Error']['Message']}",
        )


def list_exercises_by_instructor(instructor_id: str) -> list[dict]:
    table = get_exercises_table()
    try:
        response = table.query(
            IndexName="InstructorIdIndex",
            KeyConditionExpression=Key("instructor_id").eq(instructor_id),
        )
        return response.get("Items", [])
    except ClientError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error querying exercises by instructor: {e.response['Error']['Message']}",
        )


def update_exercise_status(
    exercise_id: str, status_val: str, detail: Optional[str] = None
) -> None:
    table = get_exercises_table()
    now = _now_iso()
    expr = "SET #st = :s, updated_at = :now"
    values: dict[str, Any] = {":s": status_val, ":now": now}
    if detail:
        expr += ", status_detail = :d"
        values[":d"] = detail
    elif status_val == "available":
        expr += " REMOVE status_detail"  # ล้างข้อความ error เก่า
    try:
        table.update_item(
            Key={"exercise_id": exercise_id},
            UpdateExpression=expr,
            ExpressionAttributeNames={"#st": "status"},
            ExpressionAttributeValues=values,
        )
    except ClientError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error updating exercise status: {e.response['Error']['Message']}",
        )


def delete_exercise_record(exercise_id: str) -> None:
    table = get_exercises_table()
    try:
        table.delete_item(Key={"exercise_id": exercise_id})
    except ClientError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error deleting exercise from DynamoDB: {e.response['Error']['Message']}",
        )