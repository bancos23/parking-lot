from pydantic import BaseModel, EmailStr


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    first_name: str
    last_name: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class AccountResponse(BaseModel):
    id: int
    email: str
    first_name: str
    last_name: str
    role: str

    model_config = {"from_attributes": True}


class MessageResponse(BaseModel):
    message: str
