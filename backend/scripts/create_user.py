#!/usr/bin/env python3
"""
create_user.py
--------------
CLI สคริปต์สำหรับสร้างบัญชีผู้ใช้ (Admin, Instructor, หรือ Student)
และบันทึกข้อมูลลงใน DynamoDB (netlab_users)
"""

import argparse
import os
import sys

# Ensure backend root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.auth import hash_password
from app.dynamodb_service import create_user, get_user_by_student_id, get_user_by_username


def main():
    parser = argparse.ArgumentParser(
        description="สร้างบัญชีผู้ใช้ใหม่สำหรับ NetLab Cloud (บันทึกใน DynamoDB)"
    )
    parser.add_argument(
        "-u", "--username", required=True, help="ชื่อผู้ใช้สำหรับเข้าสู่ระบบ (เช่น admin, student01)"
    )
    parser.add_argument(
        "-s", "--student-id", required=True, help="รหัสนักศึกษา หรือ รหัสประจำตัว (เช่น 6410001, 0000000)"
    )
    parser.add_argument(
        "-p", "--password", required=True, help="รหัสผ่านสำหรับเข้าสู่ระบบ"
    )
    parser.add_argument(
        "-r",
        "--role",
        choices=["student", "instructor", "admin"],
        default="student",
        help="บทบาทผู้ใช้: student (default), instructor, admin",
    )
    parser.add_argument(
        "-n", "--name", default=None, help="ชื่อ-นามสกุลจริงของผู้ใช้"
    )

    args = parser.parse_args()

    print(f"[*] Checking existing user with username: '{args.username}' or student_id: '{args.student_id}'...")
    if get_user_by_username(args.username):
        print(f"[-] Error: Username '{args.username}' already exists.")
        sys.exit(1)
    if get_user_by_student_id(args.student_id):
        print(f"[-] Error: Student ID '{args.student_id}' already exists.")
        sys.exit(1)

    print(f"[*] Hashing password and creating user item...")
    hashed = hash_password(args.password)
    user_item = create_user(
        username=args.username,
        student_id=args.student_id,
        password_hash=hashed,
        role=args.role,
        full_name=args.name,
    )

    print("\n[✔] User created successfully!")
    print(f"    User ID   : {user_item['user_id']}")
    print(f"    Username  : {user_item['username']}")
    print(f"    Student ID: {user_item['student_id']}")
    print(f"    Role      : {user_item['role']}")
    print(f"    Full Name : {user_item.get('full_name') or '-'}")
    print(f"    Created At: {user_item['created_at']}")


if __name__ == "__main__":
    main()
