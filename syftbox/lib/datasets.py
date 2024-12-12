"""
SyftBox Client Shim for apps and external dependencies


NOTE: this will likely get refactored as it's own SDK.
But we need it to maintain compatibility with apps
"""

from .client_shim import Client
import yaml
from pathlib import Path
from typing import Any, Dict
import importlib.util
import os
import traceback


# Suppose we have a required dataset version to check against:
REQUIRED_DATASET_VERSION = "0.1.0"  # This is just an example; adjust as needed.


class DatasetNotFoundError(Exception):
    pass


class DatasetConfigNotFoundError(Exception):
    pass


class DatasetValidationError(Exception):
    pass


class DatasetVersionMismatchError(Exception):
    pass


class DataLoderExecutionError(Exception):
    pass


def load_dataset(dataset_name: str) -> Path:
    """
    Attempts to load a dataset by its path from the CONFIG.

    Steps:
    1. Validate each dataset to ensure they have mandatory fields.
    2. Search for the dataset with a matching path.
    3. If found, return its path as a pathlib.Path object.
    4. If not found, raise DatasetNotFoundError.
    """

    client = Client.load()

    datasets_config_path: Path = client.datasets / "datasets.yaml"

    dataset_config = None

    with open(datasets_config_path, "r") as dataset_config_file:
        dataset_config = yaml.safe_load(dataset_config_file)

    # Check if the dataset.yaml was properly loaded
    if dataset_config is None:
        raise DatasetConfigNotFoundError("dataset.yaml not found on this datasite.")

    if "version" in dataset_config:
        dataset_version = dataset_config["version"]
        if dataset_version != REQUIRED_DATASET_VERSION:
            raise DatasetVersionMismatchError(
                f"Dataset config  version '{dataset_version}' does not match the required version '{REQUIRED_DATASET_VERSION}'."
            )
    else:
        raise DatasetVersionMismatchError(
            f"Dataset config file doesn't have a version."
        )

    # First, ensure the config structure is as expected.
    if "datasets" not in dataset_config or not isinstance(
        dataset_config["datasets"], list
    ):
        raise DatasetValidationError(
            "The configuration file is missing the 'datasets' list."
        )

    # Validate all datasets upfront (fail early if something is wrong).
    for dataset in dataset_config["datasets"]:
        validate_dataset_entry(dataset)

    # Try to match the requested dataset_name
    for dataset in dataset_config["datasets"]:
        if dataset_name == dataset["name"]:
            dataset_path = Path(dataset["path"])
            data_loader_path = dataset['dataset_loader']
            dataset = execute_data_loader(data_loader_path, dataset_path)
            return dataset 

    # If we exit the loop, no dataset matched
    raise DatasetNotFoundError(f"The dataset with name '{dataset_name}' was not found.")


def validate_dataset_entry(dataset: Dict[str, Any]) -> None:
    """
    Validate that a dataset entry has all required fields and meets any version requirements.
    Raises DatasetValidationError if mandatory fields are missing.
    Raises DatasetVersionMismatchError if version checking fails.
    """
    # Mandatory fields
    mandatory_fields = ["name", "path", "dataset_loader"]

    for field in mandatory_fields:
        if field not in dataset:
            raise DatasetValidationError(
                f"Mandatory field '{field}' is missing in dataset {dataset.get('name', '(unknown)')}"
            )


def execute_data_loader(file_path: str, dataset_path: Path):
    """
    Load a Python source file as a module and execute a given function from it.

    :param file_path:     The path to the Python source file.
    :param function_name: The name of the function within the module to execute.

    :return: The return value of the called function if successful, or None if errors occur.
    """

    # 2. Check if the file exists
    if not os.path.isfile(file_path):
        raise DataLoderExecutionError(
            f"Error: The file at '{file_path}' does not exist."
        )

    # 3. Attempt to load the module
    module_name = os.path.splitext(os.path.basename(file_path))[0]
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if spec is None:
        raise DataLoderExecutionError(
            f"Error: Could not create a module specification for '{file_path}'."
        )

    module = importlib.util.module_from_spec(spec)

    try:
        spec.loader.exec_module(module)
    except FileNotFoundError:
        raise DataLoderExecutionError(
            f"Error: The file '{file_path}' was not found or could not be read."
        )
    except SyntaxError as e:
        raise DataLoderExecutionError(
            f"Syntax error encountered when loading '{file_path}': {e}"
        )
    except Exception as e:
        # This is a general catch-all for other unexpected errors during module loading
        traceback.print_exc()
        raise DataLoderExecutionError(
            "An unexpected error occurred when loading the module: {e}"
        )

    # 4. Check if the function is defined in the module
    if not hasattr(module, "load"):
        raise DataLoderExecutionError(
            f"Error: The function 'load' is not defined in the module '{module_name}'."
        )

    func = getattr(module, "load")

    if not callable(func):
        raise DataLoderExecutionError(
            f"Error: 'load' in '{module_name}' is not callable."
        )

    # 5. Try executing the function
    try:
        result = func(dataset_path)
        return result
    except TypeError as e:
        # Argument mismatch errors, etc.
        traceback.print_exc()
        raise DataLoderExecutionError(f"TypeError: {e}")
    except Exception as e:
        # General execution errors
        traceback.print_exc()
        raise DataLoderExecutionError(
            f"An error occurred while executing 'load' from '{file_path}': {e}"
        )
