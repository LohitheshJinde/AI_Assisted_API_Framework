import logging
import os
import json
import sys
import re
from behave import when
from datetime import datetime, timezone
import subprocess

project_root_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.append(project_root_path)

# Logging setup
current_date = datetime.now(timezone.utc).strftime("%Y%m%d")
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.abspath(os.path.join(current_dir, os.pardir, os.pardir))
logs_dir = os.path.join(parent_dir, "logs", current_date, "steps")
os.makedirs(logs_dir, exist_ok=True)

log_file_path = os.path.join(logs_dir, "execution_report.log")
logging.basicConfig(filename=log_file_path, level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


def extract_json_from_output(stdout_text, stderr_text=None):
    combined = stdout_text.strip().splitlines()
    if stderr_text:
        combined += stderr_text.strip().splitlines()
    for line in reversed(combined):
        line = line.strip()
        if "{" in line and "}" in line:
            try:
                return json.loads(line[line.find("{"):])
            except json.JSONDecodeError:
                continue
    return None


def execute_subprocess(command):
    logging.info(f"Executing: {' '.join(command)}")
    process = subprocess.run(command, capture_output=True, text=True)
    logging.info(f"Return Code: {process.returncode}")

    url_pattern = r'https?://[^\s""]+'
    for line in process.stdout.splitlines():
        if not re.search(url_pattern, line):
            logging.info(line)
    for line in process.stderr.splitlines():
        if not re.search(url_pattern, line):
            logging.info(line)

    result = extract_json_from_output(process.stdout, process.stderr)

    if process.returncode != 0:
        msg = result.get("message", "Subprocess failed") if result else "Subprocess failed without JSON output"
        logging.error(f"FAILED: {msg}")
        raise Exception(msg)

    if result and result.get("status", "").upper() == "FAILED":
        raise Exception(result.get("message", "Test step failed"))

    logging.info(f"Finished: {' '.join(command)}")


def _venv_python():
    if os.name == 'nt':
        return os.path.join(sys.prefix, 'Scripts', 'python.exe')
    return os.path.join(sys.prefix, 'bin', 'python')


@when('I want to execute {application} {end_points} {filename_pattern} API post tests')
def step_execute_post(context, application, end_points, filename_pattern):
    logging.info(f"POST: {application} {end_points} {filename_pattern}")
    execute_subprocess([_venv_python(), 'core/api_engine/TestAPIRequests.py', application, end_points, 'Post', filename_pattern])


@when('I want to execute {application} {end_points} {filename_pattern} API get tests')
def step_execute_get(context, application, end_points, filename_pattern):
    logging.info(f"GET: {application} {end_points} {filename_pattern}")
    execute_subprocess([_venv_python(), 'core/api_engine/TestAPIRequests.py', application, end_points, 'Get', filename_pattern])
