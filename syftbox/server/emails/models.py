from typing import Union

from pydantic import BaseModel, EmailStr, Field, NameEmail

from .constants import FROM_EMAIl


class SendEmailRequest(BaseModel):
    to: Union[EmailStr, NameEmail]
    subject: str
    html: str

    def json_for_request(self):
        return {
            "from": FROM_EMAIl,
            "to": [self.to],
            "subject": self.subject,
            "html": self.html,
        }


class BatchSendEmailRequest(BaseModel):
    emails: list[SendEmailRequest] = Field(max_length=100)

    def json_for_request(self):
        return [email.json_for_request() for email in self.emails]
