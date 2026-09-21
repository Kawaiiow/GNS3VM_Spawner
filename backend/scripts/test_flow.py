#!/usr/bin/env python3
"""
test_flow.py
------------
Automated verification suite for DynamoDB Users & Instances service:
1. Password hashing (bcrypt) and verification
2. JWT token generation, expiration, and payload decoding
3. Pydantic model validation (User, Instance, Auth models)
4. Atomic 1-VM-per-user limit logic and DynamoDB state transitions
5. FastAPI Dependency and API route validation with TestClient
"""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# Ensure backend root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

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
            "student_id": "6410001",
            "role": "student",
        }
        token = create_access_token(user_data)
        self.assertIsInstance(token, str)

        decoded = decode_access_token(token)
        self.assertEqual(decoded["sub"], "user-uuid-1234")
        self.assertEqual(decoded["username"], "student01")
        self.assertEqual(decoded["student_id"], "6410001")
        self.assertEqual(decoded["role"], "student")


class TestPydanticModels(unittest.TestCase):
    def test_user_models(self):
        user_in = UserCreate(
            username="student_tester",
            student_id="6410099",
            password="testPassword123",
            full_name="Tester Test",
            role=UserRole.STUDENT,
        )
        self.assertEqual(user_in.username, "student_tester")

        user_resp = UserResponse(
            user_id="uuid-999",
            username=user_in.username,
            student_id=user_in.student_id,
            full_name=user_in.full_name,
            role=user_in.role,
            active_instance_id=None,
            created_at="2026-09-20T00:00:00Z",
            updated_at="2026-09-20T00:00:00Z",
        )
        self.assertIsNone(user_resp.active_instance_id)

    def test_instance_models(self):
        info = InstanceInfo(
            instance_id="i-0123456789abcdef0",
            name="test-vm",
            state="running",
            instance_type="t2.micro",
            public_ip="54.200.10.20",
            private_ip="172.31.0.10",
            student_id="6410099",
            user_id="uuid-999",
        )
        self.assertEqual(info.instance_id, "i-0123456789abcdef0")
        self.assertEqual(info.state, "running")


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
            "student_id": "6410001",
            "password_hash": self.hashed_pw,
            "full_name": "Student Test",
            "role": "student",
            "active_instance_id": None,
            "created_at": "2026-09-20T00:00:00Z",
            "updated_at": "2026-09-20T00:00:00Z",
        }

        self.mock_admin_dict = {
            "user_id": "admin-uuid-1",
            "username": "admin_test",
            "student_id": "0000000",
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
                "student_id": "6410001",
                "role": "student",
            }
        )

        self.admin_token = create_access_token(
            {
                "sub": "admin-uuid-1",
                "username": "admin_test",
                "student_id": "0000000",
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
            json={"identifier": "student_test", "password": self.test_password},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("access_token", data)
        self.assertEqual(data["user"]["username"], "student_test")
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

    @patch("app.auth.get_user_by_id")
    @patch("app.main.ec2_service.launch_instance")
    def test_launch_instance_enforcing_1_vm_limit(
        self, mock_launch_instance, mock_auth_user
    ):
        mock_auth_user.return_value = self.mock_student_dict
        # Simulate 1-VM limit violation raised from ec2_service
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
        # Current user is student-uuid-1
        mock_auth_user.return_value = self.mock_student_dict
        # Instance belongs to a different student: student-uuid-999
        mock_get_instance.return_value = {
            "instance_id": "i-other123",
            "user_id": "student-uuid-999",
        }

        headers = {"Authorization": f"Bearer {self.student_token}"}
        resp = self.client.delete("/instances/i-other123", headers=headers)
        self.assertEqual(resp.status_code, 403)
        self.assertIn("คุณไม่มีสิทธิ์จัดการ VM ของผู้ใช้อื่น", resp.json()["detail"])


if __name__ == "__main__":
    print("[*] Running NetLab DynamoDB & API Verification Test Suite...")
    unittest.main(verbosity=2)
