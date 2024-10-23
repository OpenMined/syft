import os
import shutil

import pytest

from syftbox.app.install import clone_repository, sanitize_git_path


def test_valid_git_path():
    path = "Example/Repository"
    output_path = sanitize_git_path(path)
    assert path == output_path


def test_valid_git_url():
    path = "Example/Repository"
    http_url = f"http://github.com/{path}"
    output_path = sanitize_git_path(http_url)
    assert path == output_path

    https_url = f"https://github.com/{path}"
    output_path = sanitize_git_path(https_url)
    assert path == output_path


def test_invalid_git_path():
    path = "..Example/../Repository"
    with pytest.raises(ValueError) as excpt:
        _ = sanitize_git_path(path)
        assert excpt.value == "Invalid Git repository path format."


def test_second_invalid_git_path():
    path = "http://example.com"
    with pytest.raises(ValueError) as excpt:
        _ = sanitize_git_path(path)
        assert excpt.value == "Invalid Git repository path format."


def test_clone_valid_repository():
    path = "OpenMined/logged_in"
    temp_path = clone_repository(path)
    assert os.path.exists(temp_path)
    shutil.rmtree(temp_path)


def test_clone_repository_to_an_existent_path():
    # First call will make the repository path exist
    path = "OpenMined/logged_in"
    temp_path = clone_repository(path)
    assert os.path.exists(temp_path)

    # Second call must clone it again without any exception (replaces the old one).
    temp_path = clone_repository(path)
    shutil.rmtree(temp_path)


def test_clone_invalid_repository():
    path = "InvalidUser/InvalidRepo"
    with pytest.raises(ValueError) as excpt:
        _ = clone_repository(path)
        assert excpt.value == "The provided repository path doesn't seems to be accessible. Please check it out."
