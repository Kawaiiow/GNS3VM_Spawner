#!/usr/bin/env python3
"""
NetLab GNS3 Automated Exercise Grader Runner
---------------------------------------------
Zero-dependency in-VM test runner for GNS3 network topologies.
Connects to local GNS3 REST API (127.0.0.1:3080) and device console ports
(localhost:5000+) via raw Telnet sockets with IAC negotiation.

Evaluates:
  1. config_regex   - regex pattern matching on running-config
  2. command_output - arbitrary CLI execution with must_contain / must_not_contain
  3. ping           - end-to-end ICMP ping with success rate threshold
"""

import argparse
import json
import os
import re
import socket
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple


# ==========================================
# TELNET PROTOCOL & CONSOLE CLIENT
# ==========================================

class TelnetConsole:
    """Lightweight RFC 854 Telnet socket client with IAC negotiation."""

    def __init__(self, host: str, port: int, timeout: float = 12.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.sock: Optional[socket.socket] = None
        self.connect()

    def connect(self) -> None:
        self.sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        self.sock.settimeout(self.timeout)

    def close(self) -> None:
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None

    def _negotiate_iac(self, data: bytes) -> bytes:
        """Strip and respond to Telnet IAC (0xFF) command sequences."""
        clean = bytearray()
        i = 0
        n = len(data)
        while i < n:
            b = data[i]
            if b == 255:  # IAC
                if i + 1 < n and data[i + 1] == 255:
                    clean.append(255)
                    i += 2
                elif i + 2 < n:
                    cmd = data[i + 1]
                    opt = data[i + 2]
                    # Respond: WILL (251) -> DONT (254), DO (253) -> WONT (252)
                    if cmd == 251:  # WILL -> DONT
                        try:
                            self.sock.sendall(bytes([255, 254, opt]))
                        except Exception:
                            pass
                    elif cmd == 253:  # DO -> WONT
                        try:
                            self.sock.sendall(bytes([255, 252, opt]))
                        except Exception:
                            pass
                    i += 3
                else:
                    i += 1
            else:
                clean.append(b)
                i += 1
        return bytes(clean)

    def read_until_regex(
        self, patterns: List[str], timeout: Optional[float] = None
    ) -> Tuple[str, int]:
        """
        Read buffer until one of the regex patterns matches.
        Returns (accumulated_text, matching_pattern_index).
        """
        effective_timeout = timeout if timeout is not None else self.timeout
        compiled = [re.compile(p, re.IGNORECASE) for p in patterns]
        buffer = ""
        start_time = time.time()

        while time.time() - start_time < effective_timeout:
            try:
                self.sock.settimeout(max(0.2, effective_timeout - (time.time() - start_time)))
                chunk = self.sock.recv(4096)
                if not chunk:
                    break
                filtered = self._negotiate_iac(chunk)
                text = filtered.decode("utf-8", errors="replace")
                buffer += text

                # Handle pagination prompts on the fly
                if "--More--" in buffer:
                    self.sock.sendall(b" ")
                    buffer = buffer.replace("--More--", "")

                for idx, regex in enumerate(compiled):
                    if regex.search(buffer):
                        return buffer, idx
            except socket.timeout:
                continue
            except Exception:
                break

        return buffer, -1

    def send_line(self, line: str) -> None:
        self.sock.sendall((line + "\r\n").encode("utf-8"))


# ==========================================
# DEVICE DRIVERS
# ==========================================

class DeviceDriver:
    """Base device console driver."""

    def __init__(self, console: TelnetConsole, credentials: Optional[dict] = None):
        self.console = console
        self.credentials = credentials or {}
        self.prompt_pattern = r"[#>$]\s*$"

    def prepare_session(self) -> None:
        pass

    def run_command(self, cmd: str, timeout: float = 15.0) -> str:
        raise NotImplementedError


class CiscoIOSDriver(DeviceDriver):
    """Driver for Cisco IOS, IOU, and IOSv devices."""

    def __init__(self, console: TelnetConsole, credentials: Optional[dict] = None):
        super().__init__(console, credentials)
        self.prompt_pattern = r"[\w\.\-]+[#]\s*$"

    def prepare_session(self) -> None:
        # Send newline to wake console
        self.console.send_line("")
        patterns = [
            r"Would you like to enter the initial configuration dialog\?\s*\[yes/no\]:",
            r"[\w\.\-]+>\s*$",       # User EXEC prompt
            r"[\w\.\-]+#\s*$",       # Privileged EXEC prompt
            r"Password:\s*$",
            r"Press RETURN to get started",
        ]
        text, match_idx = self.console.read_until_regex(patterns, timeout=6.0)

        if match_idx == 0:  # Initial dialog
            self.console.send_line("no")
            text, match_idx = self.console.read_until_regex(patterns[1:], timeout=10.0)

        if match_idx == 4 or "Press RETURN" in text:
            self.console.send_line("")
            text, match_idx = self.console.read_until_regex(patterns[:4], timeout=5.0)

        if match_idx == 1:  # User EXEC '>' -> enter enable mode
            self.console.send_line("enable")
            out, idx = self.console.read_until_regex([r"Password:\s*$", r"[\w\.\-]+#\s*$"], timeout=5.0)
            if idx == 0:
                pwd = self.credentials.get("enable_password", "cisco")
                self.console.send_line(pwd)
                self.console.read_until_regex([r"[\w\.\-]+#\s*$"], timeout=5.0)

        # Disable pagination
        self.console.send_line("terminal length 0")
        self.console.read_until_regex([self.prompt_pattern], timeout=5.0)

    def run_command(self, cmd: str, timeout: float = 20.0) -> str:
        self.console.send_line(cmd)
        text, idx = self.console.read_until_regex([self.prompt_pattern], timeout=timeout)
        # Strip command echo and prompt
        lines = text.splitlines()
        if len(lines) >= 2:
            return "\n".join(lines[1:-1]).strip()
        return text.strip()


class LinuxDriver(DeviceDriver):
    """Driver for Linux / QEMU / Alpine VMs with bash/sh shell."""

    def __init__(self, console: TelnetConsole, credentials: Optional[dict] = None):
        super().__init__(console, credentials)
        self.prompt_pattern = r"[\w\.\-@:~]+[#\$]\s*$"

    def prepare_session(self) -> None:
        self.console.send_line("")
        patterns = [
            r"login:\s*$",
            r"Password:\s*$",
            self.prompt_pattern,
        ]
        text, match_idx = self.console.read_until_regex(patterns, timeout=6.0)

        if match_idx == 0:  # Login prompt
            user = self.credentials.get("username", "root")
            self.console.send_line(user)
            text, match_idx = self.console.read_until_regex(patterns[1:], timeout=5.0)

        if match_idx == 1:  # Password prompt
            pwd = self.credentials.get("password", "root")
            self.console.send_line(pwd)
            self.console.read_until_regex([self.prompt_pattern], timeout=5.0)

        # Set wide terminal to prevent line-wrapping
        self.console.send_line("stty cols 500 2>/dev/null || true")
        self.console.read_until_regex([self.prompt_pattern], timeout=3.0)

    def run_command(self, cmd: str, timeout: float = 20.0) -> str:
        self.console.send_line(cmd)
        text, idx = self.console.read_until_regex([self.prompt_pattern], timeout=timeout)
        lines = text.splitlines()
        if len(lines) >= 2:
            return "\n".join(lines[1:-1]).strip()
        return text.strip()


def get_driver_for_node(
    console: TelnetConsole, device_type: str, credentials: Optional[dict] = None
) -> DeviceDriver:
    dtype = (device_type or "cisco").lower()
    if dtype in ("linux", "alpine", "ubuntu", "host", "qemu_linux"):
        return LinuxDriver(console, credentials)
    return CiscoIOSDriver(console, credentials)


# ==========================================
# GNS3 TOPOLOGY DISCOVERY
# ==========================================

def get_gns3_project_and_nodes(
    api_url: str = "http://127.0.0.1:3080/v2",
    auth: Optional[Tuple[str, str]] = None,
) -> Tuple[dict, List[dict]]:
    """
    Query local GNS3 REST API to retrieve the current active project and its nodes.
    """
    req = urllib.request.Request(f"{api_url}/projects")
    if auth:
        import base64
        cred = base64.b64encode(f"{auth[0]}:{auth[1]}".encode()).decode()
        req.add_header("Authorization", f"Basic {cred}")

    try:
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            projects = json.loads(resp.read().decode())
    except Exception as e:
        raise RuntimeError(f"Cannot connect to local GNS3 REST API at {api_url}: {e}")

    if not projects:
        raise RuntimeError("No projects found in GNS3 server.")

    # Find opened project
    opened = [p for p in projects if p.get("status") == "opened"]
    active_project = opened[0] if opened else projects[0]
    pid = active_project["project_id"]

    # If project is closed, open it
    if active_project.get("status") != "opened":
        open_req = urllib.request.Request(f"{api_url}/projects/{pid}/open", data=b"{}", method="POST")
        if auth:
            open_req.add_header("Authorization", f"Basic {cred}")
        try:
            with urllib.request.urlopen(open_req, timeout=15.0) as resp:
                active_project = json.loads(resp.read().decode())
        except Exception as e:
            raise RuntimeError(f"Cannot open GNS3 project '{active_project.get('name', pid)}': {e}")

    # Fetch nodes
    nodes_req = urllib.request.Request(f"{api_url}/projects/{pid}/nodes")
    if auth:
        nodes_req.add_header("Authorization", f"Basic {cred}")
    with urllib.request.urlopen(nodes_req, timeout=15.0) as resp:
        nodes = json.loads(resp.read().decode())

    return active_project, nodes


# ==========================================
# CHECK EVALUATION ENGINE
# ==========================================

class GraderEngine:
    def __init__(self, rubric: dict, nodes: List[dict]):
        self.rubric = rubric
        self.nodes = nodes
        self.nodes_by_name = {n.get("name"): n for n in nodes if n.get("name")}
        self.active_drivers: Dict[str, DeviceDriver] = {}
        self.running_configs: Dict[str, str] = {}

    def validate_node_states(self) -> Optional[dict]:
        """
        Fail-fast check: Verify all nodes required by rubric are present and started.
        """
        required_node_names = set()
        for task in self.rubric.get("tasks", []):
            node_name = task.get("node")
            if node_name:
                required_node_names.add(node_name)

        stopped_nodes = []
        missing_nodes = []
        for name in required_node_names:
            if name not in self.nodes_by_name:
                missing_nodes.append(name)
            else:
                node = self.nodes_by_name[name]
                if node.get("status") != "started":
                    stopped_nodes.append(name)

        if missing_nodes or stopped_nodes:
            errors = []
            if missing_nodes:
                errors.append(f"Missing required node(s) in GNS3 topology: {', '.join(missing_nodes)}")
            if stopped_nodes:
                errors.append(
                    f"The following required node(s) are stopped: {', '.join(stopped_nodes)}. "
                    "Please start all nodes in GNS3 and wait 30 seconds for them to boot before grading."
                )
            return {
                "status": "error",
                "error_code": "NODES_NOT_RUNNING",
                "message": " | ".join(errors),
                "stopped_nodes": stopped_nodes,
                "missing_nodes": missing_nodes,
            }
        return None

    def get_driver(self, node_name: str, device_type: str = "cisco") -> DeviceDriver:
        if node_name in self.active_drivers:
            return self.active_drivers[node_name]

        node = self.nodes_by_name[node_name]
        console_port = node.get("console")
        if not console_port:
            raise RuntimeError(f"Node '{node_name}' does not have a console port assigned.")

        credentials = self.rubric.get("credentials", {}).get(node_name, {})
        console = TelnetConsole("127.0.0.1", int(console_port))
        driver = get_driver_for_node(console, device_type, credentials)
        driver.prepare_session()
        self.active_drivers[node_name] = driver
        return driver

    def get_running_config(self, node_name: str, driver: DeviceDriver) -> str:
        if node_name in self.running_configs:
            return self.running_configs[node_name]
        cfg = driver.run_command("show running-config")
        self.running_configs[node_name] = cfg
        return cfg

    def evaluate_check(self, check: dict, node_name: str, driver: DeviceDriver) -> dict:
        ctype = check.get("type", "command_output")
        desc = check.get("description", "")
        hint = check.get("hint", "")

        try:
            if ctype == "config_regex":
                pattern = check.get("pattern", "")
                negative = bool(check.get("negative", False))
                custom_cmd = check.get("command")
                text = (
                    driver.run_command(custom_cmd)
                    if custom_cmd
                    else self.get_running_config(node_name, driver)
                )

                matched = bool(re.search(pattern, text, re.MULTILINE))
                passed = (not matched) if negative else matched
                return {
                    "type": ctype,
                    "passed": passed,
                    "description": desc,
                    "hint": hint if not passed else "",
                }

            elif ctype == "command_output":
                cmd = check.get("command", "")
                out = driver.run_command(cmd)
                must_contain = check.get("must_contain", [])
                must_not_contain = check.get("must_not_contain", [])

                passed = True
                failed_reasons = []

                for item in must_contain:
                    if not re.search(item, out, re.MULTILINE):
                        passed = False
                        failed_reasons.append(f"Missing expected output: '{item}'")

                for item in must_not_contain:
                    if re.search(item, out, re.MULTILINE):
                        passed = False
                        failed_reasons.append(f"Unexpected output matched: '{item}'")

                return {
                    "type": ctype,
                    "passed": passed,
                    "description": desc,
                    "hint": hint if not passed else "",
                    "message": "; ".join(failed_reasons) if not passed else "OK",
                }

            elif ctype == "ping":
                target_ip = check.get("target_ip", "")
                repeat = check.get("repeat", 5)
                min_rate = check.get("min_success_rate", 60)

                # Execute ping according to driver type
                if isinstance(driver, LinuxDriver):
                    out = driver.run_command(f"ping -c {repeat} -W 2 {target_ip}", timeout=repeat * 3 + 5)
                    # Check e.g. "0% packet loss" or "(\d+)% packet loss"
                    loss_match = re.search(r"(\d+(?:\.\d+)?)%\s*packet loss", out)
                    if loss_match:
                        loss_rate = float(loss_match.group(1))
                        success_rate = 100.0 - loss_rate
                    else:
                        success_rate = 0.0
                else:
                    out = driver.run_command(f"ping {target_ip} repeat {repeat}", timeout=repeat * 3 + 5)
                    # Cisco: Success rate is 80 percent (4/5)
                    rate_match = re.search(r"Success rate is\s+(\d+)\s+percent", out)
                    success_rate = float(rate_match.group(1)) if rate_match else 0.0

                passed = success_rate >= float(min_rate)
                return {
                    "type": ctype,
                    "passed": passed,
                    "description": desc or f"Ping {target_ip}",
                    "hint": hint if not passed else "",
                    "details": f"Success rate: {success_rate}% (threshold: {min_rate}%)",
                }

            else:
                return {
                    "type": ctype,
                    "passed": False,
                    "description": desc,
                    "message": f"Unsupported check type: {ctype}",
                }

        except Exception as e:
            return {
                "type": ctype,
                "passed": False,
                "description": desc,
                "message": f"Execution error: {str(e)[:200]}",
                "hint": hint,
            }

    def run(self) -> dict:
        # 1. Fail-fast validation
        validation_error = self.validate_node_states()
        if validation_error:
            return validation_error

        tasks_results = []
        total_score = 0
        max_score = 0

        try:
            for task in self.rubric.get("tasks", []):
                tid = task.get("id", str(len(tasks_results) + 1))
                tname = task.get("name", f"Task {tid}")
                node_name = task.get("node")
                device_type = task.get("device_type", "cisco")
                points = int(task.get("points", 10))
                max_score += points

                driver = self.get_driver(node_name, device_type)
                checks_results = []
                all_passed = True

                for chk in task.get("checks", []):
                    c_res = self.evaluate_check(chk, node_name, driver)
                    checks_results.append(c_res)
                    if not c_res["passed"]:
                        all_passed = False

                earned = points if all_passed else 0
                total_score += earned

                tasks_results.append({
                    "id": tid,
                    "name": tname,
                    "node": node_name,
                    "points": earned,
                    "max_points": points,
                    "status": "passed" if all_passed else "failed",
                    "checks": checks_results,
                })

        finally:
            # Clean up all open console connections
            for d in self.active_drivers.values():
                d.console.close()

        rubric_max = self.rubric.get("max_score", max_score)
        passing_score = self.rubric.get("passing_score", int(rubric_max * 0.6))
        percentage = round((total_score / rubric_max * 100), 1) if rubric_max > 0 else 0.0

        return {
            "status": "success",
            "score": total_score,
            "max_score": rubric_max,
            "percentage": percentage,
            "passed": total_score >= passing_score,
            "passing_score": passing_score,
            "feedback_mode": self.rubric.get("feedback_mode", "detailed"),
            "tasks": tasks_results,
            "evaluated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }


# ==========================================
# CLI ENTRY POINT
# ==========================================

def load_rubric(rubric_path: Optional[str], rubric_url: Optional[str]) -> dict:
    if rubric_url:
        req = urllib.request.Request(rubric_url)
        with urllib.request.urlopen(req, timeout=15.0) as resp:
            content = resp.read().decode("utf-8")
    elif rubric_path:
        with open(rubric_path, "r", encoding="utf-8") as f:
            content = f.read()
    else:
        raise ValueError("Must provide either --rubric-file or --rubric-url")

    # Parse JSON or YAML
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        try:
            import yaml
            return yaml.safe_load(content)
        except ImportError:
            raise RuntimeError("Rubric content is YAML but PyYAML is not installed.")


def main():
    parser = argparse.ArgumentParser(description="NetLab GNS3 Automated Exercise Grader Runner")
    parser.add_argument("--rubric-file", help="Path to local rubric JSON/YAML file")
    parser.add_argument("--rubric-url", help="Presigned S3 URL to rubric JSON/YAML")
    parser.add_argument("--mode", default="practice", choices=["practice", "submit"], help="Grading mode")
    parser.add_argument("--gns3-api", default="http://127.0.0.1:3080/v2", help="GNS3 server REST API base")
    args = parser.parse_args()

    try:
        rubric = load_rubric(args.rubric_file, args.rubric_url)
        _, nodes = get_gns3_project_and_nodes(api_url=args.gns3_api)
        engine = GraderEngine(rubric, nodes)
        result = engine.run()
        result["mode"] = args.mode
        print(json.dumps(result, ensure_ascii=False, indent=2))
        sys.exit(0)
    except Exception as e:
        error_res = {
            "status": "error",
            "error_code": "RUNNER_EXCEPTION",
            "message": str(e),
            "mode": args.mode,
        }
        print(json.dumps(error_res, ensure_ascii=False, indent=2))
        sys.exit(1)


if __name__ == "__main__":
    main()
