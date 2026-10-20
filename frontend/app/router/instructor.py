from fastapi import APIRouter, Request, Form, status
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse, HTMLResponse, Response, JSONResponse
from dotenv import load_dotenv
import httpx, os, yaml

load_dotenv()

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


@router.get("/exercise/{exercise_id}/rubric")
def render_instructor_rubric(request: Request, exercise_id: str):
    token = request.cookies.get("access_token", "")
    try:
        ex_resp = httpx.get(f"{BACKEND_URL}/exercises/{exercise_id}", cookies={"access_token": token}, timeout=10.0)
    except:
        return template.TemplateResponse(request=request, name="503.html", status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    if ex_resp.status_code in (401, 403):
        return template.TemplateResponse(request=request, name="404.html", status_code=status.HTTP_404_NOT_FOUND)
    if ex_resp.status_code != 200:
        return HTMLResponse("<script>alert('ไม่พบแบบฝึกหัด');location.href='/instructor/dashboard';</script>")

    exercise = ex_resp.json()
    rubric_yaml = ""
    try:
        r_resp = httpx.get(f"{BACKEND_URL}/exercises/{exercise_id}/rubric", cookies={"access_token": token}, timeout=10.0)
        if r_resp.status_code == 200:
            rubric_yaml = yaml.dump(r_resp.json(), allow_unicode=True, sort_keys=False)
    except:
        pass

    if not rubric_yaml:
        # Default starter template
        rubric_yaml = f"""version: "1.0"
title: "{exercise.get('title', 'Exercise')}"
max_score: 100
passing_score: 60
feedback_mode: "detailed"

tasks:
  - id: "t1"
    name: "Router R1 IP Configuration"
    node: "R1"
    device_type: "cisco"
    points: 50
    checks:
      - type: "config_regex"
        description: "Verify Gi0/0 has configured IP"
        pattern: "interface GigabitEthernet0/0\\\\s+ip address 192\\\\.168\\\\.1\\\\.1 255\\\\.255\\\\.255\\\\.0"
        hint: "Configure 'ip address 192.168.1.1 255.255.255.0' under GigabitEthernet0/0"
  - id: "t2"
    name: "End-to-End Ping"
    node: "R1"
    device_type: "cisco"
    points: 50
    checks:
      - type: "ping"
        target_ip: "192.168.2.1"
        repeat: 5
        min_success_rate: 60
        hint: "Check static routes and link status between routers"
"""

    return template.TemplateResponse(
        request=request,
        name="instructor/rubric.html",
        context={"exercise": exercise, "rubric_yaml": rubric_yaml},
    )


@router.post("/exercise/{exercise_id}/rubric")
def handle_instructor_update_rubric(
    request: Request,
    exercise_id: str,
    rubric_yaml: str = Form(...),
    max_attempts: int = Form(0),
    passing_score: int = Form(60),
    feedback_mode: str = Form("detailed"),
    keep_score_policy: str = Form("highest"),
):
    token = request.cookies.get("access_token", "")
    payload = {
        "rubric_yaml": rubric_yaml,
        "max_attempts": max_attempts,
        "passing_score": passing_score,
        "feedback_mode": feedback_mode,
        "keep_score_policy": keep_score_policy,
    }
    try:
        resp = httpx.put(
            f"{BACKEND_URL}/exercises/{exercise_id}/rubric",
            json=payload,
            cookies={"access_token": token},
            timeout=15.0,
        )
    except:
        return template.TemplateResponse(request=request, name="503.html", status_code=status.HTTP_503_SERVICE_UNAVAILABLE)

    if resp.status_code != 200:
        err = resp.json().get("detail", "บันทึกเกณฑ์การตรวจไม่สำเร็จ")
        return HTMLResponse(f"<script>alert({err!r});history.back();</script>")

    return RedirectResponse(url=f"/instructor/exercise/{exercise_id}/rubric?saved=1", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/exercise/{exercise_id}/submissions")
def render_instructor_submissions(request: Request, exercise_id: str):
    token = request.cookies.get("access_token", "")
    try:
        ex_resp = httpx.get(f"{BACKEND_URL}/exercises/{exercise_id}", cookies={"access_token": token}, timeout=10.0)
        sub_resp = httpx.get(f"{BACKEND_URL}/exercises/{exercise_id}/submissions", cookies={"access_token": token}, timeout=10.0)
    except:
        return template.TemplateResponse(request=request, name="503.html", status_code=status.HTTP_503_SERVICE_UNAVAILABLE)

    if ex_resp.status_code in (401, 403) or sub_resp.status_code in (401, 403):
        return template.TemplateResponse(request=request, name="404.html", status_code=status.HTTP_404_NOT_FOUND)

    exercise = ex_resp.json() if ex_resp.status_code == 200 else {}
    submissions = sub_resp.json().get("submissions", []) if sub_resp.status_code == 200 else []

    return template.TemplateResponse(
        request=request,
        name="instructor/submissions.html",
        context={"exercise": exercise, "submissions": submissions},
    )


@router.get("/exercise/{exercise_id}/submissions/export")
def handle_instructor_export_submissions(request: Request, exercise_id: str):
    token = request.cookies.get("access_token", "")
    try:
        resp = httpx.get(
            f"{BACKEND_URL}/exercises/{exercise_id}/submissions/export",
            cookies={"access_token": token},
            timeout=20.0,
        )
    except:
        return template.TemplateResponse(request=request, name="503.html", status_code=status.HTTP_503_SERVICE_UNAVAILABLE)

    if resp.status_code != 200:
        return HTMLResponse("<script>alert('ไม่สามารถดาวน์โหลดไฟล์รายงานได้');history.back();</script>")

    return Response(
        content=resp.content,
        media_type="text/csv",
        headers={"Content-Disposition": resp.headers.get("Content-Disposition", f"attachment; filename=exercise_{exercise_id[:8]}_grades.csv")},
    )
