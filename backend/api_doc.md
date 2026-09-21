# NetLab Backend - API Documentation (`api_doc.md`)

เอกสารสรุปรายละเอียด API Endpoints ทั้งหมดของระบบ NetLab Backend พร้อมระบบยืนยันตัวตน (JWT), การจัดการผู้ใช้และ VM บน Amazon DynamoDB และการบังคับโควตา **1 VM ต่อ 1 User**

---

## 📋 ตารางสรุปภาพรวม (Quick Reference)

| Method | Endpoint Path | ระดับสิทธิ์ (Auth) | คำอธิบาย |
| :--- | :--- | :---: | :--- |
| `GET` | `/` หรือ `/health` | Public | ตรวจสอบสถานะการทำงานของระบบ (Health Check) |
| `POST` | `/auth/login` | Public | เข้าสู่ระบบด้วย Username/Student ID และ Password |
| `GET` | `/auth/me` | **User** | ดูข้อมูลโปรไฟล์และสถานะ VM ปัจจุบันของผู้ใช้ |
| `POST` | `/instances` | **User** | สร้างและ Launch GNS3 VM บน EC2 (บังคับโควตา 1 VM) |
| `GET` | `/instances` | **User** | ดูรายการ VM (นักศึกษาเห็นเฉพาะของตนเอง, Admin เห็นทั้งหมด) |
| `POST` | `/instances/{instance_id}/start` | **Owner / Admin** | เปิดเครื่อง VM ที่ Stop ไว้ |
| `POST` | `/instances/{instance_id}/stop` | **Owner / Admin** | ปิดเครื่อง VM ชั่วคราว (Stop) |
| `DELETE` | `/instances/{instance_id}` | **Owner / Admin** | ลบ (Terminate) VM ถาวร และคืนโควตา 1 VM ให้ผู้ใช้ |
| `POST` | `/admin/users` | **Admin Only** | สร้างบัญชีผู้ใช้ใหม่ใน DynamoDB |
| `GET` | `/admin/users` | **Admin Only** | ดูรายชื่อผู้ใช้ทั้งหมดในระบบ |

---

## 🔐 ระบบยืนยันตัวตน (Authentication & Sessions)

- รองรับ 2 รูปแบบ:
  1. **HTTP Authorization Header**: `Authorization: Bearer <token>`
  2. **HttpOnly Cookie**: คุกกี้ชื่อ `access_token` (ตั้งค่าให้อัตโนมัติเมื่อยิง `/auth/login`)
- รหัสผ่านถูกเข้ารหัสด้วย **Bcrypt**
- Token สร้างด้วยมาตรฐาน **JWT (HS256)** มีอายุ 24 ชั่วโมง (1440 นาที)

---

## 🛠️ รายละเอียดของแต่ละ Endpoint

### 1. หมวดระบบและการตรวจสอบ (System & Health)

#### `GET /health` หรือ `GET /`
* **คำอธิบาย**: ตรวจสอบว่า Backend API พร้อมให้บริการหรือไม่
* **Authentication**: ไม่ต้องใช้
* **Response (200 OK)**:
  ```json
  {
    "status": "ok",
    "service": "netlab-backend"
  }
  ```

---

### 2. หมวดการเข้าสู่ระบบ (Authentication)

#### `POST /auth/login`
* **คำอธิบาย**: เข้าสู่ระบบด้วย Username หรือ Student ID พร้อมรหัสผ่าน
* **Authentication**: ไม่ต้องใช้
* **Request Body** (`application/json`):
  ```json
  {
    "identifier": "student01",
    "password": "mySecretPassword123"
  }
  ```
* **Response (200 OK)**:
  * บราวเซอร์จะได้รับคุกกี้ `access_token` (HttpOnly, SameSite=Lax, Max-Age 24h)
  * ได้รับ JSON Response:
    ```json
    {
      "access_token": "eyJhbGciOiJIUzI1Ni...",
      "token_type": "bearer",
      "user": {
        "user_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
        "username": "student01",
        "student_id": "6410001",
        "full_name": "Somchai Student",
        "role": "student",
        "active_instance_id": null,
        "created_at": "2026-09-20T14:00:00.000Z",
        "updated_at": "2026-09-20T14:00:00.000Z"
      }
    }
    ```
* **Error**: `401 Unauthorized` หากชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง

#### `GET /auth/me`
* **คำอธิบาย**: ดึงข้อมูลล่าสุดของผู้ใช้ที่ล็อกอินอยู่ รวมถึง `active_instance_id` ของ VM ที่ถือครอง
* **Authentication**: ต้องส่ง Bearer Token หรือแนบคุกกี้ `access_token`
* **Response (200 OK)**:
  ```json
  {
    "user_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "username": "student01",
    "student_id": "6410001",
    "full_name": "Somchai Student",
    "role": "student",
    "active_instance_id": "i-0123456789abcdef0",
    "created_at": "2026-09-20T14:00:00.000Z",
    "updated_at": "2026-09-20T14:15:00.000Z"
  }
  ```
* **Error**: `401 Unauthorized` หากไม่มี Token หรือ Token หมดอายุ

---

### 3. หมวดจัดการ GNS3 VM (Instance Management)

#### `POST /instances`
* **คำอธิบาย**: ร้องขอสร้างและ Launch GNS3 VM ใหม่บน AWS EC2
* **Authentication**: ต้องล็อกอิน (นักศึกษา, ผู้สอน, หรือ Admin)
* **Request Body** (`application/json`):
  ```json
  {
    "instance_name": "gns3-lab1-student01",
    "instance_type": "t2.micro", // (Optional) หากไม่ระบุจะใช้ค่า Default จาก .env
    "ami_id": "ami-xxxxxxxxxxxxxxxxx" // (Optional) หากไม่ระบุจะใช้ Default GNS3 AMI
  }
  ```
* **เงื่อนไขสำคัญ (Business Rules)**:
  1. **Atomic 1-VM Limit**: ตรวจสอบและล็อกผ่าน DynamoDB Conditional Update หากผู้ใช้มี VM ใช้งานอยู่แล้ว (ไม่ว่าจะสถานะ pending, running หรือ stopped) จะถูกปฏิเสธด้วย `400 Bad Request` ทันที
  2. **Max Project Concurrency**: หากจำนวน instance รวมทั้งโปรเจคเกินกว่า `MAX_CONCURRENT_INSTANCES` จะคืนค่า `429 Too Many Requests`
* **Response (201 Created)**:
  ```json
  {
    "instance_id": "i-0123456789abcdef0",
    "name": "gns3-lab1-student01",
    "state": "pending",
    "instance_type": "t2.micro",
    "public_ip": null,
    "private_ip": "172.31.10.5",
    "launch_time": "2026-09-20T14:10:00.000Z",
    "student_id": "6410001",
    "user_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "created_at": "2026-09-20T14:10:00.000Z",
    "terminated_at": null
  }
  ```

#### `GET /instances`
* **คำอธิบาย**: ดูรายการ VM และสถานะปัจจุบัน (Sync กับ AWS EC2 แบบ Real-time)
* **Authentication**: ต้องล็อกอิน
* **Query Parameters**: `student_id: Optional[str]` (เฉพาะ Admin ใช้กรองดูเฉพาะคนได้)
* **พฤติกรรม**:
  * **นักศึกษาทั่วไป**: จะเห็นเฉพาะ VM ของตนเองเท่านั้น
  * **Admin**: จะเห็น VM ทั้งหมดของทุกคนในระบบ
* **Response (200 OK)**:
  ```json
  {
    "count": 1,
    "instances": [
      {
        "instance_id": "i-0123456789abcdef0",
        "name": "gns3-lab1-student01",
        "state": "running",
        "instance_type": "t2.micro",
        "public_ip": "54.200.12.34",
        "private_ip": "172.31.10.5",
        "launch_time": "2026-09-20T14:10:00.000Z",
        "student_id": "6410001",
        "user_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
        "created_at": "2026-09-20T14:10:00.000Z",
        "terminated_at": null
      }
    ]
  }
  ```

#### `POST /instances/{instance_id}/start`
* **คำอธิบาย**: สั่งเปิดเครื่อง instance ที่ถูกหยุด (stopped) ไว้
* **Authentication**: ต้องเป็นเจ้าของ VM เครื่องนี้ หรือมี Role เป็น Admin
* **Error**: `403 Forbidden` หากพยายามสั่งเปิด VM ของผู้อื่น
* **Response (200 OK)**:
  ```json
  {
    "instance_id": "i-0123456789abcdef0",
    "state": "pending",
    "message": "instance กำลังเริ่มทำงาน"
  }
  ```

#### `POST /instances/{instance_id}/stop`
* **คำอธิบาย**: สั่งปิดเครื่อง instance ชั่วคราว (ข้อมูลในดิสก์ยังอยู่ ยังคงนับเป็น 1 VM ของผู้ใช้)
* **Authentication**: ต้องเป็นเจ้าของ VM เครื่องนี้ หรือมี Role เป็น Admin
* **Error**: `403 Forbidden` หากไม่ใช่เจ้าของ
* **Response (200 OK)**:
  ```json
  {
    "instance_id": "i-0123456789abcdef0",
    "state": "stopping",
    "message": "instance กำลังปิดเครื่อง"
  }
  ```

#### `DELETE /instances/{instance_id}`
* **คำอธิบาย**: ลบ (Terminate) instance ออกจาก AWS EC2 ถาวร และ**ปลดล็อกโควตา 1 VM ให้ผู้ใช้**
* **Authentication**: ต้องเป็นเจ้าของ VM เครื่องนี้ หรือมี Role เป็น Admin
* **พฤติกรรมในระบบ**:
  1. สั่ง Terminate ไปยัง AWS EC2
  2. อัปเดตสถานะในตาราง `netlab_instances` เป็น `terminated` พร้อมบันทึก `terminated_at`
  3. เคลียร์ค่า `active_instance_id = None` ในตาราง `netlab_users` แบบอัตโนมัติ ทำให้ผู้ใช้สามารถสร้าง VM ตัวใหม่ได้ทันที
* **Response (200 OK)**:
  ```json
  {
    "instance_id": "i-0123456789abcdef0",
    "state": "shutting-down",
    "message": "instance กำลังถูกลบ (terminate) และปล่อยโควตา VM เรียบร้อยแล้ว"
  }
  ```

---

### 4. หมวดการจัดการผู้ใช้สำหรับผู้ดูแลระบบ (Admin Management)

#### `POST /admin/users`
* **คำอธิบาย**: สร้างบัญชีผู้ใช้ใหม่ลงในฐานข้อมูล DynamoDB
* **Authentication**: เฉพาะผู้ใช้ที่มี Role เป็น `admin` เท่านั้น
* **Request Body** (`application/json`):
  ```json
  {
    "username": "student02",
    "student_id": "6410002",
    "password": "SecurePassword123!",
    "full_name": "Somying Student",
    "role": "student" // "student", "instructor", หรือ "admin"
  }
  ```
* **Response (201 Created)**:
  ```json
  {
    "user_id": "550e8400-e29b-41d4-a716-446655440000",
    "username": "student02",
    "student_id": "6410002",
    "full_name": "Somying Student",
    "role": "student",
    "active_instance_id": null,
    "created_at": "2026-09-20T14:30:00.000Z",
    "updated_at": "2026-09-20T14:30:00.000Z"
  }
  ```
* **Error**:
  * `403 Forbidden` หากผู้เรียกไม่มีสิทธิ์ Admin
  * `400 Bad Request` หาก `username` หรือ `student_id` ซ้ำกับที่มีอยู่แล้ว

#### `GET /admin/users`
* **คำอธิบาย**: ดูรายชื่อผู้ใช้ทั้งหมดในระบบ NetLab
* **Authentication**: เฉพาะผู้ใช้ที่มี Role เป็น `admin` เท่านั้น
* **Response (200 OK)**: Array ของรายการ `UserResponse`
* **Error**: `403 Forbidden` หากผู้เรียกไม่มีสิทธิ์ Admin
