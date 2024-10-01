import os
import re

from syftbox.lib.lib import str_to_bool


def extract_leftmost_email(text: str) -> str:
    # Define a regex pattern to match an email address
    email_regex = r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+"

    # Search for all matches of the email pattern in the text
    matches = re.findall(email_regex, text)

    # Return the first match, which is the left-most email
    if matches:
        return matches[0]
    return None


def validate_email(email: str) -> bool:
    # Define a regex pattern for a valid email
    email_regex = r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"

    # Use the match method to check if the email fits the pattern
    if re.match(email_regex, email):
        return True
    return False


def verify_tls() -> bool:
    return not str_to_bool(str(os.environ.get("IGNORE_TLS_ERRORS", "0")))
