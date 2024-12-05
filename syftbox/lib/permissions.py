import json
import re
import traceback
from collections import defaultdict
from enum import Enum
from pathlib import Path
from typing import List, Optional, Tuple

import wcmatch
import yaml
from pydantic import BaseModel, model_validator
from wcmatch.glob import globmatch

from syftbox.lib.constants import PERM_FILE
from syftbox.server.models.sync_models import RelativePath


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
    dir_path: RelativePath  # where does this permfile live
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
        return self.dir_path / PERM_FILE

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
        email = values.get("user", "")
        is_valid_email = re.match(r"[^@]+@[^@]+", email or "")
        if email != "*" and not is_valid_email:
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

    def as_file_json(self):
        res = {
            "path": self.path,
            "user": self.user,
            "permissions": [p.name.lower() for p in self.permissions],
            "terminal": self.terminal,
        }
        if not self.allow:
            res["type"] = "disallow"
        return res

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
                if globmatch(
                    str(relative_file_path),
                    self.path.replace("{useremail}", email),
                    flags=wcmatch.glob.GLOBSTAR,
                ):
                    match = True
                    match_for_email = email
                    break
        else:
            match = globmatch(str(relative_file_path), self.path, flags=wcmatch.glob.GLOBSTAR)
        return match, match_for_email

    @property
    def has_email_template(self):
        return "{useremail}" in self.path

    def resolve_path_pattern(self, email):
        return self.path.replace("{useremail}", email)


class PermissionFile(BaseModel):
    relative_filepath: RelativePath
    rules: List[PermissionRule]

    def save(self, path: Path):
        with open(path, "w") as f:
            yaml.dump([x.as_file_json() for x in self.rules], f)

    @classmethod
    def datasite_default(cls, email: str):
        return PermissionFile.from_rule_dicts(
            Path(email) / PERM_FILE,
            [
                {
                    "path": "**",
                    "user": email,
                    "permissions": ["admin", "create", "write", "read"],
                }
            ],
        )

    @property
    def depth(self):
        return len(self.relative_filepath.parts)

    def to_dict(self):
        return [x.as_file_json() for x in self.rules]

    @classmethod
    def is_permission_file(cls, path: Path):
        return path.name == PERM_FILE

    @classmethod
    def is_valid(cls, path: Path, datasite_path: Path, _print=True):
        try:
            cls.from_file(path, datasite_path)
            return True
        except Exception as e:
            if _print:
                print(f"Invalid permission file {path}: {e}\n{traceback.format_exc()}")
            return False

    @classmethod
    def mine_with_public_read(cls, email: str, filepath: Path):
        return cls.from_rule_dicts(
            filepath,
            [
                {
                    "path": "**",
                    "user": email,
                    "permissions": ["admin"],
                },
                {
                    "path": "**",
                    "user": "*",
                    "permissions": ["read"],
                },
            ],
        )

    @classmethod
    def mine_with_public_rw(cls, email: str, filepath: Path):
        return cls.from_rule_dicts(
            filepath,
            [
                {
                    "path": "**",
                    "user": email,
                    "permissions": ["admin"],
                },
                {
                    "path": "**",
                    "user": "*",
                    "permissions": ["write", "read"],
                },
            ],
        )

    @property
    def dir_path(self):
        return self.relative_filepath.parent

    @classmethod
    def from_file(cls, path: Path, datasite_path: Path):
        with open(path, "r") as f:
            rule_dicts = yaml.safe_load(f)
            relative_path = path.relative_to(datasite_path)
            return cls.from_rule_dicts(relative_path, rule_dicts)

    @classmethod
    def from_rule_dicts(cls, permfile_file_path, rule_dicts):
        if not isinstance(rule_dicts, list):
            raise ValueError(f"rules should be passed as a list of dicts, received {type(rule_dicts)}")
        rules = []
        dir_path = Path(permfile_file_path).parent
        for i, rule_dict in enumerate(rule_dicts):
            rule = PermissionRule.from_rule_dict(dir_path, rule_dict, priority=i)
            rules.append(rule)
        return cls(relative_filepath=permfile_file_path, rules=rules)

    @classmethod
    def from_string(cls, s, path):
        dicts = yaml.safe_load(s)
        return cls.from_rule_dicts(Path(path), dicts)

    @classmethod
    def from_bytes(cls, b, path):
        return cls.from_string(b.decode("utf-8"), path)


class ComputedPermission(BaseModel):
    user: str
    file_path: RelativePath
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
    def from_user_rules_and_path(cls, rules: List[PermissionRule], user: str, path: Path):
        permission = cls(user=user, file_path=path)
        for rule in rules:
            permission.apply(rule)
        return permission

    @property
    def path_owner(self):
        """owner of the datasite for this path"""
        return str(self.file_path).split("/", 1)[0]

    def has_permission(self, permtype: PermissionType):
        if self.path_owner == self.user:
            return True
        if self.perms[PermissionType.ADMIN]:
            return True
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
            return globmatch(relative_file_path, resolved_path_pattern, flags=wcmatch.glob.GLOBSTAR)
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


# migration code, can be deleted after prod migration is done


def map_email_to_permissions(json_data: dict) -> dict:
    email_permissions = defaultdict(list)
    for permission, emails in json_data.items():
        for email in emails:
            if email is None:
                continue
            email_permissions[email].append(permission)
    return email_permissions


def convert_permission(old_perm_dict: dict) -> dict:
    terminal = old_perm_dict.pop("terminal", False)
    old_perm_dict.pop("filepath", None)  # not needed, we use the actual path of the perm file

    user_permissions = map_email_to_permissions(old_perm_dict)
    output = []

    for email in user_permissions:
        new_perm_dict = {
            "permissions": user_permissions[email],
            "path": "**",
            "user": (email if email != "GLOBAL" else "*"),  # "*" is a wildcard for all users
        }
        if terminal:
            new_perm_dict["terminal"] = terminal
        output.append(new_perm_dict)

    return output


def migrate_permissions(snapshot_folder: Path):
    """
    Migrate all `_.syftperm` files from old format to new format within a given snapshot folder.
    This function:
    - searches for files with the extension '_.syftperm' in the specified snapshot folder.
    -  converts their content from JSON to YAML format
    - writes the converted content to new files with the name 'syftperm.yaml' in the same path
    - deletes the original `_.syftperm` files

    Args:
        snapshot_folder (str): The path to the snapshot folder containing the permission files.
    Returns:
        None
    """
    old_syftperm_filename = "_.syftperm"
    files = list(snapshot_folder.rglob(old_syftperm_filename))
    for file in files:
        old_data = json.loads(file.read_text())
        new_data = convert_permission(old_data)
        new_file_path = file.with_name(file.name.replace(old_syftperm_filename, PERM_FILE))
        print(new_file_path)
        print(new_data)
        new_file_path.write_text(yaml.dump(new_data))
        # do we need to backup the old file?
        # might be better to temporarily leave it for debugging purposes
        # file.unlink()