from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    student_no: str = Field(..., max_length=20)
    password: str = Field(..., max_length=128)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    student_no: str
    name: str
    dept_id: int | None = None
    role: str = "student"
    message: str = "로그인 성공"
