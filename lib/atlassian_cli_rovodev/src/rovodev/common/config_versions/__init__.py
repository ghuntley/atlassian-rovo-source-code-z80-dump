"""AI Agent CLI Configuration models.""" # Changed RovoDev

from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict
from pydantic.alias_generators import to_camel


def path_validator(value: str, is_dir: bool = False) -> str:
    """Expand user directory in the given path and create directories if needed."""
    path = Path(str(value)).expanduser().resolve()
    if is_dir:
        path.mkdir(parents=True, exist_ok=True)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
    return str(path)


def file_validator(value: str) -> str:
    """Validate and expand user directory in the given file path."""
    return path_validator(value, is_dir=False)


def dir_validator(value: str) -> str:
    """Validate and expand user directory in the given directory path."""
    return path_validator(value, is_dir=True)


FileStr = Annotated[str, BeforeValidator(file_validator)]
DirStr = Annotated[str, BeforeValidator(dir_validator)]


class BaseConfig(BaseModel):
    """Base configuration model."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
