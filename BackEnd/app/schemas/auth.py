from pydantic import BaseModel


class LoginRequest(BaseModel):
    student_no: str
    password: str


class LoginResponse(BaseModel):
    student_no: str
    name: str
    dept_id: int | None = None
    role: str = "student"
    message: str = "로그인 성공"
