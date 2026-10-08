from fastapi import APIRouter, Request, Form, status
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
import httpx

BACKEND_URL = "http://localhost:8000"

router = APIRouter()
template = Jinja2Templates(directory="template")

@router.get("/dashboard")
def render_admin_dashboard(request: Request):
    try:
        response = httpx.get(f"{BACKEND_URL}/admin/dashboard", cookies={"access_token": request.cookies.get("access_token", "")}, timeout=10.0)
    except:
        return template.TemplateResponse(request=request, name="503.html", status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    if response.status_code in (401, 403):
        return template.TemplateResponse(request=request, name="404.html", status_code=status.HTTP_404_NOT_FOUND)
    return template.TemplateResponse(request=request, name="admin/dashboard.html", context={"users": response.json()})

@router.get("/create")
def render_admin_create(request: Request):
    try:
        response = httpx.get(f"{BACKEND_URL}/auth/me", cookies={"access_token": request.cookies.get("access_token", "")}, timeout=10.0)
    except:
        return template.TemplateResponse(request=request, name="503.html", status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    if response.status_code in (401, 403):
        return template.TemplateResponse(request=request, name="404.html", status_code=status.HTTP_404_NOT_FOUND)
    return template.TemplateResponse(request=request, name="admin/create.html")

@router.post("/create")
def handle_admin_create(request: Request, name: str = Form(...), surname: str = Form(...), username: str = Form(...), member_id: str = Form(...), password: str = Form(...), role: str = Form(...)):
    try:
        response = httpx.post(f"{BACKEND_URL}/admin/users", json={"username": username, "member_id": member_id, "password": password, "full_name": f"{name} {surname}", "role": role}, cookies={"access_token": request.cookies.get("access_token", "")}, timeout=10.0)
    except:
        return template.TemplateResponse(request=request, name="503.html", status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    if response.status_code in (401, 403):
        return template.TemplateResponse(request=request, name="404.html", status_code=status.HTTP_404_NOT_FOUND)
    return RedirectResponse(url="/admin/dashboard" if response.status_code == 201 else "/admin/create", status_code=status.HTTP_303_SEE_OTHER)

@router.get("/update/{user_id}")
def render_admin_update(request: Request, user_id: str):
    try:
        response = httpx.get(f"{BACKEND_URL}/admin/users/{user_id}", cookies={"access_token": request.cookies.get("access_token", "")}, timeout=10.0)
    except:
        return template.TemplateResponse(request=request, name="503.html", status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    if response.status_code in (401, 403):
        return template.TemplateResponse(request=request, name="404.html", status_code=status.HTTP_404_NOT_FOUND)
    name, surname = response.json()["full_name"].split()
    return template.TemplateResponse(request=request, name="admin/update.html", context={"user": response.json(), "name": name, "surname": surname})

@router.post("/update/{user_id}")
def handle_admin_update(request: Request, user_id: str, name: str = Form(...), surname: str = Form(...), username: str = Form(...), member_id: str = Form(...), password: str = Form(""), role: str = Form(...)):
    try:
        response = httpx.patch(f"{BACKEND_URL}/admin/users/{user_id}", json={"username": username, "member_id": member_id, "password": password or None, "full_name": f"{name} {surname}", "role": role}, cookies={"access_token": request.cookies.get("access_token", "")}, timeout=10.0)
    except:
        return template.TemplateResponse(request=request, name="503.html", status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    if response.status_code in (401, 403):
        return template.TemplateResponse(request=request, name="404.html", status_code=status.HTTP_404_NOT_FOUND)
    return RedirectResponse(url="/admin/dashboard" if response.status_code == 200 else f"/admin/update/{user_id}", status_code=status.HTTP_303_SEE_OTHER)

@router.post("/delete/{user_id}")
def handle_admin_delete(request: Request, user_id: str):
    try:
        response = httpx.delete(f"{BACKEND_URL}/admin/users/{user_id}", cookies={"access_token": request.cookies.get("access_token", "")}, timeout=10.0)
    except:
        return template.TemplateResponse(request=request, name="503.html", status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    if response.status_code in (401, 403):
        return template.TemplateResponse(request=request, name="404.html", status_code=status.HTTP_404_NOT_FOUND)
    return RedirectResponse(url="/admin/dashboard", status_code=status.HTTP_303_SEE_OTHER)
