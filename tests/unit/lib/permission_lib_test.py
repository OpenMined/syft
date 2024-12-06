from pathlib import Path

import pytest

from syftbox.lib.permissions import (
    ComputedPermission,
    PermissionFile,
    PermissionParsingError,
    PermissionRule,
    PermissionType,
)


def test_parsing_dicts():
    d = {"permissions": "read", "path": "x.txt", "user": "user@example.org"}
    rule = PermissionRule.from_rule_dict(Path("."), d, priority=0)
    assert rule.permissions == [PermissionType.READ]
    assert rule.path == "x.txt"
    assert rule.user == "user@example.org"
    assert rule.allow is True
    assert rule.terminal is False


def test_parsing():
    yaml_string = """
    - permissions: read
      path: x.txt
      user: user@example.org

    - permissions: [read, write]
      path: x.txt
      user: "*"
      type: disallow
      terminal: true
    """
    file = PermissionFile.from_string(yaml_string, ".")
    assert len(file.rules) == 2

    assert file.rules[0].permissions == [PermissionType.READ]
    assert file.rules[0].path == "x.txt"
    assert file.rules[0].user == "user@example.org"
    assert file.rules[0].allow is True
    assert file.rules[0].terminal is False

    # check the same for the second rule
    assert file.rules[1].permissions == [PermissionType.READ, PermissionType.WRITE]
    assert file.rules[1].path == "x.txt"
    assert file.rules[1].user == "*"
    assert file.rules[1].allow is False
    assert file.rules[1].terminal is True


def test_parsing_fails():
    yaml_string = """
    - permissions: read
      path: "../*/x.txt"
      user: user@example.org
    """
    with pytest.raises(PermissionParsingError):
        PermissionFile.from_string(yaml_string, ".")


def test_parsing_useremail():
    yaml_string = """
        - permissions: read
          path: "{useremail}/*"
          user: user@example.org
    """

    file = PermissionFile.from_string(yaml_string, ".")
    rule = file.rules[0]
    assert rule.has_email_template
    assert rule.resolve_path_pattern("user@example.org") == "user@example.org/*"


def test_globstar():
    rule = PermissionRule.from_rule_dict(
        Path("."), {"path": "**", "permissions": ["admin", "read", "write"], "user": "user@example.org"}, 0
    )
    computed_permission = ComputedPermission(user="user@example.org", file_path=Path("a.txt"))
    computed_permission.apply(rule)
    assert computed_permission.has_permission(PermissionType.READ)

    computed_permission = ComputedPermission(user="user@example.org", file_path=Path("b/a.txt"))
    computed_permission.apply(rule)
    assert computed_permission.has_permission(PermissionType.READ)

def test_computed_permissions():
    base_rule = PermissionRule.from_rule_dict(
        Path("."), {"path": "user@example.org/test/a.txt", "permissions": ["admin"], "user": "user@example.org"}, 0
    )
    computed_permission = ComputedPermission(user="user@example.org", file_path=Path("user@example.org/test/a.txt"))
    computed_permission.apply(base_rule)
    assert computed_permission.has_permission(PermissionType.READ)
    assert computed_permission.has_permission(PermissionType.WRITE)
    assert computed_permission.has_permission(PermissionType.CREATE)
    assert computed_permission.has_permission(PermissionType.ADMIN)
    
    diff_user_rule = PermissionRule.from_rule_dict(
        Path("."), {"path": "user@example.org/test/a.txt", "permissions": ["read"], "user": "user_2@example.org"}, 0
    )
    computed_permission = ComputedPermission(user="user_2@example.org", file_path=Path("user@example.org/test/a.txt"))
    computed_permission.apply(diff_user_rule)
    assert computed_permission.has_permission(PermissionType.READ)


    no_read_rule = PermissionRule.from_rule_dict(
        Path("."), {"path": "user@example.org/test/a.txt", "permissions": ["write", 'create'], "user": "user_2@example.org"}, 0
    )
    computed_permission = ComputedPermission(user="user_2@example.org", file_path=Path("user@example.org/test/a.txt"))
    computed_permission.apply(no_read_rule)
    assert not computed_permission.has_permission(PermissionType.READ)
    assert computed_permission.has_permission(PermissionType.WRITE)
    assert computed_permission.has_permission(PermissionType.CREATE)
