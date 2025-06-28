"""Core logic for packaging a executable binary for the host platform."""

import os
import platform
import shutil
import subprocess
import urllib.request
import zipfile
from pathlib import Path
from typing import Final, NamedTuple

import pyinstaller_versionfile
import requests

import rovodev
from rovodev import AGENT_PATH # Import AGENT_PATH
from rovodev.common.config import AIAgentConfig, save_config # Changed RovoDevConfig

ARCH_MAPPING: Final = {
    "amd64": "amd64",
    "arm64": "arm64",
    "x86_64": "amd64",
    "aarch64": "arm64",
}


def get_arch() -> str:
    """Get the machine architecture."""
    machine = platform.machine().lower()
    if machine in ARCH_MAPPING:
        return ARCH_MAPPING[machine]
    else:
        return machine


APP_NAME: Final = "ai_agent_cli" # Changed from "atlassian_cli_rovodev"

VERSION: Final = rovodev.__version__
APP_NAME_FULL: Final = f"{APP_NAME}-{VERSION}-{platform.system().lower()}-{get_arch()}" # Uses new APP_NAME
APP_NAME_LATEST: Final = f"{APP_NAME}-latest-{platform.system().lower()}-{get_arch()}" # Uses new APP_NAME
PROJECT_ROOT: Final = Path(__file__).parent.parent # This is .../distribution, so PROJECT_ROOT is .../atlassian_cli_rovodev
REPO_ROOT: Final = PROJECT_ROOT.parent.parent # This is .../lib
DIST: Final = Path(REPO_ROOT, "dist")
DIST_PATH: Final = Path(DIST, APP_NAME_FULL)
EXE_NAME: Final[str] = f"{APP_NAME}.exe" if platform.system() == "Windows" else APP_NAME


class BuildMetadata(NamedTuple):
    company_name: str
    product_name: str
    version: str
    portable_path: str
    app_name: str = APP_NAME
    app_name_full: str = APP_NAME_FULL
    exe_name: str = EXE_NAME


def get_ripgrep_url() -> str:
    """Get the URL for the ripgrep binary."""
    system = platform.system().lower()
    arch = get_arch()
    base_url = "https://github.com/BurntSushi/ripgrep/releases/download/14.1.1/ripgrep-14.1.1-"

    if system == "windows" and arch == "amd64":
        return base_url + "x86_64-pc-windows-msvc.zip"
    elif system == "windows" and arch == "arm64":
        # Windows ARM64 is not supported by ripgrep, but the x86_64 version should work
        return base_url + "x86_64-pc-windows-msvc.zip"
    elif system == "linux" and arch == "amd64":
        return base_url + "x86_64-unknown-linux-musl.tar.gz"
    elif system == "linux" and arch == "arm64":
        return base_url + "aarch64-unknown-linux-gnu.tar.gz"
    elif system == "darwin" and arch == "amd64":
        return base_url + "x86_64-apple-darwin.tar.gz"
    elif system == "darwin" and arch == "arm64":
        return base_url + "aarch64-apple-darwin.tar.gz"
    else:
        return ""


def e2e_test():
    # reset the log file
    log_file = AGENT_PATH / "agent.log" # Changed path
    if log_file.exists():
        log_file.unlink(missing_ok=True)

    # test the executable
    result = subprocess.run(
        [f"{DIST}/{APP_NAME}/{EXE_NAME}", "run", "what is 1024 plus 1024"],
        capture_output=True,
        env=os.environ.copy()
        # Removed Atlassian-specific email for debug logging.
        # Debug logging will now depend on IS_INTERNAL_USER being True,
        # which is currently defaulted to False.
        # | {
        #     "USER_EMAIL": "debug-user@example.com",
        # },
    )
    output = result.stdout.decode() + "\n" + result.stderr.decode()
    print(output)

    if log_file.exists():
        with open(log_file, "r") as f:
            log_output = f.read()
            print(f"Log file content:\n{log_output}")

    assert result.returncode == 0, f"Executable failed with return code {result.returncode}"
    assert "AI Agent" in output, "Executable did not start correctly" # Changed "Rovo Dev"
    assert "2048" in output, "Executable did not return the expected result"
    assert "─ Error ─" not in output, "Executable returned an error"


def make_portable(publish: bool) -> Exception | BuildMetadata:
    """Build a portable application for the host platform and optionally publish it to statlas."""

    exception: Exception | None = None

    try:
        # find the sdist archive and unpack it
        archives = list(DIST.glob(rf"{APP_NAME}-{VERSION}.tar.gz")) # APP_NAME is now generic
        assert len(archives) == 1
        shutil.unpack_archive(archives[0], DIST)

        build_metadata: Final = BuildMetadata(
            company_name="YourCompany", # Changed
            product_name="AI Agent CLI", # Changed
            version=VERSION,
            portable_path=str(DIST_PATH),
        )

        # create the build folder
        if not os.path.exists(PROJECT_ROOT / "build"):
            os.makedirs(PROJECT_ROOT / "build")
        else:
            shutil.rmtree(PROJECT_ROOT / "build")
            os.makedirs(PROJECT_ROOT / "build")

        # create the version file (only used by Windows)
        pyinstaller_versionfile.create_versionfile(
            output_file=str(PROJECT_ROOT / "build" / "exe_version.txt"),
            version=VERSION,
            company_name=build_metadata.company_name, # Already "YourCompany"
            file_description="AI Agent CLI", # Changed
            product_name=build_metadata.product_name, # Already "AI Agent CLI"
            internal_name=APP_NAME, # Already "ai_agent_cli"
            original_filename=EXE_NAME, # Based on new APP_NAME
            legal_copyright="Copyright (c) YourCompany", # Changed
            translations=[1033, 1252],
        )

        pyinstaller_command: Final = (
            "uv",
            "run",
            "--package", # This refers to the package name on PyPI if it were published
            "ai_agent_cli", # Changed from "atlassian-cli-rovodev"
            "pyinstaller",
            f"--add-data={DIST}/{APP_NAME}-{VERSION}:{APP_NAME}", # APP_NAME is generic
            f"--additional-hooks-dir={PROJECT_ROOT}/hooks", # Path relative to PROJECT_ROOT (atlassian_cli_rovodev)
            f"--runtime-hook={PROJECT_ROOT}/hooks/runtime.py", # Path relative to PROJECT_ROOT
            f"--copy-metadata={APP_NAME}", # APP_NAME is generic
            f"--copy-metadata=pydantic_ai_slim", # This is a dependency, keep
            "--onedir",
            "--noconfirm",
            '--python-option="X utf8=1"',
            "--exclude-module=pyarrow",
            "--exclude-module=plotly",
            "--exclude-module=scipy",
            "--exclude-module=pandas",
            "--exclude-module=datasets",
            f"--contents-directory=lib",
            f"--name={APP_NAME}",
            f"--distpath={DIST}",
            f"--workpath={PROJECT_ROOT}/build",
            f"{PROJECT_ROOT}/src/rovodev/__main__.py",
        ) + ((f"--version-file={PROJECT_ROOT}/build/exe_version.txt",) if platform.system() == "Windows" else ())

        # build the executable
        assert subprocess.run(pyinstaller_command).returncode == 0

        # create default config file to skip agreement
        save_config(
            AIAgentConfig(), # Changed RovoDevConfig
            str(AGENT_PATH / "config.yml"), # Changed path
        )

        # download ripgrep
        ripgrep_url = get_ripgrep_url()
        if ripgrep_url:
            ripgrep_archive = Path(DIST, "ripgrep")
            urllib.request.urlretrieve(ripgrep_url, ripgrep_archive)
            shutil.unpack_archive(
                ripgrep_archive, Path(DIST, APP_NAME, "ripgrep_unzip"), "zip" if ripgrep_url.endswith(".zip") else "tar"
            )
            os.rename(
                Path(DIST, APP_NAME, "ripgrep_unzip", os.listdir(Path(DIST, APP_NAME, "ripgrep_unzip"))[0]),
                Path(DIST, APP_NAME, "ripgrep"),
            )
            shutil.rmtree(Path(DIST, APP_NAME, "ripgrep_unzip"))
            # remove the temporary archive
            os.remove(ripgrep_archive)

        # copy the build to the staging folder
        shutil.copytree(Path(DIST, APP_NAME), DIST_PATH, dirs_exist_ok=True)

        # simple test to verify the executable works
        result = subprocess.run(
            [f"{DIST}/{APP_NAME}/{EXE_NAME}", "--version"],
            capture_output=True,
        )
        output = result.stdout.decode()
        if result.returncode != 0 or VERSION not in output:
            print(f"Executable output: {output}")
            raise Exception(f"Executable failed to run correctly: {result.returncode} {output}")

        # make a ZIP archive
        zip_path = str(DIST_PATH) + ".zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, True, 9) as zip_file:
            for path, _, files in os.walk(DIST_PATH):
                for file in files:
                    zip_file.write(
                        Path(path, file),
                        Path(path, file).relative_to(DIST_PATH),
                    )

        pipelinesJwtToken = os.environ.get("PIPELINES_JWT_TOKEN")

        # if this is in CI but not a publish step, run the e2e test
        # This CI-specific logic might be kept or removed depending on user's CI setup.
        # For a generic template, it's often better to remove CI-specific assumptions.
        # pipelinesJwtToken is also Atlassian specific.
        # if pipelinesJwtToken and not publish:
        #     e2e_test()

        # Removed Atlassian-specific Statlas publishing logic
        # if pipelinesJwtToken and publish:
        #     headers = {
        #         "Authorization": f"Bearer {pipelinesJwtToken}",
        #     }
        #
        #     with open(zip_path, "rb") as f:
        #         response_upload_versioned = requests.put(
        #             f"https://statlas.prod.atl-paas.net/rovodev-cli/releases/{APP_NAME_FULL}.zip",
        #             headers=headers,
        #             data=f,
        #         )
        #         if response_upload_versioned.status_code != 200:
        #             raise Exception(
        #                 f"Failed to upload the ZIP archive: {response_upload_versioned.status_code} {response_upload_versioned.text}"
        #             )
        #
        #     with open(zip_path, "rb") as f:
        #         response_upload_latest = requests.put(
        #             f"https://statlas.prod.atl-paas.net/rovodev-cli/releases/{APP_NAME_LATEST}.zip",
        #             headers=headers,
        #             data=f,
        #         )
        #         if response_upload_latest.status_code != 200:
        #             raise Exception(
        #                 f"Failed to upload the ZIP archive: {response_upload_latest.status_code} {response_upload_latest.text}"
        #             )

        return build_metadata

    except Exception as e:
        exception = e
        return exception
