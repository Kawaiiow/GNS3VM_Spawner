#!/usr/bin/env python3
"""
Unit tests for backend/app/grader_service.py
Tests rubric YAML compilation, validation, and feedback filtering modes.
"""

import os
import sys
import unittest

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, BACKEND_DIR)

from app import grader_service
from fastapi import HTTPException


class TestGraderService(unittest.TestCase):

    def test_validate_and_compile_valid_rubric(self):
        yaml_content = """
version: "1.0"
title: "Lab 1: Static Route"
max_score: 50
passing_score: 30
feedback_mode: "detailed"
tasks:
  - id: "t1"
    name: "R1 Config"
    node: "R1"
    points: 25
    checks:
      - type: "config_regex"
        pattern: "interface GigabitEthernet0/0"
        hint: "Configure Gi0/0"
  - id: "t2"
    name: "Ping test"
    node: "R1"
    points: 25
    checks:
      - type: "ping"
        target_ip: "10.0.0.2"
        min_success_rate: 60
"""
        rubric_dict, compiled_json = grader_service.validate_and_compile_rubric(yaml_content)
        self.assertEqual(rubric_dict["title"], "Lab 1: Static Route")
        self.assertEqual(rubric_dict["max_score"], 50)
        self.assertEqual(len(rubric_dict["tasks"]), 2)
        self.assertIn('"max_score": 50', compiled_json)

    def test_validate_invalid_rubric_schema(self):
        # Missing required 'node' and 'points'
        invalid_yaml = """
version: "1.0"
tasks:
  - id: "t1"
    name: "Missing fields"
"""
        with self.assertRaises(HTTPException) as ctx:
            grader_service.validate_and_compile_rubric(invalid_yaml)
        self.assertEqual(ctx.exception.status_code, 422)

    def test_filter_feedback_detailed(self):
        raw_report = {
            "status": "success",
            "score": 100,
            "tasks": [
                {
                    "id": "t1",
                    "points": 50,
                    "checks": [{"type": "config_regex", "passed": True, "description": "Check Gi0/0"}],
                }
            ],
        }
        res = grader_service._filter_feedback(raw_report, "detailed")
        self.assertIn("checks", res["tasks"][0])

    def test_filter_feedback_score_only(self):
        raw_report = {
            "status": "success",
            "score": 50,
            "tasks": [
                {
                    "id": "t1",
                    "points": 50,
                    "checks": [{"type": "config_regex", "passed": True, "description": "Secret regex"}],
                }
            ],
        }
        res = grader_service._filter_feedback(raw_report, "score_only")
        self.assertNotIn("checks", res["tasks"][0])
        self.assertEqual(res["tasks"][0]["points"], 50)

    def test_filter_feedback_checklist_only(self):
        raw_report = {
            "status": "success",
            "score": 25,
            "tasks": [
                {
                    "id": "t1",
                    "points": 0,
                    "checks": [
                        {
                            "type": "command_output",
                            "passed": False,
                            "description": "Verify route",
                            "hint": "Add static route",
                            "message": "Missing: 192.168.2.0/24",
                        }
                    ],
                }
            ],
        }
        res = grader_service._filter_feedback(raw_report, "checklist_only")
        checks = res["tasks"][0]["checks"]
        self.assertEqual(len(checks), 1)
        self.assertEqual(checks[0]["hint"], "Add static route")
        # Internal regex failure message is stripped
        self.assertNotIn("message", checks[0])


if __name__ == "__main__":
    unittest.main()
