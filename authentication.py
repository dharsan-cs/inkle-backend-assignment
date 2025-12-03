from datetime import datetime ,timezone ,timedelta
from fastapi import Request ,HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv
from database import User
import bcrypt
import jwt
import os  

load_dotenv()

class TokenData(BaseModel):
    user_id:int
    user_name:str
    role:str
    exp:datetime

LOGINE_SESSION_KEY = os.getenv("LOGINKEY")
LOGIN_EXPIRY_HOURS = 24

OWNER_ROLE = "owner"
ADMIN_ROLE = "admin"
USER_ROLE = "user"


class Authentication:

    def generate_login_token(self ,user:User):

        if user.role not in [OWNER_ROLE ,ADMIN_ROLE ,USER_ROLE]:
            raise ValueError("Invalid user role")

        payload = TokenData(
            user_id = user.id ,
            user_name = user.name,
            role = user.role,
            exp = datetime.now(timezone.utc) + timedelta(hours = LOGIN_EXPIRY_HOURS)
        ).model_dump()

        return jwt.encode(payload ,LOGINE_SESSION_KEY , algorithm="HS256")
    
    def session_verify(self ,req:Request):
        token = req.headers.get("Authorization")
        if not token:
            return None
        
        try:
            decoded = jwt.decode(token ,LOGINE_SESSION_KEY , algorithms=["HS256"])
            return TokenData.model_validate(decoded)
        
        except Exception as e:
            print("Error:" ,e)
            raise HTTPException(status_code=401 ,detail="Unauthorized")
    
    def is_admin(self ,user:User):
        if user.role == ADMIN_ROLE:
            return True
        return False
    
    def is_owner(self ,user:User):
        if user.role == OWNER_ROLE:
            return True
        return False

    def hash_password(self ,plain_password: str) -> str:
        salt = bcrypt.gensalt()
        hashed = bcrypt.hashpw(plain_password.encode('utf-8'), salt)
        return hashed.decode('utf-8')     
    
    def verify_password(self ,plain_password: str ,hashed_password: str) -> bool:
        return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))