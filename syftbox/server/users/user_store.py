from pydantic import BaseModel, EmailStr
from syftbox.server.settings import ServerSettings
from syftbox.server.sync import db
from syftbox.server.sync.db import get_db
from syftbox.server.sync.models import AbsolutePath, RelativePath


class User(BaseModel):
    email: EmailStr
    credentials: str


class UserStore:
    def __init__(self, server_settings: ServerSettings) -> None:
        self. server_settings = server_settings
        
    @property
    def db_path(self) -> AbsolutePath:
        return self.server_settings.file_db_path
    
    def exists(self, email: str):
        user = self.get_user_by_email(email=email)
        if user:
            return True
        return False
    
    def delete_user(self, email: str):
        conn = get_db(self.db_path)
        cursor = conn.cursor()
        cursor.execute("BEGIN IMMEDIATE;")
        try:
            db.delete_user(cursor, email)
        except ValueError:
            pass
        conn.commit()
        cursor.close()
        
    def get_user_by_email(self, email: str):
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            user = db.get_user_by_email(cursor, email)
            # ignoring id for now
            return User(email=user[1], credentials=user[2])
        
    def get_all_users(self):
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            users = db.get_all_users(cursor)
            return users
        
    def add_user(self, user: User):
        conn = get_db(self.db_path)
        cursor = conn.cursor()
        cursor.execute("BEGIN IMMEDIATE;")
        db.add_user(cursor, user.email, user.credentials)
        conn.commit()
        cursor.close()
        conn.close()
        
    def update_user(self, user: User):
        conn = get_db(self.db_path)
        cursor = conn.cursor()
        cursor.execute("BEGIN IMMEDIATE;")
        db.set_credentials(cursor, user.email, user.credentials)
        conn.commit()
        cursor.close()
        conn.close()
        
    
    