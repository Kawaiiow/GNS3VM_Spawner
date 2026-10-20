"""
grader_service.py
-----------------
Orchestrates automated grading sessions for student GNS3 EC2 VMs.
Handles:
  1. Rubric validation (YAML/JSON) & S3 persistence
  2. AWS SSM Run Command dispatch to student VM
  3. Polling and parsing of runner.py execution output
  4. Attempt policy enforcement and DynamoDB persistence
  5. Feedback filtering based on exercise visibility mode
"""

import json
import os
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

import boto3
from botocore.exceptions import ClientError
from fastapi import HTTPException, status
import yaml

from app import dynamodb_service, s3_service
from app.config import get_settings
from app.models import RubricDefinition


def _ssm_client():
    settings = get_settings()
    kwargs = dict(region_name=settings.aws_region)
    if settings.aws_access_key_id and settings.aws_secret_access_key:
        kwargs["aws_access_key_id"] = settings.aws_access_key_id
        kwargs["aws_secret_access_key"] = settings.aws_secret_access_key
        if settings.aws_session_token:
            kwargs["aws_session_token"] = settings.aws_session_token
    return boto3.client("ssm", **kwargs)


# ==========================================
# RUBRIC MANAGEMENT & COMPILATION
# ==========================================

def validate_and_compile_rubric(content: str) -> Tuple[dict, str]:
    """
    Parse YAML or JSON rubric content, validate against RubricDefinition,
    and return (rubric_dict, compiled_json_string).
    """
    try:
        data = yaml.safe_load(content)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid YAML/JSON syntax: {e}",
        )

    if not isinstance(data, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Rubric content must be a dictionary/object.",
        )

    try:
        validated = RubricDefinition(**data)
    except Exception as e:
        raise HTTPException(
            status_code=422,
            detail=f"Rubric validation error: {e}",
        )

    rubric_dict = validated.model_dump()
    compiled_json = json.dumps(rubric_dict, ensure_ascii=False, indent=2)
    return rubric_dict, compiled_json


def save_exercise_rubric(
    exercise_id: str,
    rubric_content: str,
    max_attempts: Optional[int] = None,
    keep_score_policy: Optional[str] = None,
    feedback_mode: Optional[str] = None,
    passing_score: Optional[int] = None,
) -> dict:
    """Validate rubric, upload compiled JSON to S3, and update exercise in DynamoDB."""
    rubric_dict, compiled_json = validate_and_compile_rubric(rubric_content)
    s3_key = s3_service.build_rubric_key(exercise_id)

    # Save to S3
    s3_service.put_text(compiled_json, s3_key, content_type="application/json")

    # Update DynamoDB exercise record
    fields: dict[str, Any] = {
        "has_grading": True,
        "rubric_s3_key": s3_key,
        "passing_score": passing_score if passing_score is not None else rubric_dict.get("passing_score", 60),
        "feedback_mode": feedback_mode or rubric_dict.get("feedback_mode", "detailed"),
    }
    if max_attempts is not None:
        fields["max_attempts"] = max_attempts
    if keep_score_policy is not None:
        fields["keep_score_policy"] = keep_score_policy

    dynamodb_service.update_exercise_fields(exercise_id, fields)
    return {
        "exercise_id": exercise_id,
        "rubric_s3_key": s3_key,
        "tasks_count": len(rubric_dict.get("tasks", [])),
        "max_score": rubric_dict.get("max_score", 100),
        "passing_score": fields["passing_score"],
        "feedback_mode": fields["feedback_mode"],
    }


def get_exercise_rubric(exercise_id: str) -> dict:
    """Fetch and return the parsed rubric for an exercise."""
    rec = dynamodb_service.get_exercise_record(exercise_id)
    if not rec:
        raise HTTPException(status_code=404, detail=f"Exercise '{exercise_id}' not found.")

    rubric_key = rec.get("rubric_s3_key")
    if not rubric_key or not s3_service.object_exists(rubric_key):
        raise HTTPException(
            status_code=404,
            detail=f"Exercise '{exercise_id}' does not have a grading rubric configured.",
        )

    raw_bytes = s3_service.get_bytes(rubric_key)
    try:
        return json.loads(raw_bytes.decode("utf-8"))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error parsing stored rubric: {e}")


# ==========================================
# RUNNER DEPLOYMENT & SSM DISPATCH
# ==========================================

def _ensure_runner_uploaded() -> str:
    """
    Ensure backend/grader/runner.py is uploaded to S3 at _system/grader/runner.py.
    Returns S3 key.
    """
    runner_key = s3_service.build_runner_key()
    local_runner_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "grader", "runner.py")
    )
    if not os.path.exists(local_runner_path):
        raise HTTPException(status_code=500, detail="Local runner.py script not found.")

    with open(local_runner_path, "rb") as f:
        s3_service.put_bytes(f.read(), runner_key, content_type="text/x-python")
    return runner_key


def _filter_feedback(report: dict, feedback_mode: str) -> dict:
    """
    Filter results based on the exercise's configured feedback visibility:
      - 'detailed': include all check details, hints, and error outputs
      - 'checklist_only': include task pass/fail and names, but mask internal regex/details
      - 'score_only': mask individual check items, return score and task statuses
    """
    if feedback_mode == "detailed":
        return report

    report_copy = dict(report)
    tasks = report_copy.get("tasks", [])
    filtered_tasks = []

    for t in tasks:
        t_copy = dict(t)
        if feedback_mode == "score_only":
            t_copy.pop("checks", None)
        elif feedback_mode == "checklist_only":
            checks = t_copy.get("checks", [])
            sanitized_checks = []
            for c in checks:
                sanitized_checks.append({
                    "type": c.get("type"),
                    "passed": c.get("passed"),
                    "description": c.get("description"),
                    "hint": c.get("hint") if not c.get("passed") else "",
                })
            t_copy["checks"] = sanitized_checks
        filtered_tasks.append(t_copy)

    report_copy["tasks"] = filtered_tasks
    return report_copy


def run_grading_session(
    instance_id: str,
    current_user: dict,
    mode: str = "practice",
) -> dict:
    """
    Execute grading session inside student's VM via AWS SSM Run Command.
    """
    settings = get_settings()

    # 1. Verify instance status
    instance_rec = dynamodb_service.get_instance_record(instance_id)
    if not instance_rec:
        raise HTTPException(status_code=404, detail=f"Instance '{instance_id}' not found.")

    # Authorization: Owner or Instructor or Admin
    is_owner = instance_rec.get("user_id") == current_user["user_id"]
    is_staff = current_user.get("role") in ("instructor", "admin")
    if not is_owner and not is_staff:
        raise HTTPException(status_code=403, detail="You do not have permission to grade this instance.")

    if instance_rec.get("state") != "running":
        raise HTTPException(
            status_code=400,
            detail=f"VM must be in 'running' state to run grading (current state: {instance_rec.get('state')}).",
        )

    # 2. Verify exercise association
    exercise_id = instance_rec.get("exercise_id")
    if not exercise_id:
        raise HTTPException(
            status_code=400,
            detail="This instance is a Sandbox VM and is not associated with an exercise.",
        )

    exercise_rec = dynamodb_service.get_exercise_record(exercise_id)
    if not exercise_rec:
        raise HTTPException(status_code=404, detail=f"Exercise '{exercise_id}' not found.")

    rubric_key = exercise_rec.get("rubric_s3_key")
    if not rubric_key or not s3_service.object_exists(rubric_key):
        raise HTTPException(
            status_code=400,
            detail="This exercise does not have an automated grading rubric configured.",
        )

    # 3. Check attempt limit if submitting
    user_id = current_user["user_id"]
    max_attempts = int(exercise_rec.get("max_attempts") or 0)
    current_attempts = dynamodb_service.count_user_exercise_attempts(user_id, exercise_id)

    if mode == "submit" and max_attempts > 0 and current_attempts >= max_attempts:
        raise HTTPException(
            status_code=400,
            detail=f"You have reached the maximum allowed submission attempts ({max_attempts}) for this exercise.",
        )

    # 4. Prepare runner & rubric presigned URLs
    runner_key = _ensure_runner_uploaded()
    runner_url = s3_service.presign_get(runner_key, expires=600)
    rubric_url = s3_service.presign_get(rubric_key, expires=600)

    # 5. Build SSM bash command
    commands = [
        "#!/bin/bash",
        "mkdir -p /opt/netlab/grader",
        f'curl -fsSL --retry 2 -o /opt/netlab/grader/runner.py "{runner_url}"',
        f'python3 /opt/netlab/grader/runner.py --rubric-url "{rubric_url}" --mode "{mode}"',
    ]

    ssm = _ssm_client()
    try:
        resp = ssm.send_command(
            InstanceIds=[instance_id],
            DocumentName="AWS-RunShellScript",
            Parameters={
                "commands": commands,
                "executionTimeout": [str(settings.grader_timeout_seconds)],
            },
        )
    except ClientError as e:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to dispatch SSM command to VM: {e.response['Error']['Message']}",
        )

    cmd_id = resp["Command"]["CommandId"]

    # 6. Poll SSM Invocation
    deadline = time.time() + settings.grader_timeout_seconds
    inv: dict = {}
    while time.time() < deadline:
        time.sleep(2.5)
        try:
            inv = ssm.get_command_invocation(CommandId=cmd_id, InstanceId=instance_id)
        except ClientError as e:
            if e.response["Error"]["Code"] == "InvocationDoesNotExist":
                continue
            raise HTTPException(
                status_code=502,
                detail=f"Error checking SSM command status: {e.response['Error']['Message']}",
            )

        inv_status = inv.get("Status")
        if inv_status in ("Success", "Failed", "Cancelled", "TimedOut"):
            break
    else:
        raise HTTPException(
            status_code=504,
            detail="Grading session timed out. Virtual devices may be slow or booting.",
        )

    # 7. Parse runner output
    stdout = inv.get("StandardOutputContent", "").strip()
    stderr = inv.get("StandardErrorContent", "").strip()

    if not stdout:
        raise HTTPException(
            status_code=502,
            detail=f"Grader runner produced no output. Status: {inv.get('Status')} | Error: {stderr[:300]}",
        )

    try:
        parsed_result = json.loads(stdout)
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to parse grader runner output as JSON. Raw stdout: {stdout[:300]}",
        )

    # Handle fail-fast or runner errors returned inside JSON
    if parsed_result.get("status") == "error":
        return {
            "status": "error",
            "score": 0,
            "max_score": exercise_rec.get("max_score", 100),
            "percentage": 0.0,
            "passed": False,
            "mode": mode,
            "error_code": parsed_result.get("error_code", "GRADER_ERROR"),
            "message": parsed_result.get("message", "An error occurred during evaluation."),
            "evaluated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

    # 8. If Submit mode: Persist to DynamoDB
    submission_id = None
    attempt_num = current_attempts + 1
    if mode == "submit":
        submission_id = str(uuid.uuid4())
        sub_record = {
            "submission_id": submission_id,
            "exercise_id": exercise_id,
            "user_id": user_id,
            "member_id": current_user.get("member_id"),
            "username": current_user.get("username"),
            "full_name": current_user.get("full_name"),
            "instance_id": instance_id,
            "score": parsed_result.get("score", 0),
            "max_score": parsed_result.get("max_score", 100),
            "percentage": parsed_result.get("percentage", 0.0),
            "passed": parsed_result.get("passed", False),
            "attempt_number": attempt_num,
            "tasks_summary": [
                {
                    "id": t.get("id"),
                    "name": t.get("name"),
                    "points": t.get("points"),
                    "max_points": t.get("max_points"),
                    "status": t.get("status"),
                }
                for t in parsed_result.get("tasks", [])
            ],
        }
        dynamodb_service.create_submission_record(sub_record)

    # 9. Apply feedback filtering
    feedback_mode = exercise_rec.get("feedback_mode", "detailed")
    final_report = _filter_feedback(parsed_result, feedback_mode)
    final_report["submission_id"] = submission_id
    final_report["attempt_number"] = attempt_num if mode == "submit" else None

    return final_report
