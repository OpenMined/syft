import secrets

from pydantic import BaseModel


class User(BaseModel):
    email: str
    token: str
    is_registered: bool = False
    is_banned: bool = False


class UserUpdate(BaseModel):
    email: str | None = None
    token: str | None = None
    is_registered: bool | None = None
    is_banned: bool | None = None


class UserManager:
    def __init__(self):
        self.users: dict[str, User] = {}

    def get_user(self, email: str) -> User | None:
        print(self.users)
        return self.users.get(email)

    def create_token_for_user(self, email: str) -> User:
        user = self.get_user(email)
        if user is not None:
            return user

        token = secrets.token_urlsafe(32)
        user = User(email=email, token=token)
        self.users[email] = user
        return user

    def register_user(self, email: str, token: str) -> User:
        user = self.get_user(email)
        if user is None:
            raise ValueError(f"User {email} not found")

        if user.token != token:
            raise ValueError("Invalid token")

        user.is_registered = True
        return user

    def update_user(self, user: User) -> User:
        existing_user = self.get_user(user.email)
        if existing_user is None:
            raise ValueError(f"User {user.email} not found")

        self.users[user.email] = user
        return user

    def __repr__(self) -> str:
        if len(self.users) == 0:
            return "UserManager()"
        res = "UserManager(\n"
        for email, user in self.users.items():
            res += f"  {email}: {user}\n"
        res += ")"
