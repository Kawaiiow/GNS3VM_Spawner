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

from app.config import get_settings


def _get_boto3_kwargs() -> dict[str, Any]:
    settings = get_settings()
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


def get_dynamodb_resource():
    return boto3.resource("dynamodb", **_get_boto3_kwargs())


def get_dynamodb_client():
    return boto3.client("dynamodb", **_get_boto3_kwargs())


def get_users_table():
    settings = get_settings()
    return get_dynamodb_resource().Table(settings.users_table_name)


def get_instances_table():
    settings = get_settings()
    return get_dynamodb_resource().Table(settings.instances_table_name)


def get_exercises_table():
    settings = get_settings()
    return get_dynamodb_resource().Table(settings.exercises_table_name)


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


# ==========================================
# 1-VM PER USER ATOMIC LOCKING
# ==========================================

def reserve_user_vm_slot(user_id: str) -> None:
    table = get_users_table()
    now = _now_iso()

    try:
        table.update_item(
            Key={"user_id": user_id},
            UpdateExpression="SET active_instance_id = :pending, updated_at = :now",
            ConditionExpression="attribute_not_exists(active_instance_id) OR active_instance_id = :none OR active_instance_id = :null_str",
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
            active_id = user.get("active_instance_id") if user else "existing VM"
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"User already owns an active VM instance ({active_id}). Every user is limited to 1 active VM.",
            )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to reserve VM slot in DynamoDB: {e.response['Error']['Message']}",
        )


def assign_user_vm(user_id: str, instance_id: str) -> None:
    table = get_users_table()
    now = _now_iso()
    try:
        table.update_item(
            Key={"user_id": user_id},
            UpdateExpression="SET active_instance_id = :inst, updated_at = :now",
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


def release_user_vm(user_id: str) -> None:
    table = get_users_table()
    now = _now_iso()
    try:
        table.update_item(
            Key={"user_id": user_id},
            UpdateExpression="SET active_instance_id = :none, updated_at = :now",
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
) -> None:
    table = get_instances_table()
    now = _now_iso()

    expr_parts = ["#st = :state", "updated_at = :now"]
    attr_names = {"#st": "state"}
    attr_values = {":state": state, ":now": now}

    if public_ip is not None:
        expr_parts.append("public_ip = :pub_ip")
        attr_values[":pub_ip"] = public_ip
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
    ami_id: str,
    description: Optional[str] = None,
    status: str = "available",
    is_active: bool = True,
) -> dict:
    table = get_exercises_table()
    exercise_id = str(uuid.uuid4())
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


def update_exercise_status(exercise_id: str, status_val: str) -> None:
    table = get_exercises_table()
    now = _now_iso()
    try:
        table.update_item(
            Key={"exercise_id": exercise_id},
            UpdateExpression="SET #st = :s, updated_at = :now",
            ExpressionAttributeNames={"#st": "status"},
            ExpressionAttributeValues={":s": status_val, ":now": now},
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
