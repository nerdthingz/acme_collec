from pydantic import BaseModel, EmailStr


class EmailUpdate(BaseModel):
    contact_email: EmailStr