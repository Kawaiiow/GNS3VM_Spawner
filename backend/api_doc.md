# NetLab Cloud - Backend API Documentation (`api_doc.md`)

> **API Version:** `2.1.0`  
> **Backend Framework:** FastAPI / Python 3.10+  
> **Database:** Amazon DynamoDB (Reduced Schema with single `UserIdIndex` on instances)  
> **Authentication:** JWT (HS256) via Bearer Token & HttpOnly Cookies  
> **Interactive Docs (Swagger UI):** `http://localhost:8000/docs` (หรือ `http://<HOST>:8000/docs`)

---

## 📋 สรุปรายการ Endpoint ทั้งหมด (Quick Reference)

| Method | Endpoint Path | สิทธิ์การเข้าถึง (Auth) | คำอธิบายสั้น |
| :--- | :--- | :---: | :--- |
| `GET` | `/` หรือ `/health` | Public | ตรวจสอบสถานะการทำงานของระบบ (Health Check) |
| `POST` | `/auth/login` | Public | เข้าสู่ระบบด้วย Username/Member ID และ Password |
| `GET` | `/auth/me` | **Authenticated User** | ดูข้อมูลโปรไฟล์และสถานะ VM ปัจจุบันของผู้ใช้ที่ล็อกอิน |
| `GET` | `/exercises` | Public | ดูรายการแบบฝึกหัด Lab (รองรับ filter `only_active`) |
| `GET` | `/exercises/{exercise_id}` | Public | ดูรายละเอียดของแบบฝึกหัด Lab รายตัว |
| `POST` | `/exercises` | **Instructor / Admin** | สร้างแบบฝึกหัด Lab ใหม่ |
| `POST` | `/instances` | **Authenticated User** | สร้างและ Launch GNS3 VM บน EC2 (บังคับโควตา 1 VM) |
| `GET` | `/instances` | **Authenticated User** | ดูรายการ VM (นักศึกษาเห็นของตนเอง, Admin เห็นทั้งหมด) |
| `POST` | `/instances/{instance_id}/start` | **Owner / Admin** | สั่งเปิดเครื่อง (Start) VM ที่ Stop ไว้ |
| `POST` | `/instances/{instance_id}/stop` | **Owner / Admin** | สั่งปิดเครื่อง (Stop) VM ชั่วคราว |
| `DELETE` | `/instances/{instance_id}` | **Owner / Admin** | Terminate VM ออกจาก EC2 และคืนโควตา 1 VM ทันที |
| `POST` | `/admin/users` | **Admin Only** | สร้างบัญชีผู้ใช้ใหม่ใน DynamoDB |
| `GET` | `/admin/users` | **Admin Only** | ดูรายชื่อผู้ใช้ทั้งหมดในระบบ |

---

## 🔐 ข้อมูลระบบยืนยันตัวตน (Authentication & Authorization)

ระบบรองรับการส่ง Token ผ่าน 2 ช่องทาง:
1. **HTTP Authorization Header**: `Authorization: Bearer <access_token>`
2. **HttpOnly Cookie**: คุกกี้ชื่อ `access_token` (ตั้งค่าให้อัตโนมัติเมื่อเรียก `/auth/login` มีอายุ 24 ชั่วโมง)

### Token Claims (Payload):
```json
{
  "sub": "<user_id>",
  "username": "<username>",
  "member_id": "<member_id>",
  "role": "student | instructor | admin",
  "exp": 1727500000
}
```

### ระดับสิทธิ์ (Roles):
- `student`: ดู/ทำ Lab, ขอสร้าง VM ได้ 1 เครื่อง, ควบคุม VM ของตนเองได้เท่านั้น
- `instructor`: มีสิทธิ์เหมือน student + สามารถสร้างและจัดการแบบฝึกหัด Lab (`/exercises`) ได้
- `admin`: มีสิทธิ์สูงสุด จัดการผู้ใช้ทั้งหมด (`/admin/users`), ควบคุมและดู VM ของทุกคนในระบบได้

---

## 🛠️ รายละเอียด Endpoint ฉบับสมบูรณ์ (API Specifications)

### 1. หมวดระบบและการตรวจสอบ (System & Health)

#### `GET /health` หรือ `GET /`
* **คำอธิบาย**: ตรวจสอบสถานะการเชื่อมต่อและความพร้อมของเซิร์ฟเวอร์
* **Authentication**: ไม่ต้องใช้
* **Response (200 OK)**:
  ```json
  {
    "status": "ok",
    "service": "netlab-backend"
  }
  ```

---

### 2. หมวดการเข้าสู่ระบบและโปรไฟล์ (Authentication)

#### `POST /auth/login`
* **คำอธิบาย**: เข้าสู่ระบบด้วยชื่อผู้ใช้ (`username`) หรือรหัสประจำตัว (`member_id`) และรหัสผ่าน
* **Authentication**: ไม่ต้องใช้
* **Request Body** (`application/json`):
  ```json
  {
    "identifier": "student01", // ใส่ได้ทั้ง username (เช่น student01) หรือ member_id (เช่น 6410001)
    "password": "mySecretPassword123"
  }
  ```
* **Response (200 OK)**:
  * บราวเซอร์จะได้รับคุกกี้ `access_token` (HttpOnly, SameSite=Lax, Max-Age 24h)
  * ได้รับ JSON Response:
    ```json
    {
      "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
      "token_type": "bearer",
      "user": {
        "user_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
        "username": "student01",
        "member_id": "6410001",
        "role": "student",
        "active_instance_id": null,
        "created_at": "2026-09-27T10:00:00.000Z",
        "updated_at": "2026-09-27T10:00:00.000Z"
      }
    }
    ```
* **Error Responses**:
  * `401 Unauthorized`: `"ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง"`

#### `GET /auth/me`
* **คำอธิบาย**: ดึงข้อมูลโปรไฟล์ล่าสุดของผู้ใช้ที่กำลังล็อกอิน รวมถึงสถานะ `active_instance_id` ของ VM ที่ถือครอง
* **Authentication**: ต้องส่ง `Authorization: Bearer <token>` หรือแนบคุกกี้ `access_token`
* **Response (200 OK)**:
  ```json
  {
    "user_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "username": "student01",
    "member_id": "6410001",
    "role": "student",
    "active_instance_id": "i-0123456789abcdef0",
    "created_at": "2026-09-27T10:00:00.000Z",
    "updated_at": "2026-09-27T10:15:00.000Z"
  }
  ```
* **Error Responses**:
  * `401 Unauthorized`: Token ไม่ถูกต้อง, หมดอายุ, หรือไม่ได้เข้าสู่ระบบ

---

### 3. หมวดแบบฝึกหัด Lab (Exercises)

#### `GET /exercises`
* **คำอธิบาย**: ดูรายการแบบฝึกหัด Lab ทั้งหมดในระบบ
* **Authentication**: ไม่ต้องใช้
* **Query Parameters**:
  * `only_active` (boolean, optional, default: `true`): ถ้าเป็น `true` จะแสดงเฉพาะแบบฝึกหัดที่เปิดให้ทำ (`is_active = true`)
* **Response (200 OK)**:
  ```json
  {
    "count": 1,
    "exercises": [
      {
        "exercise_id": "e2c342f1-6789-4bc5-a123-999988887777",
        "instructor_id": "inst-uuid-1",
        "title": "Lab 1: Basic OSPF Routing",
        "description": "Configure single-area OSPF routing across 3 Cisco routers",
        "ami_id": "ami-0123456789abcdef0",
        "status": "available",
        "is_active": true,
        "created_at": "2026-09-27T10:00:00.000Z"
      }
    ]
  }
  ```

#### `GET /exercises/{exercise_id}`
* **คำอธิบาย**: ดูรายละเอียดของแบบฝึกหัด Lab ตัวที่ระบุ
* **Authentication**: ไม่ต้องใช้
* **Response (200 OK)**:
  ```json
  {
    "exercise_id": "e2c342f1-6789-4bc5-a123-999988887777",
    "instructor_id": "inst-uuid-1",
    "title": "Lab 1: Basic OSPF Routing",
    "description": "Configure single-area OSPF routing across 3 Cisco routers",
    "ami_id": "ami-0123456789abcdef0",
    "status": "available",
    "is_active": true,
    "created_at": "2026-09-27T10:00:00.000Z"
  }
  ```
* **Error Responses**:
  * `404 Not Found`: ไม่พบแบบฝึกหัดที่ระบุ

#### `POST /exercises`
* **คำอธิบาย**: สร้างแบบฝึกหัด Lab ใหม่
* **Authentication**: เฉพาะผู้ใช้ที่มี Role เป็น `instructor` หรือ `admin`
* **Request Body** (`application/json`):
  ```json
  {
    "title": "Lab 2: BGP Peering & Policy",
    "description": "Lab exercise for configuring eBGP and route-maps",
    "ami_id": "ami-xxxxxxxxxxxxxxxxx" // (Optional) ถ้าไม่ระบุจะใช้ DEFAULT_AMI_ID จากระบบ
  }
  ```
* **Response (201 Created)**:
  ```json
  {
    "exercise_id": "f5a6b7c8-1111-2222-3333-444455556666",
    "instructor_id": "inst-uuid-1",
    "title": "Lab 2: BGP Peering & Policy",
    "description": "Lab exercise for configuring eBGP and route-maps",
    "ami_id": "ami-xxxxxxxxxxxxxxxxx",
    "status": "available",
    "is_active": true,
    "created_at": "2026-09-27T11:00:00.000Z"
  }
  ```
* **Error Responses**:
  * `403 Forbidden`: ผู้เรียกไม่ใช่ผู้สอนหรือแอดมิน

---

### 4. หมวดจัดการ GNS3 VM (Instance Management)

#### `POST /instances`
* **คำอธิบาย**: ขอสร้างและ Launch GNS3 VM ใหม่บน AWS EC2
* **Authentication**: ต้องล็อกอิน (ทุก Role)
* **Request Body** (`application/json`):
  ```json
  {
    "instance_name": "gns3-student01-lab1",
    "exercise_id": "e2c342f1-6789-4bc5-a123-999988887777", // (Optional) ระบุเพื่อดึง AMI ของ Lab นั้น
    "instance_type": "t2.micro", // (Optional) Default: t2.micro จาก .env
    "ami_id": "ami-xxxxxxxxxxxxxxxxx" // (Optional) Default: ดึงจาก exercise หรือ default_ami_id
  }
  ```
* **เงื่อนไขสำคัญ (Business Rules)**:
  1. **Atomic 1-VM Limit**: ผู้ใช้ 1 คนสามารถมี VM ใช้งานได้**เพียง 1 เครื่องเท่านั้น** (ไม่ว่าจะสถานะ pending, running หรือ stopped) หากพยายามสร้างเครื่องที่สองจะได้รับ `400 Bad Request` ทันที
  2. **Reduced Schema**: บันทึกเฉพาะ `user_id` ลงในตาราง `netlab_instances` และใช้ GSI เดียว (`UserIdIndex`) เพื่อลดความซ้ำซ้อนและประหยัดค่าใช้จ่าย
* **Response (201 Created)**:
  ```json
  {
    "instance_id": "i-0123456789abcdef0",
    "user_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "exercise_id": "e2c342f1-6789-4bc5-a123-999988887777",
    "name": "gns3-student01-lab1",
    "state": "pending",
    "instance_type": "t2.micro",
    "public_ip": null,
    "private_ip": "172.31.10.5",
    "launch_time": "2026-09-27T12:00:00.000Z",
    "created_at": "2026-09-27T12:00:00.000Z",
    "terminated_at": null
  }
  ```
* **Error Responses**:
  * `400 Bad Request`: `"User already owns an active VM instance (...). Every user is limited to 1 active VM."`
  * `429 Too Many Requests`: จำนวนเครื่องรวมทั้งโปรเจกต์เกินกว่า `MAX_CONCURRENT_INSTANCES`

#### `GET /instances`
* **คำอธิบาย**: ดูรายการ VM และสถานะปัจจุบัน (พร้อมดึงสถานะ Real-time ล่าสุดจาก AWS EC2)
* **Authentication**: ต้องล็อกอิน
* **พฤติกรรมการแสดงผล**:
  * **นักศึกษา / ผู้สอน**: จะเห็นเฉพาะ VM เครื่องของตนเอง (`user_id`)
  * **Admin**: จะเห็น VM ทั้งหมดของทุกคนในระบบ
* **Response (200 OK)**:
  ```json
  {
    "count": 1,
    "instances": [
      {
        "instance_id": "i-0123456789abcdef0",
        "user_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
        "exercise_id": "e2c342f1-6789-4bc5-a123-999988887777",
        "name": "gns3-student01-lab1",
        "state": "running",
        "instance_type": "t2.micro",
        "public_ip": "54.200.12.34",
        "private_ip": "172.31.10.5",
        "launch_time": "2026-09-27T12:00:00.000Z",
        "created_at": "2026-09-27T12:00:00.000Z",
        "terminated_at": null
      }
    ]
  }
  ```

#### `POST /instances/{instance_id}/start`
* **คำอธิบาย**: สั่งเปิดเครื่อง (Start) instance ที่ถูกหยุด (stopped) ไว้
* **Authentication**: ต้องเป็นเจ้าของเครื่อง หรือ Admin
* **Response (200 OK)**:
  ```json
  {
    "instance_id": "i-0123456789abcdef0",
    "state": "pending",
    "message": "instance กำลังเริ่มทำงาน"
  }
  ```
* **Error Responses**:
  * `403 Forbidden`: คุณไม่มีสิทธิ์จัดการ VM ของผู้ใช้อื่น

#### `POST /instances/{instance_id}/stop`
* **คำอธิบาย**: สั่งปิดเครื่อง (Stop) instance ชั่วคราว (ดิสก์ยังคงอยู่ และยังคงนับเป็น 1 VM ของผู้ใช้)
* **Authentication**: ต้องเป็นเจ้าของเครื่อง หรือ Admin
* **Response (200 OK)**:
  ```json
  {
    "instance_id": "i-0123456789abcdef0",
    "state": "stopping",
    "message": "instance กำลังปิดเครื่อง"
  }
  ```
* **Error Responses**:
  * `403 Forbidden`: คุณไม่มีสิทธิ์จัดการ VM ของผู้ใช้อื่น

#### `DELETE /instances/{instance_id}`
* **คำอธิบาย**: สั่งลบ (Terminate) instance ออกจาก AWS EC2 ถาวร และ**ปลดล็อกโควตา 1 VM ทันที**
* **Authentication**: ต้องเป็นเจ้าของเครื่อง หรือ Admin
* **พฤติกรรมในระบบ**:
  1. สั่ง Terminate ไปยัง AWS EC2
  2. ปรับสถานะใน `netlab_instances` เป็น `terminated` พร้อมบันทึก `terminated_at`
  3. เคลียร์ค่า `active_instance_id = None` ใน `netlab_users` เพื่อให้ผู้ใช้สามารถขอสร้าง VM เครื่องใหม่ได้ทันที
* **Response (200 OK)**:
  ```json
  {
    "instance_id": "i-0123456789abcdef0",
    "state": "shutting-down",
    "message": "instance กำลังถูกลบ (terminate) และปล่อยโควตา VM เรียบร้อยแล้ว"
  }
  ```
* **Error Responses**:
  * `403 Forbidden`: คุณไม่มีสิทธิ์จัดการ VM ของผู้ใช้อื่น

---

### 5. หมวดการจัดการผู้ใช้สำหรับผู้ดูแลระบบ (Admin Management)

#### `POST /admin/users`
* **คำอธิบาย**: สร้างบัญชีผู้ใช้ใหม่ลงในฐานข้อมูล DynamoDB
* **Authentication**: เฉพาะผู้ใช้ที่มี Role เป็น `admin` เท่านั้น
* **Request Body** (`application/json`):
  ```json
  {
    "username": "student02",
    "member_id": "6410002",
    "password": "SecurePassword123!",
    "role": "student" // "student", "instructor", หรือ "admin"
  }
  ```
* **Response (201 Created)**:
  ```json
  {
    "user_id": "550e8400-e29b-41d4-a716-446655440000",
    "username": "student02",
    "member_id": "6410002",
    "role": "student",
    "active_instance_id": null,
    "created_at": "2026-09-27T13:00:00.000Z",
    "updated_at": "2026-09-27T13:00:00.000Z"
  }
  ```
* **Error Responses**:
  * `403 Forbidden`: ไม่มีสิทธิ์แอดมิน
  * `400 Bad Request`: Username หรือ Member ID ซ้ำกับที่มีอยู่ในระบบ

#### `GET /admin/users`
* **คำอธิบาย**: ดูรายชื่อผู้ใช้ทั้งหมดในระบบ NetLab
* **Authentication**: เฉพาะผู้ใช้ที่มี Role เป็น `admin` เท่านั้น
* **Response (200 OK)**: Array ของรายการ `UserResponse`
* **Error Responses**:
  * `403 Forbidden`: ไม่มีสิทธิ์แอดมิน
