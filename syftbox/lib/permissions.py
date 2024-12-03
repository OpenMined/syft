import re
import sqlite3
from enum import Enum
from pathlib import Path
from typing import List, Optional, Tuple

import yaml
from pydantic import BaseModel, model_validator
from wcmatch.glob import globmatch


# util
def issubpath(path1, path2):
    return path1 in path2.parents


class PermissionType(Enum):
    CREATE = 1
    READ = 2
    WRITE = 3
    ADMIN = 4


class PermissionParsingError(Exception):
    pass


class PermissionRule(BaseModel):
    dir_path: Path  # where does this permfile live
    path: str  # what paths does it apply to (e.g. **/*.txt)
    user: str  # can be *,
    allow: bool = True
    terminal: bool = False
    permissions: List[PermissionType]  # read/write/create/admin
    priority: int

    def __eq__(self, other):
        return self.model_dump() == other.model_dump()

    @property
    def permfile_path(self):
        return self.dir_path / ".syftperm"

    @property
    def depth(self):
        return len(self.permfile_path.parts)

        # write model validator that accepts either a single string or a list of strings as permissions when initializing

    @model_validator(mode="before")
    @classmethod
    def validate_permissions(cls, values):
        # check if values only contains keys that are in the model
        invalid_keys = set(values.keys()) - (set(cls.model_fields.keys()) | set(["type"]))
        if len(invalid_keys) > 0:
            raise PermissionParsingError(
                f"rule yaml contains invalid keys {invalid_keys}, only {cls.model_fields.keys()} are allowed"
            )

        # add that if the type value is "disallow" we set allow to false
        if values.get("type") == "disallow":
            values["allow"] = False

        # if path refers to a location higher in the directory tree than the current file, raise an error
        if values.get("path").startswith("../"):
            raise PermissionParsingError(
                f"path {values.get('path')} refers to a location higher in the directory tree than the current file"
            )

        # if user is not a valid email, or *, raise an error
        email = values.get("user")
        if email != "*" and not bool(re.search(r"^[\w\.\+\-]+\@[\w]+\.[a-z]{2,3}$", email)):
            raise PermissionParsingError(f"user {values.get('user')} is not a valid email or *")

        # listify permissions
        perms = values.get("permissions")
        if isinstance(perms, str):
            perms = [perms]
        if isinstance(perms, list):
            values["permissions"] = [PermissionType[p.upper()] if isinstance(p, str) else p for p in perms]
        else:
            raise ValueError(f"permissions should be a list of strings or a single string, received {type(perms)}")

        path = values.get("path")
        if "**" in path and "{useremail}" in path and path.index("**") < path.rindex("{useremail}"):
            # this would make creating the path2rule mapping more challenging to compute beforehand
            raise PermissionParsingError("** can never be after {useremail}")

        return values

    @classmethod
    def from_rule_dict(cls, dir_path, rule_dict, priority):
        # initialize from dict
        return cls(dir_path=dir_path, **rule_dict, priority=priority)

    @classmethod
    def from_db_row(cls, row):
        """Create a PermissionRule from a database row"""
        permissions = []
        if row["can_read"]:
            permissions.append(PermissionType.READ)
        if row["can_create"]:
            permissions.append(PermissionType.CREATE)
        if row["can_write"]:
            permissions.append(PermissionType.WRITE)
        if row["admin"]:
            permissions.append(PermissionType.ADMIN)

        return cls(
            dir_path=Path(row["permfile_path"]).parent,
            path=row["path"],
            user=row["user"],  # Default to all users since DB schema doesn't show user field
            allow=not row["disallow"],
            terminal=bool(row["terminal"]),
            priority=row["priority"],
            permissions=permissions,
        )

    def to_db_row(self):
        """Convert PermissionRule to a database row dictionary"""
        return {
            "permfile_path": str(self.permfile_path),  # Reconstruct full path
            "permfile_dir": str(self.dir_path),
            "permfile_depth": self.depth,
            "priority": self.priority,
            "path": self.path,
            "user": self.user,
            "can_read": PermissionType.READ in self.permissions,
            "can_create": PermissionType.CREATE in self.permissions,
            "can_write": PermissionType.WRITE in self.permissions,
            "admin": PermissionType.ADMIN in self.permissions,
            "disallow": not self.allow,
            "terminal": self.terminal,
        }

    @property
    def permission_dict(self):
        return {
            "read": PermissionType.READ in self.permissions,
            "create": PermissionType.CREATE in self.permissions,
            "write": PermissionType.WRITE in self.permissions,
            "admin": PermissionType.ADMIN in self.permissions,
        }

    def filepath_matches_rule_path(self, filepath: Path) -> Tuple[bool, Optional[str]]:
        if issubpath(self.dir_path, filepath):
            relative_file_path = filepath.relative_to(self.dir_path)
        else:
            return False, None

        match_for_email = None
        if self.has_email_template:
            match = False
            emails_in_file_path = [part for part in relative_file_path.split("/") if "@" in part]  # todo: improve this
            for email in emails_in_file_path:
                if globmatch(self.path.replace("{useremail}", email), str(relative_file_path)):
                    match = True
                    match_for_email = email
                    break
        else:
            match = globmatch(self.path, str(relative_file_path))
        return match, match_for_email

    @property
    def has_email_template(self):
        return "{useremail}" in self.path

    def resolve_path_pattern(self, email):
        return self.path.replace("{useremail}", email)


class PermissionFile(BaseModel):
    filepath: Path
    content: str
    rules: List[PermissionRule]

    @property
    def depth(self):
        return len(self.filepath.parts)

    @property
    def dir_path(self):
        return self.filepath.parent

    @classmethod
    def from_file(cls, path):
        with open(path, "r") as f:
            rule_dicts = yaml.safe_load(f)
            content = f.read()
            return cls.from_rule_dicts(path, content, rule_dicts)

    @classmethod
    def from_rule_dicts(cls, permfile_file_path, content, rule_dicts):
        if not isinstance(rule_dicts, list):
            raise ValueError(f"rules should be passed as a list of dicts, received {type(rule_dicts)}")
        rules = []
        dir_path = Path(permfile_file_path).parent
        for i, rule_dict in enumerate(rule_dicts):
            rule = PermissionRule.from_rule_dict(dir_path, rule_dict, priority=i)
            rules.append(rule)
        return cls(filepath=permfile_file_path, content=content, rules=rules)

    @classmethod
    def from_string(cls, s, path):
        dicts = yaml.safe_load(s)
        return cls.from_rule_dicts(Path(path), s, dicts)


class ComputedPermission(BaseModel):
    user: str
    file_path: Path
    terminal: dict[PermissionType, bool] = {
        PermissionType.READ: False,
        PermissionType.CREATE: False,
        PermissionType.WRITE: False,
        PermissionType.ADMIN: False,
    }

    perms: dict[PermissionType, bool] = {
        PermissionType.READ: False,
        PermissionType.CREATE: False,
        PermissionType.WRITE: False,
        PermissionType.ADMIN: False,
    }

    @classmethod
    def from_user_and_path(cls, cursor: sqlite3.Cursor, user: str, path: Path):
        from syftbox.server.db.db import get_rules_for_path

        rules: List[PermissionRule] = get_rules_for_path(cursor, path)

        permission = cls(user=user, file_path=path)
        for rule in rules:
            permission.apply(rule)

        return permission

    def has_permission(self, permtype: PermissionType):
        return self.perms[permtype]

    def user_matches(self, rule: PermissionRule):
        """Computes if the user in the rule"""
        if rule.user == "*":
            return True
        elif rule.user == self.user:
            return True
        else:
            return False

    def rule_applies_to_path(self, rule: PermissionRule):
        if rule.has_email_template:
            # we fill in a/b/{useremail}/*.txt -> a/b/user@email.org/*.txt
            resolved_path_pattern = rule.resolve_path_pattern(self.user)
        else:
            resolved_path_pattern = rule.path

        # target file path (the one that we want to check permissions for relative to the syftperm file
        # we need this because the syftperm file specifies path patterns relative to its own location

        if issubpath(rule.dir_path, self.file_path):
            relative_file_path = self.file_path.relative_to(rule.dir_path)
            return globmatch(relative_file_path, resolved_path_pattern)
        else:
            return False

    def apply(self, rule: PermissionRule):
        # TODO: is terminal on a rule level or on a permission level?
        if self.user_matches(rule) and self.rule_applies_to_path(rule):
            for permtype in rule.permissions:
                if not self.terminal[permtype]:
                    self.perms[permtype] = rule.allow
                if rule.terminal:
                    self.terminal[permtype] = True
