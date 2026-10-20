#!/usr/bin/env python3
"""
Unit tests for backend/grader/runner.py
Tests Telnet IAC handling, prompt stripping, regex matching, ping parsing, and fail-fast checks.
"""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# Add backend and grader directory to path
BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, BACKEND_DIR)
sys.path.insert(0, os.path.join(BACKEND_DIR, "grader"))

from runner import (
    CiscoIOSDriver,
    GraderEngine,
    LinuxDriver,
    TelnetConsole,
)


class MockTelnetConsole:
    def __init__(self, responses=None):
        self.responses = responses or []
        self.sent_lines = []

    def send_line(self, line: str):
        self.sent_lines.append(line)

    def read_until_regex(self, patterns, timeout=None):
        if self.responses:
            return self.responses.pop(0)
        return ("", -1)

    def close(self):
        pass


class TestGraderRunner(unittest.TestCase):

    def test_iac_negotiation(self):
        """Test RFC 854 IAC sequence handling"""
        console = TelnetConsole.__new__(TelnetConsole)
        console.sock = MagicMock()

        # Data with IAC WILL ECHO (255, 251, 1) and IAC DO SGA (255, 253, 3) followed by "Hello"
        raw_data = bytes([255, 251, 1, 255, 253, 3]) + b"Hello World"
        cleaned = console._negotiate_iac(raw_data)
        self.assertEqual(cleaned, b"Hello World")

        # Verify sent negotiation responses
        calls = console.sock.sendall.call_args_list
        # WILL -> DONT (255, 254, 1)
        # DO -> WONT (255, 252, 3)
        self.assertEqual(calls[0][0][0], bytes([255, 254, 1]))
        self.assertEqual(calls[1][0][0], bytes([255, 252, 3]))

    def test_cisco_driver_run_command(self):
        mock_console = MockTelnetConsole([
            ("show ip int brief\nInterface  IP-Address  OK? Method Status  Protocol\nGi0/0      192.168.1.1 YES manual up      up\nR1#", 0)
        ])
        driver = CiscoIOSDriver(mock_console)
        output = driver.run_command("show ip int brief")
        self.assertIn("192.168.1.1", output)
        self.assertNotIn("show ip int brief", output)
        self.assertNotIn("R1#", output)

    def test_linux_driver_run_command(self):
        mock_console = MockTelnetConsole([
            ("ip addr\n1: lo: <LOOPBACK> ...\n2: eth0: <BROADCAST> inet 192.168.2.10/24\nroot@alpine:~# ", 0)
        ])
        driver = LinuxDriver(mock_console)
        output = driver.run_command("ip addr")
        self.assertIn("192.168.2.10", output)
        self.assertNotIn("root@alpine:~#", output)

    def test_fail_fast_stopped_nodes(self):
        rubric = {
            "tasks": [
                {"id": "t1", "name": "Task 1", "node": "R1", "points": 10, "checks": []},
                {"id": "t2", "name": "Task 2", "node": "R2", "points": 10, "checks": []},
            ]
        }
        nodes = [
            {"name": "R1", "status": "started", "console": 5000},
            {"name": "R2", "status": "stopped", "console": 5001},
        ]
        engine = GraderEngine(rubric, nodes)
        val = engine.validate_node_states()
        self.assertIsNotNone(val)
        self.assertEqual(val["status"], "error")
        self.assertEqual(val["error_code"], "NODES_NOT_RUNNING")
        self.assertIn("R2", val["stopped_nodes"])

    def test_fail_fast_missing_nodes(self):
        rubric = {
            "tasks": [
                {"id": "t1", "name": "Task 1", "node": "SW1", "points": 10, "checks": []},
            ]
        }
        nodes = [
            {"name": "R1", "status": "started", "console": 5000},
        ]
        engine = GraderEngine(rubric, nodes)
        val = engine.validate_node_states()
        self.assertIsNotNone(val)
        self.assertEqual(val["status"], "error")
        self.assertIn("SW1", val["missing_nodes"])

    def test_config_regex_check(self):
        engine = GraderEngine({}, [])
        mock_driver = MagicMock()
        mock_driver.run_command.return_value = """
hostname R1
!
interface GigabitEthernet0/0
 ip address 192.168.1.1 255.255.255.0
 duplex auto
 speed auto
!
interface GigabitEthernet0/1
 no ip address
 shutdown
"""
        # 1. Matching pattern
        check1 = {
            "type": "config_regex",
            "pattern": r"interface GigabitEthernet0/0\s+ip address 192\.168\.1\.1 255\.255\.255\.0",
        }
        res1 = engine.evaluate_check(check1, "R1", mock_driver)
        self.assertTrue(res1["passed"])

        # 2. Non-matching pattern
        check2 = {
            "type": "config_regex",
            "pattern": r"interface GigabitEthernet0/0\s+ip address 10\.0\.0\.1",
        }
        res2 = engine.evaluate_check(check2, "R1", mock_driver)
        self.assertFalse(res2["passed"])

        # 3. Negative pattern (must NOT match)
        check3 = {
            "type": "config_regex",
            "pattern": r"ip address 10\.0\.0\.1",
            "negative": True,
        }
        res3 = engine.evaluate_check(check3, "R1", mock_driver)
        self.assertTrue(res3["passed"])

    def test_command_output_check(self):
        engine = GraderEngine({}, [])
        mock_driver = MagicMock()
        mock_driver.run_command.return_value = """
Codes: L - local, C - connected, S - static, R - RIP, M - mobile, B - BGP
Gateway of last resort is not set

      192.168.1.0/24 is variably subnetted, 2 subnets, 2 masks
C        192.168.1.0/24 is directly connected, GigabitEthernet0/0
S     192.168.2.0/24 [1/0] via 10.0.0.2
"""
        check = {
            "type": "command_output",
            "command": "show ip route",
            "must_contain": [r"192\.168\.2\.0/24", r"via 10\.0\.0\.2"],
            "must_not_contain": [r"OSPF"],
        }
        res = engine.evaluate_check(check, "R1", mock_driver)
        self.assertTrue(res["passed"])

    def test_ping_check_cisco(self):
        engine = GraderEngine({}, [])
        mock_driver = MagicMock(spec=CiscoIOSDriver)
        mock_driver.run_command.return_value = """
Type escape sequence to abort.
Sending 5, 100-byte ICMP Echos to 10.0.0.2, timeout is 2 seconds:
.!!!!
Success rate is 80 percent (4/5), round-trip min/avg/max = 1/2/4 ms
"""
        check = {
            "type": "ping",
            "target_ip": "10.0.0.2",
            "min_success_rate": 60,
        }
        res = engine.evaluate_check(check, "R1", mock_driver)
        self.assertTrue(res["passed"])
        self.assertIn("80", res["details"])


if __name__ == "__main__":
    unittest.main()
