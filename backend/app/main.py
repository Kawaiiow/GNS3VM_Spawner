import csv
import io
import uuid
from datetime import datetime
from typing import Optional

from fastapi import Depends, BackgroundTasks, FastAPI, HTTPException, Query, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from app import ec2_service, exercise_service, gns3_service, grader_service, s3_service
from app.auth import (
    create_access_token,
    get_current_admin_user,
    get_current_instructor_or_admin,
    get_current_instructor_user,
    get_current_user,
    hash_password,
    verify_password,
)
from app.config import get_settings
from app.dynamodb_service import (
    create_exercise_record,
    create_user,
    delete_exercise_record,
    delete_user_record,
    get_exercise_record,
    get_instance_record,
    get_submission_record,
    get_user_by_id,
    get_user_by_identifier,
    get_user_by_member_id,
    get_user_by_username,
    list_all_exercises,
    list_all_instances,
    list_all_users,
    list_instances_by_user,
    list_submissions_by_exercise,
    list_submissions_by_user,
    update_exercise_status,
    update_user_fields,
)
from app.models import (
    DashboardInstance,
    DashboardUserInfo,
    ExerciseCreate,
    ExerciseListResponse,
    ExerciseResponse,
    ExtendTimerResponse,
    GradingReportResponse,
    InstanceActionResponse,
    InstanceInfo,
    InstanceListResponse,
    LaunchInstanceRequest,
    LoginRequest,
    RubricUpdateRequest,
    SetTimerRequest,
    SubmissionListResponse,
    SubmissionRecord,
    TokenResponse,
    UserCreate,
    UserInDB,
    UserResponse,
    UserRole,
    UserUpdate,
)

app = FastAPI(
    title="NetLab Cloud - Backend API",
    description="API สำหรับระบบ GNS3 VM บน AWS Cloud พร้อม DynamoDB Users, Instances & Exercises Management",
    version="2.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
@app.get("/health")
def health_check():
    return {"status": "ok", "service": "netlab-backend"}


# ==========================================
# AUTHENTICATION ENDPOINTS
# ==========================================

@app.post("/auth/login", response_model=TokenResponse)
def login(payload: LoginRequest, response: Response):
    """
    เข้าสู่ระบบด้วย Username หรือ Member ID (รหัสประจำตัว) และรหัสผ่าน
    คืนค่า JWT access token พร้อมตั้งค่า HttpOnly cookie สำหรับ browser
    """
    user_dict = get_user_by_identifier(payload.identifier)
    if not user_dict:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not verify_password(payload.password, user_dict.get("password_hash", "")):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token_data = {
        "sub": user_dict["user_id"],
        "username": user_dict["username"],
        "member_id": user_dict["member_id"],
        "role": user_dict["role"],
    }
    token = create_access_token(token_data)

    # Set HttpOnly cookie for web SSR/browser sessions
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        max_age=1440 * 60,
        samesite="lax",
    )

    user_resp = UserResponse(
        user_id=user_dict["user_id"],
        username=user_dict["username"],
        member_id=user_dict["member_id"],
        full_name=user_dict.get("full_name"),
        role=user_dict["role"],
        active_instance_id=user_dict.get("active_instance_id"),
        active_exercise_instance_id=user_dict.get("active_exercise_instance_id"),
        created_at=user_dict["created_at"],
        updated_at=user_dict["updated_at"],
    )

    return TokenResponse(access_token=token, token_type="bearer", user=user_resp)

@app.post("/auth/logout")
def logout(response: Response):
    """ออกจากระบบ: ลบคุกกี้ access_token (เรียกซ้ำได้ ไม่ต้องล็อกอิน)"""
    response.delete_cookie(key="access_token", httponly=True, samesite="lax")
    return {"message": "Logged out successfully."}

@app.get("/auth/me", response_model=UserResponse)
def get_my_profile(current_user: UserInDB = Depends(get_current_user)):
    """ดูข้อมูลโปรไฟล์และสถานะ VM ปัจจุบันของผู้ใช้ที่ล็อกอินอยู่"""
    fresh_user = get_user_by_id(current_user.user_id) or current_user.model_dump()
    return UserResponse(
        user_id=fresh_user["user_id"],
        username=fresh_user["username"],
        member_id=fresh_user["member_id"],
        full_name=fresh_user.get("full_name"),
        role=fresh_user["role"],
        active_instance_id=fresh_user.get("active_instance_id"),
        active_exercise_instance_id=fresh_user.get("active_exercise_instance_id"),
        created_at=fresh_user["created_at"],
        updated_at=fresh_user["updated_at"],
    )


def _verify_instance_ownership(instance_id: str, user: UserInDB):
    """ตรวจสอบว่าผู้ใช้เป็นเจ้าของ VM นี้ หรือมีสิทธิ์เป็น admin หรือไม่"""
    if user.role == UserRole.ADMIN:
        return

    record = get_instance_record(instance_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"ไม่พบข้อมูล instance {instance_id}",
        )

    if record.get("user_id") != user.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="คุณไม่มีสิทธิ์จัดการ VM ของผู้ใช้อื่น",
        )


def _resolve_export_instance(instance_id: Optional[str], current_user: UserInDB) -> dict:
    """หา VM ที่จะ snapshot (ตรวจสิทธิ์) แล้วคืน instance record
    หมายเหตุ: SNAPSHOTS_BUCKET ไม่บังคับ ถ้าไม่ตั้งจะข้ามการสำรองลง S3 (ต้นแบบยังเป็น AMI ใช้สร้าง VM ได้)
    """
    active = current_user.active_instance_id
    if active == "PENDING_LAUNCH":
        active = None
    target_instance_id = instance_id or active
    if not target_instance_id:
        # Instructor ไม่จำกัดจำนวน VM: ถ้าไม่ระบุ instance_id จะใช้เครื่องที่มีอยู่เครื่องเดียว
        live = list_instances_by_user(current_user.user_id)
        if len(live) > 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="มี VM หลายเครื่อง กรุณาระบุ instance_id ที่ต้องการ export",
            )
        if live:
            target_instance_id = live[0]["instance_id"]
    if not target_instance_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="กรุณาระบุ instance_id หรือเปิด VM เพื่อสร้างแบบฝึกหัด (หรือระบุ ami_id)",
        )

    _verify_instance_ownership(target_instance_id, current_user)
    instance_rec = get_instance_record(target_instance_id)
    if not instance_rec:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"ไม่พบข้อมูล instance {target_instance_id}",
        )
    return instance_rec


# ==========================================
# EXERCISES (LAB TEMPLATES & SNAPSHOTS) ENDPOINTS
# ==========================================

@app.get("/exercises", response_model=ExerciseListResponse)
def get_exercises(only_active: bool = True):
    """ดูรายการแบบฝึกหัด Lab ทั้งหมดที่เปิดให้ทำ"""
    records = list_all_exercises(only_active=only_active)
    exercises = [ExerciseResponse(**r) for r in records]
    return ExerciseListResponse(count=len(exercises), exercises=exercises)


@app.get("/exercises/{exercise_id}", response_model=ExerciseResponse)
def get_exercise_detail(exercise_id: str):
    """ดูรายละเอียดของแบบฝึกหัด Lab (พร้อม sync สถานะ AMI ถ้ายัง pending)"""
    record = get_exercise_record(exercise_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Exercise '{exercise_id}' not found.",
        )

    # Sync สถานะ AMI กับ AWS EC2 หากสถานะยังเป็น pending
    if record.get("status") == "pending" and record.get("ami_id"):
        real_status = ec2_service.get_image_status(record["ami_id"])
        if real_status in ("available", "failed"):
            update_exercise_status(exercise_id, real_status)
            record["status"] = real_status

    return ExerciseResponse(**record)


@app.post("/exercises", response_model=ExerciseResponse, status_code=201)
def create_exercise(
    payload: ExerciseCreate,
    background_tasks: BackgroundTasks,
    current_user: UserInDB = Depends(get_current_instructor_user),
):
    """
    สร้างแบบฝึกหัด Lab ใหม่ (เฉพาะ Instructor, Admin สร้างไม่ได้)
    ได้ "ต้นแบบ VM" 1 อัน ที่สำรองไว้ใน S3 (เป็น image ของ VM ไม่ใช่ไฟล์ .gns3project)
    - ไม่ระบุโปรเจ็คเลย (ค่าเริ่มต้น): ต้นแบบมีทุกโปรเจ็คบน VM ของอาจารย์
    - ระบุ project_name / project_names (หรือ project_id / project_ids): ต้นแบบมีเฉพาะโปรเจ็คที่เลือก
    - ระบุ instance_id (หรือใช้ VM เดียวที่มี) ดูรายชื่อโปรเจ็คได้ที่ GET /instances/{id}/gns3/projects
    - ทำเบื้องหลัง: status = pending -> available | failed (ดูความคืบหน้า/สาเหตุที่ status_detail)
      ลำดับ: snapshot VM -> (ถ้าเลือกบางโปรเจ็ค) ตัดโปรเจ็คอื่นออกใน VM ชั่วคราว -> สำรองลง S3
    - สร้าง VM จากแบบฝึกหัดนี้ผ่าน POST /instances (exercise_id) จะได้ VM ที่มีโปรเจ็คครบตามที่เลือก
      ถ้า AMI ถูกลบไปแล้ว ระบบจะกู้คืนจากไฟล์ใน S3 ให้เอง
    - หากระบุ ami_id: ผูกกับ AMI ที่มีอยู่แล้วโดยตรง (ไม่ทำต้นแบบใหม่)
    - คำแนะนำ: ควร stop node ทุกตัวใน GNS3 ก่อนสร้าง เพื่อให้ snapshot สมบูรณ์
    """
    if payload.ami_id:
        # ผูกกับ AMI ที่มีอยู่แล้ว: ต้องเป็น AMI จริงและใช้งานได้ (กัน ami_id มั่ว เช่น "string")
        ami_state = ec2_service.get_image_status(payload.ami_id)
        if ami_state not in ("available", "pending"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"AMI '{payload.ami_id}' ใช้งานไม่ได้ (สถานะ: {ami_state}) "
                    "ตรวจ ami_id ให้ถูกต้อง หรือไม่ต้องใส่ ami_id เพื่อให้ระบบ snapshot จาก VM ของอาจารย์"
                ),
            )
        item = create_exercise_record(
            instructor_id=current_user.user_id,
            title=payload.title,
            description=payload.description,
            ami_id=payload.ami_id,
            status=ami_state,  # available | pending (GET /exercises/{id} จะ sync เป็น available เอง)
            is_active=True,
        )
        return ExerciseResponse(**item)

    settings = get_settings()
    use_project_files = settings.exercise_template_mode == "gns3project"
    if use_project_files and not settings.snapshots_bucket:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="โหมด gns3project ต้องตั้งค่า SNAPSHOTS_BUCKET ใน .env",
        )

    instance_rec = _resolve_export_instance(payload.instance_id, current_user)

    # ตรวจสอบเบื้องต้นแบบ synchronous (VM เปิดอยู่, รหัสผ่านถูก, เลือกโปรเจ็คได้) แล้วค่อยทำต้นแบบเบื้องหลัง
    projects = gns3_service.list_projects(instance_rec)

    ids = list(payload.project_ids or [])
    if payload.project_id:
        ids.append(payload.project_id)
    names = list(payload.project_names or [])
    if payload.project_name:
        names.append(payload.project_name)

    selected = gns3_service.select_projects(projects, ids, names)
    export_all = len(selected) == len(projects)  # ไม่ระบุอะไร หรือเลือกครบทุกอัน = ใช้ snapshot ตรงๆ
    project_names = [p.get("name") or p["project_id"] for p in selected]

    exercise_id = str(uuid.uuid4())
    item = create_exercise_record(
        exercise_id=exercise_id,
        instructor_id=current_user.user_id,
        title=payload.title,
        description=payload.description,
        project_name=", ".join(project_names)[:300],
        project_names=project_names,
        status="pending",
        is_active=True,
    )
    if use_project_files:
        # export แต่ละโปรเจ็คเป็น .gns3project -> S3 (ทุกโปรเจ็คถ้าไม่ได้เลือก)
        background_tasks.add_task(
            exercise_service.build_exercise_export, exercise_id, instance_rec, selected
        )
        return ExerciseResponse(**item)
    background_tasks.add_task(
        exercise_service.build_exercise_template,
        exercise_id,
        current_user.user_id,
        instance_rec,
        [p["project_id"] for p in selected],
        export_all,
    )
    return ExerciseResponse(**item)


@app.get("/instances/{instance_id}/gns3/projects")
def list_gns3_projects(
    instance_id: str,
    current_user: UserInDB = Depends(get_current_instructor_or_admin),
):
    """แสดงรายชื่อโปรเจ็คทั้งหมดที่มีใน GNS3 บน VM นี้ (ใช้เลือกก่อน export)"""
    _verify_instance_ownership(instance_id, current_user)
    instance_rec = get_instance_record(instance_id)
    if not instance_rec:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"ไม่พบข้อมูล instance {instance_id}",
        )
    projects = gns3_service.list_projects(instance_rec)
    return {"instance_id": instance_id, "count": len(projects), "projects": projects}


@app.delete("/exercises/{exercise_id}", status_code=200)
def delete_exercise(
    exercise_id: str,
    current_user: UserInDB = Depends(get_current_instructor_or_admin),
):
    """
    ลบแบบฝึกหัด Lab (Instructor ทุกคน หรือ Admin)
    - terminate VM ทุกเครื่องที่สร้างจากแบบฝึกหัดนี้ (exercise_id เดียวกัน) และคืนโควตาให้เจ้าของ
    - ถ้า terminate VM เครื่องใดไม่สำเร็จ จะยังไม่ลบแบบฝึกหัด (ตอบ 500 แล้วลองใหม่ได้)
    - จากนั้น De-register AMI + ลบ snapshot (ถ้ามี), ลบไฟล์สำรองบน S3 (ถ้ามี) และลบแถวใน DynamoDB
    """
    record = get_exercise_record(exercise_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Exercise '{exercise_id}' not found.",
        )

    terminated = ec2_service.terminate_instances_for_exercise(exercise_id)

    # ไม่ De-register AMI หลักของระบบ เผื่อมีคนสร้างแบบฝึกหัดโดยใส่ ami_id ของ Base AMI
    ami_id = record.get("ami_id")
    if ami_id and ami_id != get_settings().default_ami_id:
        ec2_service.deregister_image(ami_id)

    s3_keys = set(record.get("s3_keys") or [])
    if record.get("s3_key"):
        s3_keys.add(record["s3_key"])
    for key in s3_keys:
        s3_service.delete_object(key)

    delete_exercise_record(exercise_id)
    return {
        "message": f"Exercise '{exercise_id}' deleted successfully.",
        "terminated_instances": terminated,
    }


# ==========================================
# INSTANCES (VM) ENDPOINTS
# ==========================================


@app.post("/instances", response_model=InstanceInfo, status_code=201)
def create_instance(
    payload: LaunchInstanceRequest,
    current_user: UserInDB = Depends(get_current_user),
):
    """
    สร้าง (launch) GNS3 VM บน EC2
    - ผูกกับ user_id ของผู้ใช้ที่ล็อกอินโดยอัตโนมัติ
    - บังคับโควตา 1 VM ต่อ 1 User อย่างเข้มงวดผ่าน DynamoDB Atomic Lock
    - รองรับการเลือก exercise_id เพื่อดึง AMI ของแบบฝึกหัดนั้นมา Launch
    - student / instructor: Sandbox 1 เครื่อง + Exercise 1 เครื่อง | admin: สร้างไม่ได้
    """
    if current_user.role == UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin ไม่สามารถสร้าง VM ได้ (ดู Dashboard และจัดการผู้ใช้เท่านั้น)",
        )
    return ec2_service.launch_instance(
        user_id=current_user.user_id,
        instance_name=payload.instance_name,
        instance_type=payload.instance_type,
        ami_id=payload.ami_id,
        exercise_id=payload.exercise_id,
        role=current_user.role.value,
    )


@app.get("/instances", response_model=InstanceListResponse)
def get_instances(
    current_user: UserInDB = Depends(get_current_user),
):
    """
    List VM instances:
    - ถ้าเป็นนักศึกษา: จะเห็นเฉพาะ VM ของตนเอง
    - ถ้าเป็น Admin: สามารถดู VM ทั้งหมดของทุกคนในระบบ
    """
    if current_user.role == UserRole.ADMIN:
        instances = ec2_service.list_instances()
    else:
        # ผู้ใช้เห็นรหัสผ่าน GNS3 ของ VM ตัวเองเท่านั้น (Admin ไม่เห็น)
        instances = ec2_service.list_instances(
            user_id=current_user.user_id, include_credentials=True
        )

    return InstanceListResponse(count=len(instances), instances=instances)


@app.post("/instances/{instance_id}/start", response_model=InstanceActionResponse)
def start_instance(
    instance_id: str,
    current_user: UserInDB = Depends(get_current_user),
):
    """เปิดเครื่อง VM ที่ถูก stop ไว้ (ตรวจสอบความเป็นเจ้าของก่อน)"""
    _verify_instance_ownership(instance_id, current_user)
    return ec2_service.start_instance(instance_id)


@app.post("/instances/{instance_id}/stop", response_model=InstanceActionResponse)
def stop_instance(
    instance_id: str,
    current_user: UserInDB = Depends(get_current_user),
):
    """ปิดเครื่อง VM ชั่วคราว (ตรวจสอบความเป็นเจ้าของก่อน)"""
    _verify_instance_ownership(instance_id, current_user)
    return ec2_service.stop_instance(instance_id)


@app.post("/instances/{instance_id}/extend", response_model=ExtendTimerResponse)
def extend_instance_timer(
    instance_id: str,
    current_user: UserInDB = Depends(get_current_user),
):
    """
    รีเวลา auto-stop กลับเป็น 4 ชั่วโมง (นับจากตอนกด) สำหรับ VM ของ student ที่กำลังทำงานอยู่
    - ตรวจสอบความเป็นเจ้าของก่อน
    - กดได้ไม่จำกัดครั้ง แต่ตั้งเป็นค่าเต็มใหม่เสมอ (ไม่ใช่บวกเพิ่ม)
    """
    _verify_instance_ownership(instance_id, current_user)
    return ec2_service.extend_instance(instance_id)


@app.post("/instances/{instance_id}/timer", response_model=ExtendTimerResponse)
def set_instance_timer(
    instance_id: str,
    payload: SetTimerRequest,
    current_user: UserInDB = Depends(get_current_admin_user),
):
    """
    ตั้งเวลาที่เหลือก่อน auto-stop ของ VM รายเครื่อง (เฉพาะ Admin)
    - minutes = เวลาที่เหลือ นับจากตอนเรียก API (ไม่ใช่บวกเพิ่ม) ขั้นต่ำ 1 นาที สูงสุดตาม AUTO_STOP_MAX_HOURS (24 ชม.)
    - ใช้ได้กับ VM ของ student ที่กำลัง running/pending เท่านั้น
    - ไม่ตรวจความเป็นเจ้าของ: อาจารย์/แอดมินตั้งให้ VM ของนักศึกษาคนไหนก็ได้
    """
    return ec2_service.set_instance_timer(instance_id, payload.minutes)


@app.delete("/instances/{instance_id}", response_model=InstanceActionResponse)
def delete_instance(
    instance_id: str,
    current_user: UserInDB = Depends(get_current_user),
):
    """
    ลบ (terminate) instance ถาวรบน EC2
    - ตรวจสอบสิทธิ์เจ้าของ
    - ปลดล็อก active_instance_id ใน DynamoDB เพื่อให้ผู้ใช้สามารถสร้าง VM ใหม่ได้
    """
    _verify_instance_ownership(instance_id, current_user)
    return ec2_service.terminate_instance(instance_id)


@app.post("/admin/instances/terminate-all")
def admin_terminate_all_instances(
    wait: bool = Query(True, description="รอจน EC2 เป็น terminated ก่อนตอบกลับ"),
    current_user: UserInDB = Depends(get_current_admin_user),
):
    """
    ลบ (terminate) VM ทั้งหมดที่ระบบสร้างไว้ (เฉพาะ Admin)
    ใช้ก่อน terraform destroy เพื่อให้ลบ Security Group ของ VM ได้โดยไม่ติด DependencyViolation
    - ปล่อยโควตาของเจ้าของทุก VM
    - wait=true: รอจน EC2 รายงาน terminated (สูงสุดประมาณ 5 นาที)
    """
    terminated: list[str] = []
    failed: list[dict] = []
    for rec in list_all_instances():
        iid = rec["instance_id"]
        try:
            ec2_service.terminate_instance(iid)
            terminated.append(iid)
        except HTTPException as e:
            failed.append({"instance_id": iid, "error": str(e.detail)})

    wait_error: Optional[str] = None
    if wait and terminated:
        try:
            ec2_service.get_ec2_client().get_waiter("instance_terminated").wait(
                InstanceIds=terminated,
                WaiterConfig={"Delay": 5, "MaxAttempts": 60},
            )
        except Exception as e:  # noqa: BLE001
            wait_error = str(e)[:300]

    return {
        "terminated_count": len(terminated),
        "terminated": terminated,
        "failed": failed,
        "wait_error": wait_error,
    }


@app.post("/admin/images/delete-all")
def admin_delete_all_images(
    current_user: UserInDB = Depends(get_current_admin_user),
):
    """
    ลบ AMI (และ EBS snapshot) ที่ระบบสร้างเอง (เฉพาะ Admin): ติด tag Project=gns3-cloud
    และชื่อขึ้นต้นด้วย netlab-ex- / netlab-restore- (ต้นแบบแบบฝึกหัด)
    ใช้ก่อน terraform destroy หลัง terminate-all เพราะ Terraform ไม่รู้จัก AMI ที่ระบบสร้างเอง
    - ไม่แตะ Base AMI (netlab-gns3-base-*) และ DEFAULT_AMI_ID
    - ไฟล์สำรองบน S3 ไม่ถูกลบ: แบบฝึกหัดที่ยังอยู่ใน DynamoDB จะกู้คืนจาก S3 ให้เองตอนสร้าง VM
    """
    return ec2_service.deregister_all_project_images()


# ==========================================
# AUTOMATED GRADING & SUBMISSIONS ENDPOINTS
# ==========================================

@app.post("/instances/{instance_id}/grade", response_model=GradingReportResponse)
def grade_instance_practice(
    instance_id: str,
    current_user: UserInDB = Depends(get_current_user),
):
    """
    ตรวจแบบฝึกหัดโหมดทดสอบฝีมือ (Practice Check)
    - รันการตรวจภายใน VM ผ่าน AWS SSM
    - ตรวจสอบทั้ง configuration และ functional connectivity
    - ไม่บันทึกคะแนนเป็นทางการ นักศึกษาสามารถกดตรวจได้ไม่จำกัด
    """
    return grader_service.run_grading_session(
        instance_id=instance_id,
        current_user=current_user.model_dump(),
        mode="practice",
    )


@app.post("/instances/{instance_id}/submit", response_model=GradingReportResponse)
def grade_instance_submit(
    instance_id: str,
    current_user: UserInDB = Depends(get_current_user),
):
    """
    ส่งแบบฝึกหัดเป็นทางการ (Formal Submission)
    - ตรวจสอบโควตาจำนวนครั้งที่ส่งได้ (max_attempts)
    - บันทึกคะแนนและรายงานผลลงใน DynamoDB (netlab_submissions)
    """
    return grader_service.run_grading_session(
        instance_id=instance_id,
        current_user=current_user.model_dump(),
        mode="submit",
    )


@app.get("/exercises/{exercise_id}/rubric")
def get_exercise_rubric(
    exercise_id: str,
    current_user: UserInDB = Depends(get_current_instructor_or_admin),
):
    """ดึงข้อมูลเกณฑ์การตรวจ (Rubric) ของแบบฝึกหัด (เฉพาะ Instructor/Admin)"""
    return grader_service.get_exercise_rubric(exercise_id)


@app.put("/exercises/{exercise_id}/rubric")
def update_exercise_rubric(
    exercise_id: str,
    payload: RubricUpdateRequest,
    current_user: UserInDB = Depends(get_current_instructor_or_admin),
):
    """
    บันทึกหรืออัปเดตเกณฑ์การตรวจ (Rubric) ของแบบฝึกหัด (เฉพาะ Instructor/Admin)
    - รองรับทั้ง YAML และ JSON
    - คอมไพล์และจัดเก็บลง S3 อัตโนมัติ
    """
    return grader_service.save_exercise_rubric(
        exercise_id=exercise_id,
        rubric_content=payload.rubric_yaml,
        max_attempts=payload.max_attempts,
        keep_score_policy=payload.keep_score_policy,
        feedback_mode=payload.feedback_mode,
        passing_score=payload.passing_score,
    )


@app.get("/exercises/{exercise_id}/submissions", response_model=SubmissionListResponse)
def list_exercise_submissions(
    exercise_id: str,
    current_user: UserInDB = Depends(get_current_instructor_or_admin),
):
    """ดูรายการส่งงานของนักศึกษาทุกคนในแบบฝึกหัดนี้ (สำหรับ Instructor/Admin)"""
    items = dynamodb_service.list_submissions_by_exercise(exercise_id)
    submissions = [SubmissionRecord(**i) for i in items]
    return SubmissionListResponse(
        count=len(submissions),
        exercise_id=exercise_id,
        submissions=submissions,
    )


@app.get("/exercises/{exercise_id}/submissions/export")
def export_exercise_submissions_csv(
    exercise_id: str,
    current_user: UserInDB = Depends(get_current_instructor_or_admin),
):
    """ดาวน์โหลดสมุดคะแนน (Gradebook) ของแบบฝึกหัดนี้เป็นไฟล์ CSV (สำหรับ Instructor/Admin)"""
    items = dynamodb_service.list_submissions_by_exercise(exercise_id)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Submission ID",
        "Student ID",
        "Username",
        "Full Name",
        "Score",
        "Max Score",
        "Percentage",
        "Passed",
        "Attempt",
        "Submitted At",
    ])
    for s in items:
        writer.writerow([
            s.get("submission_id", ""),
            s.get("member_id", ""),
            s.get("username", ""),
            s.get("full_name", ""),
            s.get("score", 0),
            s.get("max_score", 100),
            s.get("percentage", 0.0),
            "PASS" if s.get("passed") else "FAIL",
            s.get("attempt_number", 1),
            s.get("submitted_at", ""),
        ])
    output.seek(0)
    filename = f"exercise_{exercise_id[:8]}_grades.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.get("/submissions/my", response_model=SubmissionListResponse)
def get_my_submissions(
    exercise_id: Optional[str] = None,
    current_user: UserInDB = Depends(get_current_user),
):
    """ดูประวัติการส่งแบบฝึกหัดของตนเอง"""
    items = dynamodb_service.list_submissions_by_user(
        user_id=current_user.user_id,
        exercise_id=exercise_id,
    )
    submissions = [SubmissionRecord(**i) for i in items]
    return SubmissionListResponse(
        count=len(submissions),
        exercise_id=exercise_id,
        submissions=submissions,
    )


# ==========================================
# ADMIN MANAGEMENT ENDPOINTS
# ==========================================

@app.post("/admin/users", response_model=UserResponse, status_code=201)
def admin_create_user(
    payload: UserCreate,
    current_user: UserInDB = Depends(get_current_admin_user),
):
    """สร้างบัญชีผู้ใช้ใหม่ (สำหรับ Admin/Instructor เท่านั้น)"""
    hashed = hash_password(payload.password)
    user_item = create_user(
        username=payload.username,
        member_id=payload.member_id,
        password_hash=hashed,
        role=payload.role.value,
        full_name=payload.full_name,
    )
    return UserResponse(
        user_id=user_item["user_id"],
        username=user_item["username"],
        member_id=user_item["member_id"],
        full_name=user_item.get("full_name"),
        role=user_item["role"],
        active_instance_id=user_item.get("active_instance_id"),
        active_exercise_instance_id=user_item.get("active_exercise_instance_id"),
        created_at=user_item["created_at"],
        updated_at=user_item["updated_at"],
    )


@app.get("/admin/users", response_model=list[UserResponse])
def admin_list_users(
    current_user: UserInDB = Depends(get_current_admin_user),
):
    """ดูรายชื่อผู้ใช้ทั้งหมดในระบบ (เฉพาะ Admin)"""
    users = list_all_users()
    return [
        UserResponse(
            user_id=u["user_id"],
            username=u["username"],
            member_id=u["member_id"],
            full_name=u.get("full_name"),
            role=u["role"],
            active_instance_id=u.get("active_instance_id"),
            active_exercise_instance_id=u.get("active_exercise_instance_id"),
            created_at=u["created_at"],
            updated_at=u["updated_at"],
        )
        for u in users
    ]

@app.get("/admin/users/{user_id}", response_model=UserResponse)
def admin_get_user(
    user_id: str,
    current_user: UserInDB = Depends(get_current_admin_user),
):
    """
    ดูข้อมูลบัญชีผู้ใช้รายบุคคล (เฉพาะ Admin)
    """
    target = get_user_by_id(user_id)
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ไม่พบผู้ใช้นี้")
    
    return _user_response(target)

def _user_response(u: dict) -> UserResponse:
    return UserResponse(
        user_id=u["user_id"],
        username=u["username"],
        member_id=u["member_id"],
        full_name=u.get("full_name"),
        role=u["role"],
        active_instance_id=u.get("active_instance_id"),
        active_exercise_instance_id=u.get("active_exercise_instance_id"),
        created_at=u["created_at"],
        updated_at=u["updated_at"],
    )


def _user_has_live_instance(user: dict) -> bool:
    """True ถ้าผู้ใช้ยังมี instance (Sandbox/Exercise) ที่ยังไม่ terminated"""
    return len(list_instances_by_user(user["user_id"])) > 0


@app.get("/admin/dashboard", response_model=list[DashboardUserInfo])
def admin_dashboard(
    current_user: UserInDB = Depends(get_current_admin_user),
):
    """
    Dashboard (เฉพาะ Admin): ผู้ใช้ทุกคน พร้อม Instance (Sandbox/Exercise) ทั้งหมดที่ใช้งานอยู่
    ข้อมูล state/ip จะ sync กับ EC2 ก่อนแสดงผล
    """
    users = list_all_users()
    by_user: dict = {}
    for inst in ec2_service.list_instances():
        if inst.user_id:
            by_user.setdefault(inst.user_id, []).append(inst)

    rows = []
    for u in users:
        rows.append(
            DashboardUserInfo(
                user_id=u["user_id"],
                username=u["username"],
                member_id=u["member_id"],
                full_name=u.get("full_name"),
                role=u["role"],
                instances=[
                    DashboardInstance(
                        instance_id=i.instance_id,
                        name=i.name,
                        kind="exercise" if i.exercise_id else "sandbox",
                        exercise_id=i.exercise_id,
                        state=i.state,
                        public_ip=i.public_ip,
                    )
                    for i in by_user.get(u["user_id"], [])
                ],
            )
        )
    return rows


@app.patch("/admin/users/{user_id}", response_model=UserResponse)
def admin_update_user(
    user_id: str,
    payload: UserUpdate,
    current_user: UserInDB = Depends(get_current_admin_user),
):
    """
    แก้ไขบัญชีผู้ใช้ (เฉพาะ Admin) ส่งเฉพาะฟิลด์ที่ต้องการเปลี่ยน
    - แก้ username / member_id / full_name / role ได้ และใส่ password เพื่อรีเซ็ตรหัสผ่าน
    - Admin ไม่สามารถลดสิทธิ์ของตัวเองได้
    - หมายเหตุ: ถ้าเปลี่ยนรหัสผ่าน ต้องอัปเดตใน GNS3 ให้ตรงกันเอง
    """
    target = get_user_by_id(user_id)
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ไม่พบผู้ใช้นี้")

    changes = payload.model_dump(exclude_none=True)
    if not changes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="ไม่มีข้อมูลที่จะแก้ไข"
        )

    if (
        user_id == current_user.user_id
        and "role" in changes
        and changes["role"] != UserRole.ADMIN
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="ไม่สามารถลดสิทธิ์ admin ของตัวเองได้",
        )

    if "username" in changes:
        other = get_user_by_username(changes["username"])
        if other and other["user_id"] != user_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Username '{changes['username']}' ถูกใช้แล้ว",
            )
    if "member_id" in changes:
        other = get_user_by_member_id(changes["member_id"])
        if other and other["user_id"] != user_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Member ID '{changes['member_id']}' ถูกใช้แล้ว",
            )

    fields: dict = {}
    for key in ("username", "member_id", "full_name"):
        if key in changes:
            fields[key] = changes[key]
    if "role" in changes:
        fields["role"] = changes["role"].value
    if "password" in changes:
        fields["password_hash"] = hash_password(changes["password"])

    return _user_response(update_user_fields(user_id, fields))


@app.delete("/admin/users/{user_id}", status_code=200)
def admin_delete_user(
    user_id: str,
    current_user: UserInDB = Depends(get_current_admin_user),
):
    """
    ลบบัญชีผู้ใช้ (เฉพาะ Admin)
    - ลบบัญชีตัวเองไม่ได้
    - ถ้าบัญชีนี้ยังมี Instance (Sandbox/Exercise) ใช้งานอยู่ จะลบไม่ได้ (409)
      ต้อง terminate instance ก่อน
    """
    if user_id == current_user.user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="ไม่สามารถลบบัญชีของตัวเองได้",
        )

    target = get_user_by_id(user_id)
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ไม่พบผู้ใช้นี้")

    if _user_has_live_instance(target):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"บัญชีนี้ยังมี Instance ใช้งานอยู่ ({target['active_instance_id']}) "
                f"กรุณา terminate ก่อน (DELETE /instances/{target['active_instance_id']})"
            ),
        )

    delete_user_record(user_id)
    return {"message": f"User '{target.get('username', user_id)}' deleted successfully."}