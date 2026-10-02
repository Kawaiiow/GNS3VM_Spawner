from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from router import user, admin

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
template = Jinja2Templates(directory="template")

app.include_router(user.router)
app.include_router(admin.router, prefix="/admin")

@app.api_route("/{path:path}", methods=["GET", "POST"])
def catch_all(request: Request):
    return template.TemplateResponse(
        request=request,
        name="404.html"
    )
