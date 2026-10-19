"""
grading_service.py
------------------
ระบบตรวจแบบฝึกหัดอัตโนมัติ (Auto-Grading Engine) สำหรับ GNS3 Labs
- ตรวจสอบความถูกต้องของการตั้งค่าเครือข่ายตาม Test Cases ที่กำหนดไว้
- เชื่อมต่อไปยัง Console (Telnet) ของแต่ละ Node (VPCS, Cisco IOS, Linux ฯลฯ)
- รองรับการตรวจ:
    1. Ping reachability (VPCS และ Cisco) เช่น ping 8.8.8.8 หรือ ping gateway
    2. VPCS IP configuration (show ip) เช่น IP, Subnet mask, Default Gateway
    3. CLI Command output verification (เช่น show ip interface brief, show ip route)
"""

import asyncio
from datetime import datetime, timezone
import re
import socket
from typing import Optional

from fastapi import HTTPException

from app import gns3_service
from app.models import (
    GradingCheckType,
    GradingConfig,
    GradeSubmissionResponse,
    TestCase,
    TestCaseResult,
)


_ANSI_ESCAPE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
_VPCS_PROMPT = re.compile(r"(?im)^\s*\w+(?:\[\d+\])?>\s*$")
_CISCO_PROMPT = re.compile(r"(?im)[>#]\s*$")
_GENERIC_PROMPT = re.compile(r"(?im)[>#$]\s*$")


def _clean_output(raw_bytes: bytes) -> str:
    """ทำความสะอาดข้อมูล Telnet: ตัด Telnet IAC codes และ ANSI escape codes"""
    out = bytearray()
    i = 0
    n = len(raw_bytes)
    while i < n:
        b = raw_bytes[i]
        # Telnet IAC (0xFF)
        if b == 0xFF:
            if i + 1 < n:
                cmd = raw_bytes[i + 1]
                # WILL, WONT, DO, DONT (3-byte sequences)
                if cmd in (251, 252, 253, 254):
                    i += 3
                    continue
                # IAC IAC (escaped 0xFF)
                elif cmd == 255:
                    out.append(255)
                    i += 2
                    continue
                else:
                    i += 2
                    continue
            else:
                break
        else:
            out.append(b)
            i += 1

    text = out.decode("utf-8", errors="replace")
    text = _ANSI_ESCAPE.sub("", text)
    # ตัด carriage return \r ให้เหลือ \n เดียว
    return text.replace("\r\r\n", "\n").replace("\r\n", "\n").replace("\r", "")


async def _drain_and_wake(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    prompt_regex: re.Pattern,
    wake_command: str = "\r\n",
    timeout: float = 3.0,
) -> str:
    """ส่ง Enter เพื่อปลุก console และรออ่าน prompt"""
    writer.write(wake_command.encode("ascii"))
    await writer.drain()

    buf = bytearray()
    deadline = asyncio.get_event_loop().time() + timeout
    while True:
        rem = deadline - asyncio.get_event_loop().time()
        if rem <= 0:
            break
        try:
            chunk = await asyncio.wait_for(reader.read(1024), timeout=min(rem, 0.5))
            if not chunk:
                break
            buf.extend(chunk)
            cleaned = _clean_output(buf)
            if prompt_regex.search(cleaned):
                return cleaned
        except asyncio.TimeoutError:
            continue
    return _clean_output(buf)


async def _execute_command(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    command: str,
    prompt_regex: re.Pattern,
    timeout: float = 8.0,
) -> str:
    """ส่งคำสั่งและรออ่านผลลัพธ์จนกว่าจะเจอ prompt หรือหมดเวลา"""
    writer.write(f"{command.strip()}\r\n".encode("utf-8"))
    await writer.drain()

    buf = bytearray()
    deadline = asyncio.get_event_loop().time() + timeout
    while True:
        rem = deadline - asyncio.get_event_loop().time()
        if rem <= 0:
            break
        try:
            chunk = await asyncio.wait_for(reader.read(2048), timeout=min(rem, 0.6))
            if not chunk:
                break
            buf.extend(chunk)
            cleaned = _clean_output(buf)
            if prompt_regex.search(cleaned):
                return cleaned
        except asyncio.TimeoutError:
            continue
    return _clean_output(buf)


async def _test_vpcs_ping(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    tc: TestCase,
    timeout: float,
) -> tuple[bool, str, str]:
    """ทดสอบ Ping บน VPCS node"""
    target = (tc.target or "8.8.8.8").strip()
    count = tc.count or 3
    cmd = f"ping {target} -c {count}"
    output = await _execute_command(reader, writer, cmd, _VPCS_PROMPT, timeout=timeout)

    # ตัวบ่งชี้ความสำเร็จของ VPCS
    # ตัวอย่าง: "84 bytes from 8.8.8.8 icmp_seq=1 ttl=114 time=24.520 ms"
    success_matches = re.findall(r"\bbytes from\b", output, flags=re.IGNORECASE)
    success_count = len(success_matches)

    is_expected_success = tc.expected.lower() != "unreachable"

    if is_expected_success:
        if success_count > 0:
            msg = f"Ping ไปยัง {target} สำเร็จ (ได้รับ {success_count}/{count} packets)"
            return True, msg, output
        else:
            if "timeout" in output.lower():
                msg = f"Ping ไปยัง {target} ล้มเหลว (Request timed out)"
            elif "not reachable" in output.lower() or "no gateway" in output.lower():
                msg = f"Ping ไปยัง {target} ล้มเหลว (Host unreachable หรือยังไม่ได้ตั้งค่า Gateway)"
            else:
                msg = f"Ping ไปยัง {target} ไม่ได้รับการตอบกลับ"
            return False, msg, output
    else:
        # ต้องการให้ ping ไม่ผ่าน (unreachable)
        if success_count == 0:
            msg = f"ตามที่คาดหวัง: {target} ไม่สามารถเชื่อมต่อได้"
            return True, msg, output
        else:
            msg = f"ไม่ตรงตามเงื่อนไข: คาดหวังให้ unreachable แต่ ping สำเร็จ ({success_count}/{count} packets)"
            return False, msg, output


async def _test_vpcs_show_ip(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    tc: TestCase,
    timeout: float,
) -> tuple[bool, str, str]:
    """ตรวจสอบการตั้งค่า IP/Gateway บน VPCS"""
    output = await _execute_command(reader, writer, "show ip", _VPCS_PROMPT, timeout=timeout)

    # ค้นหา IP และ Mask
    # IP/MASK     : 192.168.1.10/24
    ip_match = re.search(r"IP/MASK\s*:\s*([0-9.]+)(?:/(\d+))?", output, flags=re.IGNORECASE)
    # GATEWAY     : 192.168.1.1
    gw_match = re.search(r"GATEWAY\s*:\s*([0-9.]+)", output, flags=re.IGNORECASE)

    current_ip = ip_match.group(1) if ip_match else "0.0.0.0"
    current_mask = ip_match.group(2) if (ip_match and ip_match.group(2)) else None
    current_gw = gw_match.group(1) if gw_match else "0.0.0.0"

    errors = []
    if tc.expected_ip and current_ip != tc.expected_ip.strip():
        errors.append(f"IP address ไม่ถูกต้อง (คาดหวัง {tc.expected_ip}, ปัจจุบัน {current_ip})")

    if tc.expected_mask:
        exp_mask = str(tc.expected_mask).strip().lstrip("/")
        if current_mask != exp_mask:
            errors.append(f"Subnet prefix ไม่ตรง (คาดหวัง /{exp_mask}, ปัจจุบัน /{current_mask})")

    if tc.expected_gateway and current_gw != tc.expected_gateway.strip():
        errors.append(f"Gateway ไม่ถูกต้อง (คาดหวัง {tc.expected_gateway}, ปัจจุบัน {current_gw})")

    if not errors:
        msg = f"การตั้งค่า IP ถูกต้อง (IP: {current_ip}/{current_mask or 'unknown'}, GW: {current_gw})"
        return True, msg, output
    else:
        return False, "; ".join(errors), output


async def _test_cisco_ping(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    tc: TestCase,
    timeout: float,
) -> tuple[bool, str, str]:
    """ทดสอบ Ping บน Cisco Router / Switch"""
    target = (tc.target or "8.8.8.8").strip()
    count = tc.count or 5
    cmd = f"ping {target} repeat {count}"
    output = await _execute_command(reader, writer, cmd, _CISCO_PROMPT, timeout=timeout)

    # ตัวอย่าง Cisco: "Success rate is 100 percent (5/5)"
    rate_match = re.search(r"Success rate is\s+(\d+)\s+percent", output, flags=re.IGNORECASE)
    success_rate = int(rate_match.group(1)) if rate_match else 0

    is_expected_success = tc.expected.lower() != "unreachable"

    if is_expected_success:
        if success_rate > 0:
            msg = f"Ping ไปยัง {target} สำเร็จ (Success rate: {success_rate}%)"
            return True, msg, output
        else:
            return False, f"Ping ไปยัง {target} ล้มเหลว (Success rate: 0%)", output
    else:
        if success_rate == 0:
            msg = f"ตามที่คาดหวัง: {target} ไม่สามารถเชื่อมต่อได้ (Success rate: 0%)"
            return True, msg, output
        else:
            return False, f"ไม่ตรงตามเงื่อนไข: คาดหวัง unreachable แต่สำเร็จ ({success_rate}%)", output


async def _test_cli_command(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    tc: TestCase,
    is_cisco: bool,
    timeout: float,
) -> tuple[bool, str, str]:
    """ส่งคำสั่ง CLI ตรวจสอบเนื้อหาผลลัพธ์ (contains / not_contains)"""
    cmd = (tc.command or "").strip()
    if not cmd:
        return False, "ไม่ได้ระบุคำสั่ง (command)", ""

    prompt_regex = _CISCO_PROMPT if is_cisco else _GENERIC_PROMPT
    output = await _execute_command(reader, writer, cmd, prompt_regex, timeout=timeout)

    missing = []
    if tc.contains:
        for keyword in tc.contains:
            if keyword.strip() and keyword.strip() not in output:
                missing.append(f"'{keyword}'")

    unwanted = []
    if tc.not_contains:
        for bad_kw in tc.not_contains:
            if bad_kw.strip() and bad_kw.strip() in output:
                unwanted.append(f"'{bad_kw}'")

    if missing:
        msg = f"ผลลัพธ์ของคำสั่ง '{cmd}' ขาดข้อความที่กำหนด: {', '.join(missing)}"
        return False, msg, output

    if unwanted:
        msg = f"ผลลัพธ์ของคำสั่ง '{cmd}' พบข้อความที่ไม่ควรมี: {', '.join(unwanted)}"
        return False, msg, output

    msg = f"คำสั่ง '{cmd}' ผ่านการตรวจสอบเงื่อนไขทั้งหมด"
    return True, msg, output


async def _run_single_test(
    host: str,
    console_port: int,
    node_type: str,
    tc: TestCase,
    timeout_sec: float,
) -> TestCaseResult:
    """เปิด socket Telnet ไปยัง Node และเรียก runner ตามประเภทการตรวจ"""
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, console_port),
            timeout=5.0,
        )
    except Exception as e:
        return TestCaseResult(
            test_id=tc.id,
            title=tc.title,
            node=tc.node,
            status="ERROR",
            points_awarded=0,
            max_points=tc.points,
            message=f"เชื่อมต่อไปยัง Console ของ {tc.node} ที่ port {console_port} ไม่ได้: {e}",
            output_snippet=None,
        )

    try:
        is_vpcs = (node_type or "").lower() == "vpcs" or tc.node.lower().startswith("pc")
        is_cisco = any(
            t in (node_type or "").lower() for t in ("dynamips", "iou", "qemu", "cisco")
        )

        prompt = _VPCS_PROMPT if is_vpcs else (_CISCO_PROMPT if is_cisco else _GENERIC_PROMPT)

        # ปลุก console
        await _drain_and_wake(reader, writer, prompt, timeout=2.5)

        # สำหรับ Cisco: ปิด pagination ด้วย terminal length 0
        if is_cisco:
            try:
                writer.write(b"terminal length 0\r\n")
                await writer.drain()
                await asyncio.sleep(0.3)
            except Exception:
                pass

        # รัน Test ตามประเภท
        passed = False
        message = ""
        raw_output = ""

        if tc.type == GradingCheckType.PING:
            if is_vpcs:
                passed, message, raw_output = await _test_vpcs_ping(
                    reader, writer, tc, timeout_sec
                )
            else:
                passed, message, raw_output = await _test_cisco_ping(
                    reader, writer, tc, timeout_sec
                )

        elif tc.type == GradingCheckType.VPCS_SHOW_IP:
            passed, message, raw_output = await _test_vpcs_show_ip(
                reader, writer, tc, timeout_sec
            )

        elif tc.type == GradingCheckType.CLI_COMMAND:
            passed, message, raw_output = await _test_cli_command(
                reader, writer, tc, is_cisco, timeout_sec
            )

        else:
            return TestCaseResult(
                test_id=tc.id,
                title=tc.title,
                node=tc.node,
                status="ERROR",
                points_awarded=0,
                max_points=tc.points,
                message=f"ประเภทการทดสอบ '{tc.type}' ไม่รองรับ",
                output_snippet=None,
            )

        # ตัด output ให้พอเหมาะสำหรับแสดง feedback
        snippet = "\n".join(raw_output.strip().splitlines()[-15:]) if raw_output else None

        return TestCaseResult(
            test_id=tc.id,
            title=tc.title,
            node=tc.node,
            status="PASSED" if passed else "FAILED",
            points_awarded=tc.points if passed else 0,
            max_points=tc.points,
            message=message,
            output_snippet=snippet,
        )

    except Exception as e:
        return TestCaseResult(
            test_id=tc.id,
            title=tc.title,
            node=tc.node,
            status="ERROR",
            points_awarded=0,
            max_points=tc.points,
            message=f"เกิดข้อผิดพลาดขณะรันการทดสอบ: {e}",
            output_snippet=None,
        )
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


async def grade_instance(
    instance_rec: dict,
    grading_config: GradingConfig,
    exercise_id: str,
) -> GradeSubmissionResponse:
    """
    ตรวจสอบแบบฝึกหัด Lab บน Instance แบบอัตโนมัติ
    1. อ่าน Node map จาก GNS3 REST API บน VM
    2. เปิด Node ที่ยังปิดอยู่ถ้าตั้งค่า auto_start_nodes=True
    3. ส่งคำสั่งผ่าน Telnet console และสรุปผลคะแนน
    """
    if not grading_config.test_cases:
        raise HTTPException(
            status_code=400,
            detail="แบบฝึกหัดนี้ยังไม่ได้กำหนด Test Cases สำหรับตรวจอัตโนมัติ",
        )

    # 1. ดึงข้อมูล nodes จาก GNS3
    project_id, node_map = gns3_service.get_project_nodes_map(instance_rec)
    target_host = gns3_service.get_vm_target_host(instance_rec)

    # 2. ตรวจสอบสถานะและเปิด node ที่จำเป็นถ้ากำหนด auto_start_nodes=True
    if grading_config.auto_start_nodes:
        needed_node_names = {tc.node.strip().lower() for tc in grading_config.test_cases}
        for name in needed_node_names:
            node_info = node_map.get(name)
            if node_info and node_info.get("status") != "started":
                gns3_service.start_node_sync(instance_rec, project_id, node_info["node_id"])

        # รอ 2 วินาทีให้ console port พร้อมรับการเชื่อมต่อ
        await asyncio.sleep(2.0)

        # อัปเดต node map ใหม่หลังเปิด node
        _, node_map = gns3_service.get_project_nodes_map(instance_rec, project_id=project_id)

    # 3. รันแต่ละ test case
    results: list[TestCaseResult] = []
    total_score = 0
    max_score = 0
    passed_count = 0

    for tc in grading_config.test_cases:
        max_score += tc.points
        node_name_clean = tc.node.strip().lower()
        node_info = node_map.get(node_name_clean)

        if not node_info:
            results.append(
                TestCaseResult(
                    test_id=tc.id,
                    title=tc.title,
                    node=tc.node,
                    status="ERROR",
                    points_awarded=0,
                    max_points=tc.points,
                    message=f"ไม่พบ Node '{tc.node}' ในโปรเจ็ค GNS3 ปัจจุบัน",
                    output_snippet=None,
                )
            )
            continue

        console_port = node_info.get("console")
        if not console_port:
            results.append(
                TestCaseResult(
                    test_id=tc.id,
                    title=tc.title,
                    node=tc.node,
                    status="ERROR",
                    points_awarded=0,
                    max_points=tc.points,
                    message=f"Node '{tc.node}' ไม่มี Console Port (สถานะ: {node_info.get('status')})",
                    output_snippet=None,
                )
            )
            continue

        node_type = node_info.get("node_type") or ""
        test_res = await _run_single_test(
            host=target_host,
            console_port=console_port,
            node_type=node_type,
            tc=tc,
            timeout_sec=float(grading_config.timeout_seconds),
        )

        if test_res.status == "PASSED":
            passed_count += 1
            total_score += test_res.points_awarded

        results.append(test_res)

    percentage = round((total_score / max_score * 100), 2) if max_score > 0 else 0.0

    return GradeSubmissionResponse(
        exercise_id=exercise_id,
        instance_id=instance_rec["instance_id"],
        total_score=total_score,
        max_score=max_score,
        percentage=percentage,
        passed_count=passed_count,
        total_count=len(grading_config.test_cases),
        results=results,
        checked_at=datetime.now(timezone.utc).isoformat(),
    )
