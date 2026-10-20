from fastapi import APIRouter, Request, Form, status
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse
from dotenv import load_dotenv
import httpx, os

load_dotenv()

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")

router = APIRouter()
template = Jinja2Templates(directory="template")

@router.get("/dashboard")
def render_student_dashboard(request: Request):
    try:
        response = httpx.get(f"{BACKEND_URL}/instances", cookies={"access_token": request.cookies.get("access_token", "")}, timeout=10.0)
        exercises = httpx.get(f"{BACKEND_URL}/exercises", timeout=10.0)
    except:
        return template.TemplateResponse(request=request, name="503.html", status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    if response.status_code in (401, 403):
        return template.TemplateResponse(request=request, name="404.html", status_code=status.HTTP_404_NOT_FOUND)
    if response.status_code != 200:
        return HTMLResponse("<script>alert('ไม่สามารถโหลดข้อมูลแดชบอร์ดได้');</script>")
    if exercises.status_code != 200:
        return HTMLResponse("<script>alert('ไม่สามารถโหลดรายการแบบฝึกหัดได้');</script>")
    return template.TemplateResponse(request=request, name="student/dashboard.html", context={"user": response.json(), "exercises": exercises.json()["exercises"]})

@router.post("/instance/create")
def handle_student_create_instance(request: Request, exercise_id: str = Form(None)):
    try:
        response = httpx.post(f"{BACKEND_URL}/instances", json={"instance_name": f"gns3-{request.cookies.get('username')}-{'exercise' if exercise_id else 'sandbox'}", "exercise_id": exercise_id}, cookies={"access_token": request.cookies.get("access_token", "")}, timeout=10.0)
    except:
        return template.TemplateResponse(request=request, name="503.html", status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    if response.status_code != 201:
        return HTMLResponse("<script>alert('ไม่สามารถสร้างเครื่องใหม่ได้');location.href='/dashboard';</script>")
    return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)

@router.post("/instance/start")
def handle_student_start_instance(request: Request, instance_id: str = Form(...)):
    try:
        response = httpx.post(f"{BACKEND_URL}/instances/{instance_id}/start", cookies={"access_token": request.cookies.get("access_token", "")}, timeout=150.0)
    except:
        return template.TemplateResponse(request=request, name="503.html", status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    if response.status_code != 200:
        return HTMLResponse("<script>alert('ไม่สามารถเปิดเครื่องนี้ได้');location.href='/dashboard';</script>")
    return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)

@router.post("/instance/stop")
def handle_student_stop_instance(request: Request, instance_id: str = Form(...)):
    try:
        response = httpx.post(f"{BACKEND_URL}/instances/{instance_id}/stop", cookies={"access_token": request.cookies.get("access_token", "")}, timeout=10.0)
    except:
        return template.TemplateResponse(request=request, name="503.html", status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    if response.status_code != 200:
        return HTMLResponse("<script>alert('ไม่สามารถหยุดเครื่องนี้ได้');location.href='/dashboard';</script>")
    return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)

@router.post("/instance/extend")
def handle_student_extend_instance(request: Request, instance_id: str = Form(...)):
    try:
        response = httpx.post(f"{BACKEND_URL}/instances/{instance_id}/extend", cookies={"access_token": request.cookies.get("access_token", "")}, timeout=10.0)
    except:
        return template.TemplateResponse(request=request, name="503.html", status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    if response.status_code != 200:
        return HTMLResponse("<script>alert('ไม่สามารถเพิ่มเวลาเครื่องนี้ได้');location.href='/dashboard';</script>")
    return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)

@router.post("/instance/delete")
def handle_student_delete_instance(request: Request, instance_id: str = Form(...)):
    try:
        response = httpx.delete(f"{BACKEND_URL}/instances/{instance_id}", cookies={"access_token": request.cookies.get("access_token", "")}, timeout=10.0)
    except:
        return template.TemplateResponse(request=request, name="503.html", status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    if response.status_code != 200:
        return HTMLResponse("<script>alert('ไม่สามารถลบเครื่องนี้ได้');location.href='/dashboard';</script>")
    return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/instance/grade")
async def handle_student_grade_instance(request: Request):
    try:
        body = await request.json()
        instance_id = body.get("instance_id")
        if not instance_id:
            return JSONResponse(status_code=400, content={"status": "error", "message": "Missing instance_id"})
        response = httpx.post(
            f"{BACKEND_URL}/instances/{instance_id}/grade",
            cookies={"access_token": request.cookies.get("access_token", "")},
            timeout=190.0,
        )
        return JSONResponse(status_code=response.status_code, content=response.json())
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "message": f"ไม่สามารถติดต่อระบบตรวจข้อสอบได้: {str(e)}"})


@router.post("/instance/submit")
async def handle_student_submit_instance(request: Request):
    try:
        body = await request.json()
        instance_id = body.get("instance_id")
        if not instance_id:
            return JSONResponse(status_code=400, content={"status": "error", "message": "Missing instance_id"})
        response = httpx.post(
            f"{BACKEND_URL}/instances/{instance_id}/submit",
            cookies={"access_token": request.cookies.get("access_token", "")},
            timeout=190.0,
        )
        return JSONResponse(status_code=response.status_code, content=response.json())
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "message": f"ไม่สามารถส่งแบบฝึกหัดได้: {str(e)}"})


@router.get("/submissions/my")
def handle_student_my_submissions(request: Request, exercise_id: str = None):
    try:
        params = {"exercise_id": exercise_id} if exercise_id else {}
        response = httpx.get(
            f"{BACKEND_URL}/submissions/my",
            params=params,
            cookies={"access_token": request.cookies.get("access_token", "")},
            timeout=10.0,
        )
        return JSONResponse(status_code=response.status_code, content=response.json())
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})
