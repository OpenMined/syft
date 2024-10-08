import secrets

from pydantic import BaseModel


class User(BaseModel):
    email: str
    token: str
    is_registered: bool = False
    is_banned: bool = False


class UserManager:
    def __init__(self):
        self.users: dict[str, User] = {}

    def get_user(self, email: str) -> User | None:
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

    def ban_user(self, email: str) -> User:
        user = self.get_user(email)
        if user is None:
            raise ValueError(f"User {email} not found")

        user.is_banned = True
        return user

    def unban_user(self, email: str) -> User:
        user = self.get_user(email)
        if user is None:
            raise ValueError(f"User {email} not found")

        user.is_banned = False
        return user

    def __repr__(self) -> str:
        if len(self.users) == 0:
            return "UserManager()"
        res = "UserManager(\n"
        for email, user in self.users.items():
            res += f"  {email}: {user}\n"
        res += ")"
