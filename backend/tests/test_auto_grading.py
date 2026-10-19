"""
Unit tests for Auto-Grading Engine (Approach 1: Rule-based declarative grading)
"""

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app.models import (
    GradingCheckType,
    GradingConfig,
    TestCase,
)
from app.grading_service import (
    _clean_output,
    _test_vpcs_ping,
    _test_vpcs_show_ip,
    _test_cisco_ping,
    _test_cli_command,
    grade_instance,
)


class TestAutoGradingEngine(unittest.IsolatedAsyncioTestCase):

    def test_clean_output_strips_ansi_and_iac(self):
        # Sample with Telnet IAC bytes (e.g. \xff\xfb\x01) and ANSI escape color codes
        raw = b"\xff\xfb\x01\x1b[32mPC1> \x1b[0mping 8.8.8.8\r\n"
        cleaned = _clean_output(raw)
        self.assertIn("PC1> ping 8.8.8.8", cleaned)
        self.assertNotIn("\x1b", cleaned)
        self.assertNotIn("\xff", cleaned)

    async def test_vpcs_ping_success(self):
        reader = AsyncMock()
        writer = MagicMock()
        mock_output = (
            "PC1> ping 8.8.8.8 -c 3\n"
            "84 bytes from 8.8.8.8 icmp_seq=1 ttl=114 time=24.520 ms\n"
            "84 bytes from 8.8.8.8 icmp_seq=2 ttl=114 time=23.811 ms\n"
            "84 bytes from 8.8.8.8 icmp_seq=3 ttl=114 time=25.102 ms\n"
            "PC1> "
        )

        with patch("app.grading_service._execute_command", return_value=mock_output):
            tc = TestCase(
                id="test_ping_vpcs",
                title="Ping 8.8.8.8 from PC1",
                node="PC1",
                type=GradingCheckType.PING,
                target="8.8.8.8",
                count=3,
                expected="success",
                points=10,
            )
            passed, msg, out = await _test_vpcs_ping(reader, writer, tc, timeout=5.0)
            self.assertTrue(passed)
            self.assertIn("สำเร็จ", msg)
            self.assertIn("3/3 packets", msg)

    async def test_vpcs_ping_timeout(self):
        reader = AsyncMock()
        writer = MagicMock()
        mock_output = (
            "PC1> ping 8.8.8.8 -c 3\n"
            "*8.8.8.8 icmp_seq=1 timeout\n"
            "*8.8.8.8 icmp_seq=2 timeout\n"
            "*8.8.8.8 icmp_seq=3 timeout\n"
            "PC1> "
        )

        with patch("app.grading_service._execute_command", return_value=mock_output):
            tc = TestCase(
                id="test_ping_vpcs_fail",
                title="Ping 8.8.8.8 from PC1",
                node="PC1",
                type=GradingCheckType.PING,
                target="8.8.8.8",
                count=3,
                expected="success",
                points=10,
            )
            passed, msg, out = await _test_vpcs_ping(reader, writer, tc, timeout=5.0)
            self.assertFalse(passed)
            self.assertIn("ล้มเหลว", msg)
            self.assertIn("timed out", msg)

    async def test_vpcs_show_ip_match(self):
        reader = AsyncMock()
        writer = MagicMock()
        mock_output = (
            "PC1> show ip\n"
            "NAME        : PC1[1]\n"
            "IP/MASK     : 192.168.1.10/24\n"
            "GATEWAY     : 192.168.1.1\n"
            "DNS         : 8.8.8.8\n"
            "MAC         : 00:50:79:66:68:00\n"
            "PC1> "
        )

        with patch("app.grading_service._execute_command", return_value=mock_output):
            tc = TestCase(
                id="test_vpcs_ip",
                title="Verify PC1 IP address",
                node="PC1",
                type=GradingCheckType.VPCS_SHOW_IP,
                expected_ip="192.168.1.10",
                expected_mask="24",
                expected_gateway="192.168.1.1",
                points=10,
            )
            passed, msg, out = await _test_vpcs_show_ip(reader, writer, tc, timeout=5.0)
            self.assertTrue(passed)
            self.assertIn("ถูกต้อง", msg)

    async def test_vpcs_show_ip_mismatch_gateway(self):
        reader = AsyncMock()
        writer = MagicMock()
        mock_output = (
            "PC1> show ip\n"
            "NAME        : PC1[1]\n"
            "IP/MASK     : 192.168.1.10/24\n"
            "GATEWAY     : 0.0.0.0\n"
            "PC1> "
        )

        with patch("app.grading_service._execute_command", return_value=mock_output):
            tc = TestCase(
                id="test_vpcs_ip_wrong_gw",
                title="Verify PC1 Gateway",
                node="PC1",
                type=GradingCheckType.VPCS_SHOW_IP,
                expected_ip="192.168.1.10",
                expected_gateway="192.168.1.1",
                points=10,
            )
            passed, msg, out = await _test_vpcs_show_ip(reader, writer, tc, timeout=5.0)
            self.assertFalse(passed)
            self.assertIn("Gateway ไม่ถูกต้อง", msg)

    async def test_cisco_ping_success(self):
        reader = AsyncMock()
        writer = MagicMock()
        mock_output = (
            "R1#ping 8.8.8.8 repeat 5\n"
            "Type escape sequence to abort.\n"
            "Sending 5, 100-byte ICMP Echos to 8.8.8.8, timeout is 2 seconds:\n"
            "!!!!!\n"
            "Success rate is 100 percent (5/5), round-trip min/avg/max = 1/2/4 ms\n"
            "R1#"
        )

        with patch("app.grading_service._execute_command", return_value=mock_output):
            tc = TestCase(
                id="test_cisco_ping",
                title="R1 to Internet",
                node="R1",
                type=GradingCheckType.PING,
                target="8.8.8.8",
                count=5,
                points=15,
            )
            passed, msg, out = await _test_cisco_ping(reader, writer, tc, timeout=5.0)
            self.assertTrue(passed)
            self.assertIn("100%", msg)

    async def test_cli_command_contains(self):
        reader = AsyncMock()
        writer = MagicMock()
        mock_output = (
            "R1#show ip interface brief\n"
            "Interface                  IP-Address      OK? Method Status                Protocol\n"
            "GigabitEthernet0/0         192.168.1.1     YES manual up                    up\n"
            "GigabitEthernet0/1         unassigned      YES unset  administratively down down\n"
            "R1#"
        )

        with patch("app.grading_service._execute_command", return_value=mock_output):
            tc = TestCase(
                id="test_r1_int",
                title="Check R1 Gi0/0 is up",
                node="R1",
                type=GradingCheckType.CLI_COMMAND,
                command="show ip int brief",
                contains=["GigabitEthernet0/0", "192.168.1.1", "up"],
                not_contains=["administratively down"],  # Gi0/0 shouldn't be admin down
                points=10,
            )
            # Gi0/1 has "administratively down" in the overall output snippet, so let's test missing substring
            tc_fail = TestCase(
                id="test_r1_missing",
                title="Check missing route",
                node="R1",
                type=GradingCheckType.CLI_COMMAND,
                command="show ip route",
                contains=["10.0.0.0/24"],
                points=10,
            )
            passed, msg, out = await _test_cli_command(reader, writer, tc_fail, is_cisco=True, timeout=5.0)
            self.assertFalse(passed)
            self.assertIn("ขาดข้อความที่กำหนด: '10.0.0.0/24'", msg)

    async def test_grade_instance_orchestrator(self):
        inst_rec = {
            "instance_id": "i-test123",
            "private_ip": "10.0.1.50",
            "public_ip": "54.200.1.1",
            "gns3_user": "gns3",
            "gns3_password": "secretpassword",
        }

        mock_nodes = {
            "pc1": {"node_id": "node-1", "name": "PC1", "status": "started", "console": 5900, "node_type": "vpcs"},
            "r1": {"node_id": "node-2", "name": "R1", "status": "started", "console": 5901, "node_type": "dynamips"},
        }

        cfg = GradingConfig(
            auto_start_nodes=False,
            timeout_seconds=5,
            test_cases=[
                TestCase(
                    id="t1",
                    title="PC1 Ping Gateway",
                    node="PC1",
                    type=GradingCheckType.PING,
                    target="192.168.1.1",
                    points=10,
                ),
                TestCase(
                    id="t2",
                    title="PC1 Ping 8.8.8.8",
                    node="PC1",
                    type=GradingCheckType.PING,
                    target="8.8.8.8",
                    points=15,
                ),
            ],
        )

        with patch("app.gns3_service.get_project_nodes_map", return_value=("proj-1", mock_nodes)), \
             patch("app.gns3_service.get_vm_target_host", return_value="10.0.1.50"), \
             patch("app.grading_service._run_single_test") as mock_test:

            # Mock first test passed, second test failed
            from app.models import TestCaseResult
            mock_test.side_effect = [
                TestCaseResult(
                    test_id="t1",
                    title="PC1 Ping Gateway",
                    node="PC1",
                    status="PASSED",
                    points_awarded=10,
                    max_points=10,
                    message="Ping gateway succeeded",
                ),
                TestCaseResult(
                    test_id="t2",
                    title="PC1 Ping 8.8.8.8",
                    node="PC1",
                    status="FAILED",
                    points_awarded=0,
                    max_points=15,
                    message="Ping 8.8.8.8 timed out",
                ),
            ]

            report = await grade_instance(inst_rec, cfg, exercise_id="ex-123")
            self.assertEqual(report.total_score, 10)
            self.assertEqual(report.max_score, 25)
            self.assertEqual(report.percentage, 40.0)
            self.assertEqual(report.passed_count, 1)
            self.assertEqual(report.total_count, 2)
            self.assertEqual(len(report.results), 2)


if __name__ == "__main__":
    unittest.main()
