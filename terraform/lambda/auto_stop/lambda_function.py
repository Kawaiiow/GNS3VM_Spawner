"""
NetLab auto-stop Lambda
-----------------------
ถูกเรียกโดย EventBridge ทุกๆ N นาที:
  1. scan ตาราง instances หา record ที่ auto_stop = true และ expires_at <= ตอนนี้
  2. "จอง" record นั้นก่อนด้วย conditional update (ลบ expires_at ถ้ายังหมดเวลาอยู่จริง)
     -> ถ้า student กดรีเวลาพอดี เงื่อนไขจะไม่ผ่าน และเราจะข้าม VM นั้นไป
  3. ตรวจสถานะจริงบน EC2 แล้วสั่ง stop_instances เฉพาะ VM ที่ running/pending
  4. ถ้า stop ไม่สำเร็จ จะคืน expires_at เดิมเพื่อให้รอบถัดไปลองใหม่

ENV ที่ต้องมี: INSTANCES_TABLE   (AWS_REGION ถูกตั้งให้โดย Lambda runtime อยู่แล้ว)
"""

import logging
import os
import time
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

TABLE_NAME = os.environ["INSTANCES_TABLE"]

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(TABLE_NAME)
ec2 = boto3.client("ec2")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _find_expired(now: int) -> list[dict]:
    """หา instance ที่หมดเวลา (scan ทั้งตาราง: ข้อมูลน้อย ไม่ต้องมี index เพิ่ม)"""
    items: list[dict] = []
    kwargs = {
        "FilterExpression": (
            "auto_stop = :t AND attribute_exists(expires_at) "
            "AND expires_at <= :now AND #st <> :term"
        ),
        "ExpressionAttributeNames": {"#st": "state"},
        "ExpressionAttributeValues": {":t": True, ":now": now, ":term": "terminated"},
    }
    while True:
        resp = table.scan(**kwargs)
        items.extend(resp.get("Items", []))
        if "LastEvaluatedKey" not in resp:
            return items
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


def _claim(instance_id: str, now: int) -> bool:
    """ลบ expires_at แบบมีเงื่อนไข: True = เราเป็นคนจอง (ยังหมดเวลาอยู่จริง)"""
    try:
        table.update_item(
            Key={"instance_id": instance_id},
            UpdateExpression="REMOVE expires_at SET updated_at = :u",
            ConditionExpression="attribute_exists(expires_at) AND expires_at <= :now",
            ExpressionAttributeValues={":now": now, ":u": _now_iso()},
        )
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return False  # ถูกรีเวลา/หยุดไปก่อนแล้ว
        raise


def _restore_expiry(instance_id: str, expires_at) -> None:
    """stop ไม่สำเร็จ -> คืน expires_at เดิม (ไม่ทับถ้ามีคนตั้งค่าใหม่ไปแล้ว)"""
    try:
        table.update_item(
            Key={"instance_id": instance_id},
            UpdateExpression="SET expires_at = :e",
            ConditionExpression="attribute_not_exists(expires_at)",
            ExpressionAttributeValues={":e": expires_at},
        )
    except ClientError as e:
        if e.response["Error"]["Code"] != "ConditionalCheckFailedException":
            logger.error("restore expires_at failed for %s: %s", instance_id, e)


def _mark_stopping(instance_id: str) -> None:
    """อัปเดต DB ให้ตรงกับที่ backend ทำตอน stop (state + ล้าง public_ip)"""
    table.update_item(
        Key={"instance_id": instance_id},
        UpdateExpression="SET #st = :s, public_ip = :none, updated_at = :u",
        ExpressionAttributeNames={"#st": "state"},
        ExpressionAttributeValues={":s": "stopping", ":none": None, ":u": _now_iso()},
    )


def _ec2_state(instance_id: str):
    """คืนสถานะจริงบน EC2 หรือ None ถ้าหา instance ไม่เจอ"""
    try:
        resp = ec2.describe_instances(InstanceIds=[instance_id])
    except ClientError as e:
        if e.response["Error"]["Code"] in (
            "InvalidInstanceID.NotFound",
            "InvalidInstanceID.Malformed",
        ):
            return None
        raise
    for r in resp.get("Reservations", []):
        for i in r.get("Instances", []):
            return i["State"]["Name"]
    return None


def lambda_handler(event, context):
    now = int(time.time())
    expired = _find_expired(now)
    logger.info("now=%s expired_candidates=%d", now, len(expired))

    stopped, skipped, failed = [], [], []

    for rec in expired:
        iid = rec["instance_id"]
        old_exp = rec.get("expires_at")

        if not _claim(iid, now):
            logger.info("%s: skipped (extended or already handled)", iid)
            skipped.append(iid)
            continue

        try:
            state = _ec2_state(iid)
            if state in ("running", "pending"):
                ec2.stop_instances(InstanceIds=[iid])
                _mark_stopping(iid)
                logger.info(
                    "%s: STOPPED (user=%s name=%s expired_at=%s)",
                    iid, rec.get("user_id"), rec.get("name"), old_exp,
                )
                stopped.append(iid)
            else:
                # หยุด/ลบไปแล้วโดยทางอื่น: แค่ล้างเวลา (claim ทำให้แล้ว)
                logger.info("%s: ec2 state=%s -> nothing to stop", iid, state)
                skipped.append(iid)
        except Exception as e:  # noqa: BLE001
            logger.exception("%s: stop failed: %s", iid, e)
            _restore_expiry(iid, old_exp)  # รอบหน้าลองใหม่
            failed.append(iid)

    result = {"stopped": stopped, "skipped": skipped, "failed": failed}
    logger.info("result=%s", result)
    return result
