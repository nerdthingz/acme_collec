from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class AppError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.message = message
        self.status = status


def register_error_handlers(app: FastAPI):
    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, error: AppError):
        return JSONResponse(status_code=error.status, content={"detail": error.message})