from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

router = APIRouter()
template = Jinja2Templates(directory="template")

@router.get("/")
def render_home(request: Request):
    return template.TemplateResponse(
        request=request,
        name="home.html"
    )

@router.get("/signin")
def render_signin(request: Request):
    return template.TemplateResponse(
        request=request,
        name="signin.html"
    )
