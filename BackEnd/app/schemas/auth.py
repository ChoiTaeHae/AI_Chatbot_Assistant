import re

from pydantic import BaseModel, Field, field_validator


class LoginRequest(BaseModel):
    student_no: str = Field(..., max_length=20)
    password: str = Field(..., max_length=128)


class SignupRequest(BaseModel):
    """회원가입 입력.

    role은 일부러 받지 않는다. 클라이언트가 보낸 값을 그대로 쓰면 가입 요청에
    role='admin'을 실어 보내는 것만으로 관리자가 된다(권한 상승). 서버가 항상 'student'로 만든다.
    """
    student_no: str = Field(..., min_length=4, max_length=20)
    password: str = Field(..., min_length=8, max_length=128)
    name: str = Field(..., min_length=1, max_length=20)
    dept_id: int                      # 졸업요건·장학금 판정이 학과 기준이라 가입 때 받는다

    @field_validator("student_no")
    @classmethod
    def _digits_only(cls, v: str) -> str:
        v = v.strip()
        if not re.fullmatch(r"\d{4,20}", v):
            raise ValueError("학번은 숫자만 입력해 주세요.")
        return v

    @field_validator("name")
    @classmethod
    def _clean_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("이름을 입력해 주세요.")
        return v

    @field_validator("password")
    @classmethod
    def _password_strength(cls, v: str) -> str:
        # 길이만 본다. 특수문자 강제는 기억하기 어려운 비밀번호를 만들고,
        # 결국 메모장에 적어 두게 만든다(NIST 800-63B도 복잡도 강제를 권하지 않는다).
        if len(v.strip()) < 8:
            raise ValueError("비밀번호는 8자 이상이어야 합니다.")
        return v


class DeptOption(BaseModel):
    id: int
    name: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    student_no: str
    name: str
    dept_id: int | None = None
    role: str = "student"
    message: str = "로그인 성공"
