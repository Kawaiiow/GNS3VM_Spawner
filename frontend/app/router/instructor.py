from fastapi import APIRouter, Request, Form, status
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse, HTMLResponse
import httpx, os

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")

router = APIRouter()
template = Jinja2Templates(directory="template")

@router.get("/dashboard")
def render_instructor_dashboard(request: Request):
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
    return template.TemplateResponse(request=request, name="instructor/dashboard.html", context={"user": response.json(), "exercises": exercises.json()["exercises"]})

@router.post("/instance/create")
def handle_instructor_create_instance(request: Request, exercise_id: str = Form(None)):
    try:
        response = httpx.post(f"{BACKEND_URL}/instances", json={"instance_name": f"gns3-{request.cookies.get('username')}-{'exercise' if exercise_id else 'sandbox'}", "exercise_id": exercise_id}, cookies={"access_token": request.cookies.get("access_token", "")}, timeout=10.0)
    except:
        return template.TemplateResponse(request=request, name="503.html", status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    if response.status_code != 201:
        return HTMLResponse("<script>alert('ไม่สามารถสร้างเครื่องใหม่ได้');location.href='/instructor/dashboard';</script>")
    return RedirectResponse(url="/instructor/dashboard", status_code=status.HTTP_303_SEE_OTHER)

@router.post("/instance/start")
def handle_instructor_start_instance(request: Request, instance_id: str = Form(...)):
    try:
        response = httpx.post(f"{BACKEND_URL}/instances/{instance_id}/start", cookies={"access_token": request.cookies.get("access_token", "")}, timeout=150.0)
    except:
        return template.TemplateResponse(request=request, name="503.html", status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    if response.status_code != 200:
        return HTMLResponse("<script>alert('ไม่สามารถเปิดเครื่องนี้ได้');location.href='/instructor/dashboard';</script>")
    return RedirectResponse(url="/instructor/dashboard", status_code=status.HTTP_303_SEE_OTHER)

@router.post("/instance/stop")
def handle_instructor_stop_instance(request: Request, instance_id: str = Form(...)):
    try:
        response = httpx.post(f"{BACKEND_URL}/instances/{instance_id}/stop", cookies={"access_token": request.cookies.get("access_token", "")}, timeout=10.0)
    except:
        return template.TemplateResponse(request=request, name="503.html", status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    if response.status_code != 200:
        return HTMLResponse("<script>alert('ไม่สามารถหยุดเครื่องนี้ได้');location.href='/instructor/dashboard';</script>")
    return RedirectResponse(url="/instructor/dashboard", status_code=status.HTTP_303_SEE_OTHER)

@router.post("/instance/delete")
def handle_instructor_delete_instance(request: Request, instance_id: str = Form(...)):
    try:
        response = httpx.delete(f"{BACKEND_URL}/instances/{instance_id}", cookies={"access_token": request.cookies.get("access_token", "")}, timeout=10.0)
    except:
        return template.TemplateResponse(request=request, name="503.html", status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    if response.status_code != 200:
        return HTMLResponse("<script>alert('ไม่สามารถลบเครื่องนี้ได้');location.href='/instructor/dashboard';</script>")
    return RedirectResponse(url="/instructor/dashboard", status_code=status.HTTP_303_SEE_OTHER)

@router.get("/exercise/create")
def render_instructor_create_exercise(request: Request, instance_id: str):
    try:
        response = httpx.get(f"{BACKEND_URL}/instances/{instance_id}/gns3/projects", cookies={"access_token": request.cookies.get("access_token", "")}, timeout=10.0)
    except:
        return template.TemplateResponse(request=request, name="503.html", status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    if response.status_code in (401, 403):
        return template.TemplateResponse(request=request, name="404.html", status_code=status.HTTP_404_NOT_FOUND)
    if response.status_code != 200:
        return HTMLResponse("<script>alert('ไม่สามารถสร้างเปิดหน้าเพิ่มแบบฝึกหัดใหม่ได้');location.href='/instructor/dashboard';</script>")
    return template.TemplateResponse(request=request, name="instructor/create.html", context={"instance_id": instance_id, "projects": response.json()["projects"]})

@router.post("/exercise/create")
def handle_instructor_create_exercise(request: Request, instance_id: str = Form(...), title: str = Form(...), description: str = Form(...), project_ids: list[str] = Form(alias="project_ids[]")):
    try:
        response = httpx.post(f"{BACKEND_URL}/exercises", json={"instance_id": instance_id, "title": title, "description": description, "description": description, "project_ids": project_ids}, cookies={"access_token": request.cookies.get("access_token", "")}, timeout=10.0)
    except:
        return template.TemplateResponse(request=request, name="503.html", status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    if response.status_code != 201:
        return HTMLResponse("<script>alert('ไม่สามารถเพิ่มแบบฝึกหัดใหม่ได้');history.back();</script>")
    return RedirectResponse(url="/instructor/dashboard", status_code=status.HTTP_303_SEE_OTHER)

@router.post("/exercise/delete")
def handle_instructor_delete_exercise(request: Request, exercise_id: str = Form(...)):
    try:
        response = httpx.delete(f"{BACKEND_URL}/exercises/{exercise_id}", cookies={"access_token": request.cookies.get("access_token", "")}, timeout=10.0)
    except:
        return template.TemplateResponse(request=request, name="503.html", status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    if response.status_code != 200:
        return HTMLResponse("<script>alert('ไม่สามารถลบแบบฝึกหัดได้');location.href='/instructor/dashboard';</script>")
    return RedirectResponse(url="/instructor/dashboard", status_code=status.HTTP_303_SEE_OTHER)
