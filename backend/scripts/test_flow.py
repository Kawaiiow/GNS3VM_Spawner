#!/usr/bin/env python3
"""
test_flow.py
------------
Automated verification suite for DynamoDB Users, Instances & Exercises (Reduced Schema):
1. Password hashing (bcrypt) and verification
2. JWT token generation, expiration, and payload decoding with member_id
3. Pydantic model validation (User, Instance, Exercise models)
4. Atomic 1-VM-per-user limit logic and DynamoDB state transitions
5. FastAPI Dependency and API route validation with TestClient
"""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# Ensure backend root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Provide mock environment variables so test suite runs without requiring real .env
os.environ.setdefault("AWS_ACCESS_KEY_ID", "mock_key")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "mock_secret")
os.environ.setdefault("DEFAULT_AMI_ID", "ami-mock")
os.environ.setdefault("DEFAULT_KEY_NAME", "mock_keyname")
os.environ.setdefault("DEFAULT_SECURITY_GROUP_ID", "sg-mock")

from botocore.exceptions import ClientError
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.auth import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from app.main import app
from app.models import (
    ExerciseCreate,
    ExerciseResponse,
    InstanceInfo,
    LaunchInstanceRequest,
    LoginRequest,
    TokenResponse,
    UserCreate,
    UserInDB,
    UserResponse,
    UserRole,
)


class TestAuthAndTokens(unittest.TestCase):
    def test_password_hashing(self):
        password = "mySecretPassword123!"
        hashed = hash_password(password)
        self.assertNotEqual(password, hashed)
        self.assertTrue(verify_password(password, hashed))
        self.assertFalse(verify_password("wrongPassword", hashed))

    def test_jwt_token_flow(self):
        user_data = {
            "sub": "user-uuid-1234",
            "username": "student01",
            "member_id": "6410001",
            "role": "student",
        }
        token = create_access_token(user_data)
        self.assertIsInstance(token, str)

        decoded = decode_access_token(token)
        self.assertEqual(decoded["sub"], "user-uuid-1234")
        self.assertEqual(decoded["username"], "student01")
        self.assertEqual(decoded["member_id"], "6410001")
        self.assertEqual(decoded["role"], "student")


class TestPydanticModels(unittest.TestCase):
    def test_user_models(self):
        user_in = UserCreate(
            username="student_tester",
            member_id="6410099",
            password="testPassword123",
            full_name="Tester Test",
            role=UserRole.STUDENT,
        )
        self.assertEqual(user_in.username, "student_tester")
        self.assertEqual(user_in.member_id, "6410099")

        user_resp = UserResponse(
            user_id="uuid-999",
            username=user_in.username,
            member_id=user_in.member_id,
            full_name=user_in.full_name,
            role=user_in.role,
            active_instance_id=None,
            created_at="2026-09-20T00:00:00Z",
            updated_at="2026-09-20T00:00:00Z",
        )
        self.assertIsNone(user_resp.active_instance_id)
        self.assertEqual(user_resp.member_id, "6410099")

    def test_instance_models(self):
        info = InstanceInfo(
            instance_id="i-0123456789abcdef0",
            user_id="uuid-999",
            exercise_id="ex-101",
            name="test-vm",
            state="running",
            instance_type="t2.micro",
            public_ip="54.200.10.20",
            private_ip="172.31.0.10",
        )
        self.assertEqual(info.instance_id, "i-0123456789abcdef0")
        self.assertEqual(info.state, "running")
        self.assertEqual(info.user_id, "uuid-999")
        self.assertEqual(info.exercise_id, "ex-101")

    def test_exercise_models(self):
        ex = ExerciseResponse(
            exercise_id="ex-101",
            instructor_id="inst-1",
            title="Lab 1: Basic Routing",
            description="Configure OSPF",
            ami_id="ami-123456",
            status="available",
            is_active=True,
            created_at="2026-09-27T00:00:00Z",
        )
        self.assertEqual(ex.title, "Lab 1: Basic Routing")
        self.assertTrue(ex.is_active)


class TestDynamoDBServiceLogic(unittest.TestCase):
    @patch("app.dynamodb_service.get_users_table")
    def test_reserve_user_vm_slot_success(self, mock_get_table):
        mock_table = MagicMock()
        mock_get_table.return_value = mock_table

        from app.dynamodb_service import reserve_user_vm_slot
        reserve_user_vm_slot("user-123")
        mock_table.update_item.assert_called_once()

    @patch("app.dynamodb_service.get_user_by_id")
    @patch("app.dynamodb_service.get_users_table")
    def test_reserve_user_vm_slot_failure_when_active_exists(
        self, mock_get_table, mock_get_user
    ):
        mock_table = MagicMock()
        mock_get_table.return_value = mock_table
        mock_get_user.return_value = {"active_instance_id": "i-existing123"}

        error_response = {
            "Error": {
                "Code": "ConditionalCheckFailedException",
                "Message": "The conditional request failed",
            }
        }
        mock_table.update_item.side_effect = ClientError(
            error_response, "UpdateItem"
        )

        from app.dynamodb_service import reserve_user_vm_slot
        with self.assertRaises(HTTPException) as ctx:
            reserve_user_vm_slot("user-123")

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("already owns an active VM", ctx.exception.detail)

    @patch("app.dynamodb_service.get_users_table")
    def test_assign_and_release_user_vm(self, mock_get_table):
        mock_table = MagicMock()
        mock_get_table.return_value = mock_table

        from app.dynamodb_service import assign_user_vm, release_user_vm
        assign_user_vm("user-123", "i-newvm")
        self.assertEqual(mock_table.update_item.call_count, 1)

        release_user_vm("user-123")
        self.assertEqual(mock_table.update_item.call_count, 2)


class TestFastAPIRoutes(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.test_password = "SecretPass123!"
        self.hashed_pw = hash_password(self.test_password)

        self.mock_student_dict = {
            "user_id": "student-uuid-1",
            "username": "student_test",
            "member_id": "6410001",
            "password_hash": self.hashed_pw,
            "full_name": "Student Test",
            "role": "student",
            "active_instance_id": None,
            "created_at": "2026-09-20T00:00:00Z",
            "updated_at": "2026-09-20T00:00:00Z",
        }

        self.mock_instructor_dict = {
            "user_id": "inst-uuid-1",
            "username": "inst_test",
            "member_id": "INST01",
            "password_hash": self.hashed_pw,
            "full_name": "Instructor Test",
            "role": "instructor",
            "active_instance_id": None,
            "created_at": "2026-09-20T00:00:00Z",
            "updated_at": "2026-09-20T00:00:00Z",
        }

        self.mock_admin_dict = {
            "user_id": "admin-uuid-1",
            "username": "admin_test",
            "member_id": "0000000",
            "password_hash": self.hashed_pw,
            "full_name": "Admin Test",
            "role": "admin",
            "active_instance_id": None,
            "created_at": "2026-09-20T00:00:00Z",
            "updated_at": "2026-09-20T00:00:00Z",
        }

        self.student_token = create_access_token(
            {
                "sub": "student-uuid-1",
                "username": "student_test",
                "member_id": "6410001",
                "role": "student",
            }
        )

        self.instructor_token = create_access_token(
            {
                "sub": "inst-uuid-1",
                "username": "inst_test",
                "member_id": "INST01",
                "role": "instructor",
            }
        )

        self.admin_token = create_access_token(
            {
                "sub": "admin-uuid-1",
                "username": "admin_test",
                "member_id": "0000000",
                "role": "admin",
            }
        )

    def test_health_endpoint(self):
        resp = self.client.get("/health")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "ok")

    @patch("app.main.get_user_by_identifier")
    def test_login_success(self, mock_get_user):
        mock_get_user.return_value = self.mock_student_dict
        resp = self.client.post(
            "/auth/login",
            json={"identifier": "6410001", "password": self.test_password},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("access_token", data)
        self.assertEqual(data["user"]["username"], "student_test")
        self.assertEqual(data["user"]["member_id"], "6410001")
        self.assertIn("access_token", resp.cookies)

    @patch("app.main.get_user_by_identifier")
    def test_login_invalid_password(self, mock_get_user):
        mock_get_user.return_value = self.mock_student_dict
        resp = self.client.post(
            "/auth/login",
            json={"identifier": "student_test", "password": "WrongPassword"},
        )
        self.assertEqual(resp.status_code, 401)

    def test_protected_route_unauthenticated(self):
        resp = self.client.get("/auth/me")
        self.assertEqual(resp.status_code, 401)

    @patch("app.auth.get_user_by_id")
    @patch("app.main.get_user_by_id")
    def test_protected_route_authenticated(self, mock_main_user, mock_auth_user):
        mock_auth_user.return_value = self.mock_student_dict
        mock_main_user.return_value = self.mock_student_dict
        headers = {"Authorization": f"Bearer {self.student_token}"}
        resp = self.client.get("/auth/me", headers=headers)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["user_id"], "student-uuid-1")
        self.assertEqual(resp.json()["member_id"], "6410001")

    @patch("app.auth.get_user_by_id")
    @patch("app.main.ec2_service.launch_instance")
    def test_launch_instance_enforcing_1_vm_limit(
        self, mock_launch_instance, mock_auth_user
    ):
        mock_auth_user.return_value = self.mock_student_dict
        mock_launch_instance.side_effect = HTTPException(
            status_code=400,
            detail="User already owns an active VM instance (i-12345). Every user is limited to 1 active VM.",
        )
        headers = {"Authorization": f"Bearer {self.student_token}"}
        resp = self.client.post(
            "/instances",
            json={"instance_name": "student-vm-2"},
            headers=headers,
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("limited to 1 active VM", resp.json()["detail"])

    @patch("app.auth.get_user_by_id")
    @patch("app.main.get_instance_record")
    def test_ownership_check_prevents_unauthorized_deletion(
        self, mock_get_instance, mock_auth_user
    ):
        mock_auth_user.return_value = self.mock_student_dict
        mock_get_instance.return_value = {
            "instance_id": "i-other123",
            "user_id": "student-uuid-999",
        }

        headers = {"Authorization": f"Bearer {self.student_token}"}
        resp = self.client.delete("/instances/i-other123", headers=headers)
        self.assertEqual(resp.status_code, 403)
        self.assertIn("คุณไม่มีสิทธิ์จัดการ VM ของผู้ใช้อื่น", resp.json()["detail"])

    @patch("app.main.list_all_exercises")
    def test_get_exercises(self, mock_list_exercises):
        mock_list_exercises.return_value = [
            {
                "exercise_id": "ex-1",
                "instructor_id": "inst-1",
                "title": "Lab 1",
                "description": "Lab desc",
                "ami_id": "ami-test",
                "status": "available",
                "is_active": True,
                "created_at": "2026-09-27T00:00:00Z",
            }
        ]
        resp = self.client.get("/exercises")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["exercises"][0]["title"], "Lab 1")

    @patch("app.auth.get_user_by_id")
    @patch("app.main.create_exercise_record")
    def test_create_exercise_by_instructor(self, mock_create_ex, mock_auth_user):
        mock_auth_user.return_value = self.mock_instructor_dict
        mock_create_ex.return_value = {
            "exercise_id": "ex-new",
            "instructor_id": "inst-uuid-1",
            "title": "New Lab",
            "description": "Lab desc",
            "ami_id": "ami-custom",
            "status": "available",
            "is_active": True,
            "created_at": "2026-09-27T00:00:00Z",
        }
        headers = {"Authorization": f"Bearer {self.instructor_token}"}
        resp = self.client.post(
            "/exercises",
            json={"title": "New Lab", "ami_id": "ami-custom"},
            headers=headers,
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()["exercise_id"], "ex-new")

    @patch("app.auth.get_user_by_id")
    @patch("app.main.get_instance_record")
    @patch("app.main.ec2_service.create_instance_image")
    @patch("app.main.create_exercise_record")
    def test_create_exercise_snapshot_from_active_instance(
        self, mock_create_ex, mock_create_img, mock_get_inst, mock_auth_user
    ):
        inst_user = dict(self.mock_instructor_dict)
        inst_user["active_instance_id"] = "i-active-inst-1"
        mock_auth_user.return_value = inst_user
        mock_get_inst.return_value = {
            "instance_id": "i-active-inst-1",
            "user_id": inst_user["user_id"],
        }
        mock_create_img.return_value = "ami-snapshot-ospf"
        mock_create_ex.return_value = {
            "exercise_id": "ex-ospf-1",
            "instructor_id": inst_user["user_id"],
            "title": "Lab OSPF Snapshot",
            "description": "Configured topology",
            "ami_id": "ami-snapshot-ospf",
            "status": "pending",
            "is_active": True,
            "created_at": "2026-10-03T00:00:00Z",
        }

        headers = {"Authorization": f"Bearer {self.instructor_token}"}
        resp = self.client.post(
            "/exercises",
            json={"title": "Lab OSPF Snapshot", "description": "Configured topology"},
            headers=headers,
        )
        self.assertEqual(resp.status_code, 201)
        mock_create_img.assert_called_once()
        self.assertEqual(mock_create_img.call_args[1]["instance_id"], "i-active-inst-1")
        self.assertEqual(resp.json()["ami_id"], "ami-snapshot-ospf")
        self.assertEqual(resp.json()["status"], "pending")

    @patch("app.auth.get_user_by_id")
    def test_create_exercise_fails_without_instance_or_ami(self, mock_auth_user):
        inst_user = dict(self.mock_instructor_dict)
        inst_user["active_instance_id"] = None
        mock_auth_user.return_value = inst_user

        headers = {"Authorization": f"Bearer {self.instructor_token}"}
        resp = self.client.post(
            "/exercises",
            json={"title": "Missing AMI Lab"},
            headers=headers,
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("กรุณาระบุ instance_id", resp.json()["detail"])

    @patch("app.main.get_exercise_record")
    @patch("app.main.ec2_service.get_image_status")
    @patch("app.main.update_exercise_status")
    def test_get_exercise_detail_syncs_status(
        self, mock_update_status, mock_get_status, mock_get_rec
    ):
        mock_get_rec.return_value = {
            "exercise_id": "ex-pending-1",
            "instructor_id": "inst-1",
            "title": "Pending Lab",
            "description": "Desc",
            "ami_id": "ami-pending-1",
            "status": "pending",
            "is_active": True,
            "created_at": "2026-10-03T00:00:00Z",
        }
        mock_get_status.return_value = "available"

        resp = self.client.get("/exercises/ex-pending-1")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "available")
        mock_update_status.assert_called_once_with("ex-pending-1", "available")

    @patch("app.auth.get_user_by_id")
    @patch("app.main.get_exercise_record")
    @patch("app.main.ec2_service.deregister_image")
    @patch("app.main.delete_exercise_record")
    def test_delete_exercise_by_owner(
        self, mock_del_rec, mock_deregister, mock_get_rec, mock_auth_user
    ):
        mock_auth_user.return_value = self.mock_instructor_dict
        mock_get_rec.return_value = {
            "exercise_id": "ex-del-1",
            "instructor_id": "inst-uuid-1",
            "ami_id": "ami-to-del",
        }

        headers = {"Authorization": f"Bearer {self.instructor_token}"}
        resp = self.client.delete("/exercises/ex-del-1", headers=headers)
        self.assertEqual(resp.status_code, 200)
        mock_deregister.assert_called_once_with("ami-to-del")
        mock_del_rec.assert_called_once_with("ex-del-1")

    @patch("app.auth.get_user_by_id")
    @patch("app.main.get_exercise_record")
    def test_delete_exercise_forbidden_for_other_user(
        self, mock_get_rec, mock_auth_user
    ):
        mock_auth_user.return_value = self.mock_instructor_dict
        mock_get_rec.return_value = {
            "exercise_id": "ex-other",
            "instructor_id": "inst-other-999",
            "ami_id": "ami-other",
        }

        headers = {"Authorization": f"Bearer {self.instructor_token}"}
        resp = self.client.delete("/exercises/ex-other", headers=headers)
        self.assertEqual(resp.status_code, 403)
        self.assertIn("คุณไม่มีสิทธิ์ลบแบบฝึกหัด", resp.json()["detail"])


if __name__ == "__main__":
    print("[*] Running NetLab DynamoDB (Reduced Schema) Verification Test Suite...")
    unittest.main(verbosity=2)
