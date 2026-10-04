#!/usr/bin/env python3
"""
init_dynamodb.py
----------------
สร้าง/ตรวจสอบ DynamoDB Tables สำหรับ NetLab (Reduced Schema) รันซ้ำได้ปลอดภัย:
1. netlab_users:     PK user_id        | GSI: UsernameIndex (username), MemberIdIndex (member_id)
2. netlab_instances: PK instance_id    | GSI: UserIdIndex (user_id)
3. netlab_exercises: PK exercise_id    | GSI: InstructorIdIndex (instructor_id)

พฤติกรรม:
  - ตารางยังไม่มี            -> สร้างพร้อม GSI
  - ตารางมี แต่ขาด GSI       -> เพิ่ม GSI ให้ (ข้อมูลเดิมไม่หาย)
  - ตารางมี แต่ PK ไม่ตรง    -> แจ้งเตือน (ใช้ --recreate-mismatched เพื่อลบแล้วสร้างใหม่)
  - --seed                   -> สร้างบัญชีทดสอบ admin / instructor / student (รหัสผ่าน test1234)

ใช้ BillingMode = PAY_PER_REQUEST (On-Demand)

วิธีใช้ (รันจากโฟลเดอร์ backend):
    python scripts/init_dynamodb.py
    python scripts/init_dynamodb.py --seed
"""

import argparse
import os
import sys
import time

# Ensure backend root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from botocore.exceptions import ClientError

from app.config import get_settings
from app.dynamodb_service import get_dynamodb_client


def table_specs(settings):
    return [
        {
            "name": settings.users_table_name,
            "pk": "user_id",
            "gsis": {"UsernameIndex": "username", "MemberIdIndex": "member_id"},
        },
        {
            "name": settings.instances_table_name,
            "pk": "instance_id",
            "gsis": {"UserIdIndex": "user_id"},
        },
        {
            "name": settings.exercises_table_name,
            "pk": "exercise_id",
            "gsis": {"InstructorIdIndex": "instructor_id"},
        },
    ]


def gsi_def(index_name: str, attr: str) -> dict:
    return {
        "IndexName": index_name,
        "KeySchema": [{"AttributeName": attr, "KeyType": "HASH"}],
        "Projection": {"ProjectionType": "ALL"},
    }


def wait_for_active(client, table_name: str, timeout: int = 600):
    """รอให้ตารางและ GSI ทุกตัวเป็น ACTIVE"""
    print(f"    waiting for '{table_name}' (table + indexes) to become ACTIVE...")
    start = time.time()
    while time.time() - start < timeout:
        try:
            t = client.describe_table(TableName=table_name)["Table"]
            gsis = t.get("GlobalSecondaryIndexes", [])
            if t["TableStatus"] == "ACTIVE" and all(
                g["IndexStatus"] == "ACTIVE" for g in gsis
            ):
                print(f"[+] '{table_name}' is ACTIVE.")
                return
        except ClientError:
            pass
        time.sleep(3)
    print(f"[!] Warning: '{table_name}' not fully ACTIVE within {timeout}s.")


def create_table(client, spec: dict):
    attrs = {spec["pk"]} | set(spec["gsis"].values())
    print(f"[*] Creating table '{spec['name']}'...")
    client.create_table(
        TableName=spec["name"],
        KeySchema=[{"AttributeName": spec["pk"], "KeyType": "HASH"}],
        AttributeDefinitions=[
            {"AttributeName": a, "AttributeType": "S"} for a in sorted(attrs)
        ],
        GlobalSecondaryIndexes=[gsi_def(n, a) for n, a in spec["gsis"].items()],
        BillingMode="PAY_PER_REQUEST",
    )
    wait_for_active(client, spec["name"])


def ensure_table(client, spec: dict, recreate_mismatched: bool):
    name = spec["name"]
    print(f"[*] Checking table: {name}...")

    try:
        desc = client.describe_table(TableName=name)["Table"]
    except ClientError as e:
        if e.response["Error"]["Code"] != "ResourceNotFoundException":
            print(f"[-] Error describing table '{name}': {e}")
            raise
        create_table(client, spec)
        return

    # 1) ตรวจ primary key
    actual_pk = desc["KeySchema"][0]["AttributeName"]
    if actual_pk != spec["pk"]:
        print(f"[!] '{name}' has primary key '{actual_pk}' but code expects '{spec['pk']}'.")
        if not recreate_mismatched:
            print("    Re-run with --recreate-mismatched to DELETE and recreate it (data is lost).")
            return
        print("    Deleting and recreating...")
        client.delete_table(TableName=name)
        client.get_waiter("table_not_exists").wait(TableName=name)
        create_table(client, spec)
        return

    # 2) ตรวจ GSI ที่ขาด (DynamoDB เพิ่มได้ทีละตัว ต้องรอ ACTIVE ก่อนตัวถัดไป)
    existing = {g["IndexName"] for g in desc.get("GlobalSecondaryIndexes", [])}
    missing = {n: a for n, a in spec["gsis"].items() if n not in existing}
    if not missing:
        print(f"[+] '{name}' OK (key and indexes correct).")
        return

    for idx_name, attr in missing.items():
        print(f"[*] Adding missing index '{idx_name}' to '{name}'...")
        client.update_table(
            TableName=name,
            AttributeDefinitions=[{"AttributeName": attr, "AttributeType": "S"}],
            GlobalSecondaryIndexUpdates=[{"Create": gsi_def(idx_name, attr)}],
        )
        wait_for_active(client, name)


def seed_users():
    # import ที่นี่ เพราะต้องใช้เมื่อ --seed เท่านั้น และตารางต้องพร้อมแล้ว
    from app.auth import hash_password
    from app.dynamodb_service import (
        create_user,
        get_user_by_member_id,
        get_user_by_username,
    )

    # Password can be overridden via SEED_PASSWORD env var (default: test1234)
    seed_password = os.environ.get("SEED_PASSWORD", "test1234")

    # Only seed the admin account — admin can create instructor/student via the API
    username, member_id, role, full_name = "admin", "ADMIN01", "admin", "Admin"

    print(f"[*] Seeding admin account (username: {username}, password: {seed_password})")
    if get_user_by_username(username) or get_user_by_member_id(member_id):
        print(f"    skip {username} (already exists)")
        return
    create_user(
        username=username,
        member_id=member_id,
        password_hash=hash_password(seed_password),
        role=role,
        full_name=full_name,
    )
    print(f"    created {username} ({role})")


def main():
    parser = argparse.ArgumentParser(description="Initialize DynamoDB tables for NetLab")
    parser.add_argument("--seed", action="store_true",
                        help="สร้างบัญชีทดสอบ admin / instructor / student")
    parser.add_argument("--recreate-mismatched", action="store_true",
                        help="ถ้า primary key ไม่ตรง ให้ลบตารางแล้วสร้างใหม่ (ข้อมูลหาย)")
    args = parser.parse_args()

    settings = get_settings()
    client = get_dynamodb_client()

    print("========================================")
    print("NetLab DynamoDB Initializer (Reduced Schema)")
    print(f"Region: {settings.aws_region}")
    print(f"Users Table: {settings.users_table_name}")
    print(f"Instances Table: {settings.instances_table_name}")
    print(f"Exercises Table: {settings.exercises_table_name}")
    print("========================================")

    for spec in table_specs(settings):
        ensure_table(client, spec, args.recreate_mismatched)

    if args.seed:
        seed_users()

    print("\n[✔] DynamoDB tables initialization complete!")


if __name__ == "__main__":
    main()