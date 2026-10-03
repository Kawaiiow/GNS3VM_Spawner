from datetime import datetime
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Response, status
from fastapi.middleware.cors import CORSMiddleware

from app import ec2_service
from app.auth import (
    create_access_token,
    get_current_admin_user,
    get_current_instructor_or_admin,
    get_current_user,
    hash_password,
    verify_password,
)
from app.config import get_settings
from app.dynamodb_service import (
    create_exercise_record,
    create_user,
    delete_exercise_record,
    get_exercise_record,
    get_instance_record,
    get_user_by_id,
    get_user_by_identifier,
    list_all_exercises,
    list_all_users,
    update_exercise_status,
)
from app.models import (
    ExerciseCreate,
    ExerciseListResponse,
    ExerciseResponse,
    InstanceActionResponse,
    InstanceInfo,
    InstanceListResponse,
    LaunchInstanceRequest,
    LoginRequest,
    TokenResponse,
    UserCreate,
    UserInDB,
    UserResponse,
    UserRole,
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
        created_at=user_dict["created_at"],
        updated_at=user_dict["updated_at"],
    )

    return TokenResponse(access_token=token, token_type="bearer", user=user_resp)


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
    current_user: UserInDB = Depends(get_current_instructor_or_admin),
):
    """
    สร้างแบบฝึกหัด Lab ใหม่ (เฉพาะ Instructor หรือ Admin)
    - หากระบุ instance_id หรือมี active_instance_id อยู่ ระบบจะสั่ง AWS EC2 ทำ Snapshot (AMI) จาก VM นั้น
    - หรือหากมี ami_id อยู่แล้ว ก็สามารถระบุ ami_id โดยตรงได้
    """
    target_ami = payload.ami_id
    initial_status = "available"

    # หากไม่มีการส่ง ami_id มาโดยตรง ให้ทำ Snapshot จาก EC2 VM ของอาจารย์
    if not target_ami:
        target_instance_id = payload.instance_id or current_user.active_instance_id
        if not target_instance_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="กรุณาระบุ instance_id หรือเปิด VM เพื่อสร้างแบบฝึกหัดจาก Snapshot (หรือระบุ ami_id)",
            )

        _verify_instance_ownership(target_instance_id, current_user)

        sanitized_title = "".join(
            c for c in payload.title if c.isalnum() or c in ("-", "_")
        ).strip() or "exercise"
        img_name = f"ex-{sanitized_title[:20]}-{int(datetime.now().timestamp())}"

        target_ami = ec2_service.create_instance_image(
            instance_id=target_instance_id,
            name=img_name,
            description=payload.description or f"Snapshot exercise for {payload.title}",
        )
        initial_status = "pending"

    item = create_exercise_record(
        instructor_id=current_user.user_id,
        title=payload.title,
        description=payload.description,
        ami_id=target_ami,
        status=initial_status,
        is_active=True,
    )
    return ExerciseResponse(**item)


@app.delete("/exercises/{exercise_id}", status_code=200)
def delete_exercise(
    exercise_id: str,
    current_user: UserInDB = Depends(get_current_instructor_or_admin),
):
    """ลบแบบฝึกหัด Lab (เฉพาะเจ้าของแบบฝึกหัด หรือ Admin)"""
    record = get_exercise_record(exercise_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Exercise '{exercise_id}' not found.",
        )

    if (
        current_user.role != UserRole.ADMIN
        and record.get("instructor_id") != current_user.user_id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="คุณไม่มีสิทธิ์ลบแบบฝึกหัดของผู้สอนท่านอื่น",
        )

    if record.get("ami_id"):
        ec2_service.deregister_image(record["ami_id"])

    delete_exercise_record(exercise_id)
    return {"message": f"Exercise '{exercise_id}' deleted successfully."}


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
    """
    return ec2_service.launch_instance(
        user_id=current_user.user_id,
        instance_name=payload.instance_name,
        instance_type=payload.instance_type,
        ami_id=payload.ami_id,
        exercise_id=payload.exercise_id,
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
        instances = ec2_service.list_instances(user_id=current_user.user_id)

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
            created_at=u["created_at"],
            updated_at=u["updated_at"],
        )
        for u in users
    ]
