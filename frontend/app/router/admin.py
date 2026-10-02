from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

router = APIRouter()
template = Jinja2Templates(directory="template")

@router.get("/dashboard")
def render_admin_dashboard(request: Request):
    return template.TemplateResponse(
        request=request,
        name="admin/dashboard.html"
    )

@router.get("/create")
def render_admin_create(request: Request):
    return template.TemplateResponse(
        request=request,
        name="admin/create.html"
    )

@router.get("/update")
def render_admin_edit(request: Request):
    return template.TemplateResponse(
        request=request,
        name="admin/update.html"
    )
