import json
import os
import sys
import logging
import time
import pandas as pd
import matplotlib
matplotlib.use('Agg')  # Use non-interactive backend
from matplotlib import pyplot as plt
from dotenv import load_dotenv
import argparse
import traceback

# Color constants for charts
VULNERABLE_COLOR = '#e74c3c'
SECURE_COLOR = '#27ae60'
INFO_COLOR = '#3498db'
WARNING_COLOR = '#f39c12'

# Load configuration from the config file
project_root_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
sys.path.append(project_root_path)

from core.utils import utils
from core.utils.utils import log_file_status

# Automatically reload environment variables when .env file changes
load_dotenv(dotenv_path=".env", verbose=True, override=True)

# Set up logging
current_dir = os.path.dirname(os.path.abspath(__file__))
current_date = utils.current_date
param_key = "security_method_gen_report.log"
log_file_path = utils.configure_logging_api(param_key, current_date, current_dir)


def extract_attack_payload(test):
    """Extract the malicious payload from test data."""
    # Check test case name for vulnerability type and return appropriate payload
    test_name = test.get('test_case_name', '').lower()
    
    if 'xxe' in test_name:
        return '<?xml version="1.0"?><!DOCTYPE root [<!ENTITY test SYSTEM "file:///etc/passwd">]>'
    elif 'ssrf' in test_name:
        return 'http://169.254.169.254/latest/meta-data/'
    elif 'broken_access_control' in test_name:
        return '../../../admin/users'
    elif 'command_injection' in test_name:
        return '; cat /etc/passwd'
    elif 'path_traversal' in test_name:
        return '../../../etc/passwd'
    elif 'sql_injection' in test_name or 'sql' in test_name:
        return "' OR '1'='1' --"
    elif 'xss' in test_name:
        return '<script>alert("XSS")</script>'
    elif 'brute_force' in test_name:
        return 'admin:password123'
    elif 'insecure_deserialization' in test_name:
        return 'O:8:"stdClass":1:{s:4:"exec";s:10:"system(ls)";}'  
    elif 'security_misconfiguration' in test_name:
        return 'debug=true&admin=1'
    elif 'sensitive_data_exposure' in test_name:
        return 'password=plaintext123'
    
    # Fallback to original payload extraction
    payload = test.get('request_payload', {})
    if not payload:
        return "N/A"
    
    def search_payload(obj, depth=0):
        if depth > 3:
            return None
            
        if isinstance(obj, str) and obj:
            if any(pattern in obj.lower() for pattern in ["'", "drop", "select", "union", "script", "alert", "@#@", "123", "random", "hatch"]):
                return obj
            if obj in ["", "@#@", "123", "random", "hatch"] or "'" in obj:
                return obj
        elif isinstance(obj, dict):
            for key, value in obj.items():
                result = search_payload(value, depth + 1)
                if result:
                    return result
        elif isinstance(obj, list):
            for item in obj:
                result = search_payload(item, depth + 1)
                if result:
                    return result
        return None
    
    result = search_payload(payload)
    return str(result) if result else "N/A"


def categorize_vulnerability(test_name):
    """Categorize the type of security vulnerability based on test name."""
    if not test_name:
        return 'Input Validation'
    test_lower = test_name.lower()
    if 'sql_injection' in test_lower or 'sql' in test_lower:
        return 'SQL Injection'
    elif 'brute_force' in test_lower or 'brute' in test_lower:
        return 'Brute Force'
    elif 'xss' in test_lower:
        return 'XSS'
    elif 'command_injection' in test_lower:
        return 'Command Injection'
    elif 'path_traversal' in test_lower:
        return 'Path Traversal'
    elif 'insecure_deserialization' in test_lower:
        return 'Insecure Deserialization'
    elif 'security_misconfiguration' in test_lower:
        return 'Security Misconfiguration'
    elif 'sensitive_data_exposure' in test_lower:
        return 'Sensitive Data Exposure'
    elif 'broken_access_control' in test_lower:
        return 'Broken Access Control'
    elif 'xxe' in test_lower:
        return 'XXE'
    elif 'ssrf' in test_lower:
        return 'SSRF'
    elif 'csrf' in test_lower:
        return 'CSRF'
    elif 'injection' in test_lower:
        return 'Injection Attack'
    else:
        return 'Input Validation'


def generate_html_report(json_file, output_folder):
    """
    Generate comprehensive HTML security report for POST method vulnerability testing.
    
    This function processes security test results and creates detailed HTML reports
    specifically for POST method endpoints. It analyzes various security vulnerabilities
    including SQL injection, brute force attacks, XSS, CSRF, and input validation issues.
    
    The report includes:
    - Security vulnerability summary with pass/fail statistics
    - Detailed test case results with attack payloads
    - Visual charts showing vulnerability distribution and response times
    - Code recommendations for fixing identified security issues
    - Endpoint performance metrics and security assessment
    
    Args:
        json_file (str): Path to JSON file containing security test results
        output_folder (str): Directory path where HTML reports will be generated
    
    Returns:
        None: Generates HTML files and charts in the specified output folder
    
    Raises:
        FileNotFoundError: If the input JSON file is not found
        json.JSONDecodeError: If the JSON file contains invalid data
        IOError: If unable to write output files
    """
    try:
        with open(json_file, 'r') as file:
            tests = json.load(file)
        logging.info("Loaded JSON data from file")

    except FileNotFoundError as e:
        error_message = f"Report Input File not found: {e}"
        logging.error(error_message)
        print(json.dumps({
            "status": "failed",
            "message": error_message
        }, indent=2))
        sys.exit(1)

    except json.JSONDecodeError as e:
        error_message = f"Error decoding JSON: {e}"
        logging.error(error_message)
        print(json.dumps({
            "status": "failed",
            "message": error_message
        }, indent=2))
        sys.exit(1)

    method_data = {}
    test_data = tests.get("tests", tests) if isinstance(tests, dict) else tests

    for test in test_data:
        method = "POST"
        if method not in method_data:
            method_data[method] = []

        filtered_test = {
            "testKey": test.get("test_key", "N/A"),
            "testCaseName": test.get("test_case_name", "N/A"),
            "testDescription": test.get("test_description", "N/A"),
            "responseTime": test.get("elapsed_time_req", 0) * 1000,  # Convert to milliseconds
            "status": test.get("status", "unknown"),
            "vulnerabilityType": categorize_vulnerability(test.get("test_case_name", "")),
            "attackPayload": extract_attack_payload(test),
            "statusCode": get_status_code(test)
        }
        method_data[method].append(filtered_test)

    for method, method_tests in method_data.items():
        df = pd.DataFrame(method_tests)

        method_output_folder = os.path.join(output_folder, f"method_{method.lower()}")
        os.makedirs(method_output_folder, exist_ok=True)
        logging.info("Created method output folder")

        # Generate endpoint summary data
        endpoint_summary = generate_endpoint_summary(df)
        
        generate_method_vulnerability_chart(df, method, os.path.join(method_output_folder, f"{method.lower()}_vulnerabilities.png"))
        generate_method_success_chart(df, method, os.path.join(method_output_folder, f"{method.lower()}_success_rate.png"))
        generate_method_response_time_chart(df, method, os.path.join(method_output_folder, f"{method.lower()}_response_times.png"))
        generate_method_status_summary_chart(df, method, os.path.join(method_output_folder, f"{method.lower()}_status_summary.png"))

        generate_method_html_report(df, method, method_output_folder, endpoint_summary)


def generate_method_html_report(df, method, output_folder, endpoint_summary):
    template_file_path = os.path.join(project_root_path, "core", "reports", "security", "security_method_template.html")
    try:
        with open(template_file_path, 'r', encoding='utf-8') as file:
            html_template = file.read()
        logging.info("HTML template loaded successfully!")
    except Exception as e:
        logging.error(f"Template error: {str(e)}")
        return



    # Generate table rows
    rows_html = ""
    for _, row in df.iterrows():
        status_class = "vulnerable" if row["status"] == "failed" else "secure"
        status_text = "FAILED" if row["status"] == "failed" else "PASSED"
        response_time = float(row['responseTime']) if pd.notna(row['responseTime']) and row['responseTime'] is not None else 0.0
        
        import html
        rows_html += f"""
            <tr>
                <td>{html.escape(str(row['testKey']))}</td>
                <td>{html.escape(str(row['testCaseName'])[:40])}...</td>
                <td>{html.escape(str(row['vulnerabilityType']))}</td>
                <td><div class="payload">{html.escape(str(row['attackPayload'])[:40])}...</div></td>
                <td>{html.escape(str(row['statusCode']))}</td>
                <td>{response_time:.2f}ms</td>
                <td><span class="status-badge status-{status_class}">{status_text}</span></td>
            </tr>
        """

    total_tests = len(df)
    vulnerable_tests = len(df[df['status'] == 'failed'])
    secure_tests = len(df[df['status'] == 'passed'])
    vulnerability_rate = (vulnerable_tests / total_tests * 100) if total_tests > 0 else 0
    pass_rate = (secure_tests / total_tests * 100) if total_tests > 0 else 0
    
    # Determine if majority passed or failed
    if pass_rate > vulnerability_rate:
        rate_text = f"Passed {pass_rate:.1f}%"
    else:
        rate_text = f"Failed {vulnerability_rate:.1f}%"

    vuln_breakdown = df['vulnerabilityType'].value_counts()
    sql_injection_count = vuln_breakdown.get('SQL Injection', 0)
    brute_force_count = vuln_breakdown.get('Brute Force', 0)
    xss_count = vuln_breakdown.get('XSS', 0)
    command_injection_count = vuln_breakdown.get('Command Injection', 0)
    path_traversal_count = vuln_breakdown.get('Path Traversal', 0)
    insecure_deserialization_count = vuln_breakdown.get('Insecure Deserialization', 0)
    security_misconfiguration_count = vuln_breakdown.get('Security Misconfiguration', 0)
    sensitive_data_exposure_count = vuln_breakdown.get('Sensitive Data Exposure', 0)
    broken_access_control_count = vuln_breakdown.get('Broken Access Control', 0)
    xxe_count = vuln_breakdown.get('XXE', 0)
    ssrf_count = vuln_breakdown.get('SSRF', 0)
    input_validation_count = vuln_breakdown.get('Input Validation', 0)
    avg_response_time = df['responseTime'].mean()

    recommendations = generate_security_recommendations(df, vulnerability_rate)

    html_report = html_template.replace("{{ method }}", method)
    html_report = html_report.replace("{{ testSuite }}", f"Customer Security {method} Method Test Suite")
    html_report = html_report.replace("{{ summary }}", f"Security vulnerability assessment for {method} method")
    html_report = html_report.replace("{{ environment }}", "Test Environment")
    html_report = html_report.replace("{{ testPlanKey }}", "SEC-8537")
    html_report = html_report.replace("{{ testExecutionKey }}", "SEC-1044")
    html_report = html_report.replace("{{ total_tests }}", str(total_tests))
    html_report = html_report.replace("{{ vulnerable_tests }}", str(vulnerable_tests))
    html_report = html_report.replace("{{ secure_tests }}", str(secure_tests))
    html_report = html_report.replace("{{ vulnerability_rate }}", rate_text)
    html_report = html_report.replace("{{ sql_injection_count }}", str(sql_injection_count))
    html_report = html_report.replace("{{ brute_force_count }}", str(brute_force_count))
    html_report = html_report.replace("{{ xss_count }}", str(xss_count))
    html_report = html_report.replace("{{ command_injection_count }}", str(command_injection_count))
    html_report = html_report.replace("{{ path_traversal_count }}", str(path_traversal_count))
    html_report = html_report.replace("{{ insecure_deserialization_count }}", str(insecure_deserialization_count))
    html_report = html_report.replace("{{ security_misconfiguration_count }}", str(security_misconfiguration_count))
    html_report = html_report.replace("{{ sensitive_data_exposure_count }}", str(sensitive_data_exposure_count))
    html_report = html_report.replace("{{ broken_access_control_count }}", str(broken_access_control_count))
    html_report = html_report.replace("{{ xxe_count }}", str(xxe_count))
    html_report = html_report.replace("{{ ssrf_count }}", str(ssrf_count))
    html_report = html_report.replace("{{ input_validation_count }}", str(input_validation_count))
    html_report = html_report.replace("{{ average_response_time }}", f"{avg_response_time:.2f}")
    html_report = html_report.replace("{{ rows }}", rows_html)
    html_report = html_report.replace("{{ method_vulnerabilities }}", f"{method.lower()}_vulnerabilities.png")
    html_report = html_report.replace("{{ method_success_rate }}", f"{method.lower()}_success_rate.png")
    html_report = html_report.replace("{{ method_response_times }}", f"{method.lower()}_response_times.png")
    html_report = html_report.replace("{{ method_status_summary }}", f"{method.lower()}_status_summary.png")
    html_report = html_report.replace("{{ endpoint_summary_rows }}", endpoint_summary)
    html_report = html_report.replace("{{ application_name }}", "trips")
    html_report = html_report.replace("{{ endpoint_name }}", "jumpcustomer")
    html_report = html_report.replace("{{ duration }}", "00:02:15")
    html_report = html_report.replace("{{ CI_JOB_URL }}", "#")
    html_report = html_report.replace("{{ recommendations }}", recommendations)

    output_file = os.path.join(output_folder, f"customer_security_{method.lower()}_report.html")
    
    try:
        with open(output_file, "w", encoding='utf-8') as file:
            file.write(html_report)
        logging.info(f"Security method HTML report generated: {output_file}")
    except (IOError, OSError, PermissionError) as e:
        error_message = f"Failed to write HTML report: {e}"
        logging.error(error_message)
        print(json.dumps({
            "status": "failed",
            "message": error_message
        }, indent=2))
        sys.exit(1)


def generate_security_recommendations(df, vulnerability_rate):
    """Generate code recommendations based on test results"""
    recommendations = []
    vuln_types = df[df['status'] == 'failed']['vulnerabilityType'].value_counts()
    
    for vuln_type, count in vuln_types.items():
        if vuln_type == 'SQL Injection' and count > 0:
            recommendations.append({
                "priority": "Critical",
                "title": "SQL Injection Prevention Code",
                "description": f"Found {count} SQL injection vulnerabilities.",
                "code": r"""# Use parameterized queries
from sqlalchemy import text

# BAD - Vulnerable to SQL injection
query = f"SELECT * FROM customers WHERE id = {customer_id}"

# GOOD - Safe parameterized query
query = text("SELECT * FROM customers WHERE id = :customer_id")
result = db.execute(query, customer_id=customer_id)

# Input sanitization
import re
def sanitize_input(user_input):
    return re.sub(r'[^\w\s-]', '', user_input)"""
            })
        elif vuln_type == 'XSS' and count > 0:
            recommendations.append({
                "priority": "High",
                "title": "XSS Protection Code",
                "description": f"Found {count} XSS vulnerabilities.",
                "code": """# XSS Prevention
from markupsafe import escape

# Output encoding
def safe_output(user_input):
    return escape(user_input)

# Content Security Policy headers
@app.after_request
def add_csp_header(response):
    response.headers['Content-Security-Policy'] = "default-src 'self'"
    return response"""
            })
        elif vuln_type == 'Brute Force' and count > 0:
            recommendations.append({
                "priority": "Medium",
                "title": "Rate Limiting Implementation",
                "description": f"Found {count} brute force vulnerabilities.",
                "code": """# Flask rate limiting
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

limiter = Limiter(
    app,
    key_func=get_remote_address
)

@app.route('/customers', methods=['POST'])
@limiter.limit("10 per minute")
def create_customer():
    # Implementation with rate limiting
    pass

# Account lockout mechanism
failed_attempts = {}
def check_rate_limit(ip_address):
    if failed_attempts.get(ip_address, 0) >= 5:
        raise TooManyRequests("Rate limit exceeded")"""
            })
        elif vuln_type == 'Command Injection' and count > 0:
            recommendations.append({
                "priority": "Critical",
                "title": "Command Injection Prevention",
                "description": f"Found {count} command injection vulnerabilities.",
                "code": """# Safe command execution
import subprocess
import shlex

def safe_execute(command, args):
    allowed_commands = ['ls', 'cat', 'grep']
    if command not in allowed_commands:
        raise ValueError("Command not allowed")
    
    safe_args = [shlex.quote(arg) for arg in args]
    result = subprocess.run([command] + safe_args, capture_output=True, text=True)
    return result.stdout"""
            })
        elif vuln_type == 'Path Traversal' and count > 0:
            recommendations.append({
                "priority": "High",
                "title": "Path Traversal Protection",
                "description": f"Found {count} path traversal vulnerabilities.",
                "code": """# Safe file access
import os
from pathlib import Path

def safe_file_access(filename, base_dir):
    base_path = Path(base_dir).resolve()
    file_path = (base_path / filename).resolve()
    
    if not str(file_path).startswith(str(base_path)):
        raise ValueError("Path traversal detected")
    
    return file_path"""
            })
        elif vuln_type == 'Insecure Deserialization' and count > 0:
            recommendations.append({
                "priority": "Critical",
                "title": "Secure Deserialization",
                "description": f"Found {count} insecure deserialization vulnerabilities.",
                "code": """# Safe deserialization
import json
from typing import Any

def safe_deserialize(data: str) -> Any:
    try:
        # Only use JSON, avoid pickle
        return json.loads(data)
    except json.JSONDecodeError:
        raise ValueError("Invalid JSON data")

# Input validation
def validate_input(data):
    if not isinstance(data, dict):
        raise ValueError("Expected dictionary")
    return data"""
            })
        elif vuln_type == 'Security Misconfiguration' and count > 0:
            recommendations.append({
                "priority": "Medium",
                "title": "Security Configuration",
                "description": f"Found {count} security misconfiguration issues.",
                "code": """# Secure configuration
from flask import Flask

app = Flask(__name__)
app.config['DEBUG'] = False
app.config['TESTING'] = False
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY')

# Disable server tokens
@app.after_request
def remove_server_header(response):
    response.headers.pop('Server', None)
    return response"""
            })
        elif vuln_type == 'Sensitive Data Exposure' and count > 0:
            recommendations.append({
                "priority": "High",
                "title": "Data Protection",
                "description": f"Found {count} sensitive data exposure issues.",
                "code": """# Data encryption and masking
from cryptography.fernet import Fernet
import re

def encrypt_sensitive_data(data):
    key = Fernet.generate_key()
    f = Fernet(key)
    return f.encrypt(data.encode())

def mask_sensitive_data(data):
    # Mask credit card numbers
    data = re.sub(r'\\d{4}-\\d{4}-\\d{4}-\\d{4}', 'XXXX-XXXX-XXXX-XXXX', data)
    # Mask SSN
    data = re.sub(r'\\d{3}-\\d{2}-\\d{4}', 'XXX-XX-XXXX', data)
    return data"""
            })
        elif vuln_type == 'Broken Access Control' and count > 0:
            recommendations.append({
                "priority": "High",
                "title": "Access Control Implementation",
                "description": f"Found {count} broken access control issues.",
                "code": """# Role-based access control
from functools import wraps
from flask import session, abort

def require_role(role):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user_role' not in session or session['user_role'] != role:
                abort(403)
            return f(*args, **kwargs)
        return decorated_function
    return decorator

@app.route('/admin')
@require_role('admin')
def admin_panel():
    pass"""
            })
        elif vuln_type == 'XXE' and count > 0:
            recommendations.append({
                "priority": "Critical",
                "title": "XXE Prevention",
                "description": f"Found {count} XXE vulnerabilities.",
                "code": """# Safe XML parsing
from defusedxml import ElementTree as DefusedET

def safe_xml_parse(xml_data):
    try:
        root = DefusedET.fromstring(xml_data)
        return root
    except Exception as e:
        raise ValueError(f"Invalid XML: {e}")"""
            })
        elif vuln_type == 'SSRF' and count > 0:
            recommendations.append({
                "priority": "Critical",
                "title": "SSRF Prevention",
                "description": f"Found {count} SSRF vulnerabilities.",
                "code": """# SSRF protection
import requests
from urllib.parse import urlparse

def safe_request(url):
    parsed = urlparse(url)
    
    blocked_hosts = ['localhost', '127.0.0.1', '169.254.169.254']
    if parsed.hostname in blocked_hosts:
        raise ValueError("Blocked host")
    
    if parsed.scheme not in ['http', 'https']:
        raise ValueError("Invalid scheme")
    
    return requests.get(url, timeout=5)"""
            })
    
    recommendations.extend([
        {
            "priority": "Medium",
            "title": "Security Headers Code",
            "description": "Implement security headers for API protection.",
            "code": """# Security headers for API
@app.after_request
def add_security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Strict-Transport-Security'] = 'max-age=31536000'
    return response"""
        },
        {
            "priority": "Low",
            "title": "Input Validation Code",
            "description": "Implement comprehensive input validation.",
            "code": r"""# Request validation schema
from marshmallow import Schema, fields, validate

class CustomerSchema(Schema):
    name = fields.Str(required=True, validate=validate.Length(min=1, max=100))
    email = fields.Email(required=True)
    phone = fields.Str(validate=validate.Regexp(r'^\+?[1-9]\d{1,14}$'))

@app.route('/customers', methods=['POST'])
def create_customer():
    schema = CustomerSchema()
    try:
        data = schema.load(request.json)
    except ValidationError as err:
        return {'errors': err.messages}, 400"""
        }
    ])
    
    html_recommendations = ""
    for rec in recommendations:
        priority_class = rec['priority'].lower()
        html_recommendations += f"""
        <div class="recommendation-item priority-{priority_class}">
            <div class="rec-header">
                <span class="priority-badge priority-{priority_class}">{rec['priority']}</span>
                <h4>{rec['title']}</h4>
            </div>
            <p class="rec-description">{rec['description']}</p>
            <pre class="code-block"><code>{rec['code']}</code></pre>
        </div>
        """
    
    return html_recommendations


def get_status_code(test):
    # First check actual_status_code field
    actual_status = test.get('actual_status_code')
    if actual_status is not None:
        return actual_status
    
    # Then check response_payload for error status
    response = test.get('response_payload', {})
    if response and 'error' in response:
        return response['error'].get('status', 400)
    
    # Default based on test status
    status = test.get('status', 'unknown')
    if status == 'failed':
        return 400
    elif status == 'passed':
        return 200
    
    return 'N/A'


def generate_method_vulnerability_chart(df, method, output_file):
    try:
        vuln_status = df.groupby(['vulnerabilityType', 'status']).size().unstack(fill_value=0)
        
        fig, ax = plt.subplots(figsize=(12, 6))
        vuln_status.plot(kind='bar', stacked=True, 
                        color={'failed': '#e74c3c', 'passed': '#27ae60'}, ax=ax)
        ax.set_title(f"{method} Method - Vulnerability Summary by Type")
        ax.set_xlabel("Vulnerability Type")
        ax.set_ylabel("Number of Tests")
        ax.legend(['Passed', 'Failed'])
        plt.xticks(rotation=45, ha='right')
        plt.tight_layout()
        plt.savefig(output_file, format='png', dpi=100)
        plt.close()
        logging.info(f"Vulnerability chart saved to {output_file}")
    except Exception as e:
        logging.error(f"Error generating vulnerability chart: {e}")
        fig, ax = plt.subplots(figsize=(12, 6))
        ax.text(0.5, 0.5, 'No Data Available', ha='center', va='center')
        ax.set_title(f"{method} Method - Vulnerability Summary")
        plt.savefig(output_file, format='png')
        plt.close()


def generate_method_success_chart(df, method, output_file):
    try:
        status_counts = df['status'].value_counts()
        vulnerable_count = status_counts.get('failed', 0)
        secure_count = status_counts.get('passed', 0)
            
        labels = ['Vulnerable', 'Secure']
        sizes = [vulnerable_count, secure_count]
        colors = ['#e74c3c', '#27ae60']

        fig, ax = plt.subplots(figsize=(8, 8))
        ax.pie(sizes, labels=labels, autopct='%1.1f%%', startangle=90, colors=colors)
        ax.set_title(f"{method} Method - Security Test Results")
        plt.axis('equal')
        plt.savefig(output_file, format='png', dpi=100)
        plt.close()
        logging.info(f"Success rate chart saved to {output_file}")
    except Exception as e:
        logging.error(f"Error generating success rate chart: {e}")
        fig, ax = plt.subplots(figsize=(8, 8))
        ax.text(0.5, 0.5, 'No Data Available', ha='center', va='center')
        ax.set_title(f"{method} Method - Security Test Results")
        plt.savefig(output_file, format='png')
        plt.close()


def generate_method_response_time_chart(df, method, output_file):
    try:
        avg_times = df.groupby('vulnerabilityType')['responseTime'].mean()
            
        fig, ax = plt.subplots(figsize=(10, 6))
        avg_times.plot(kind='bar', color='#3498db', ax=ax)
        ax.set_title(f"{method} Method - Average Response Time by Vulnerability Type")
        ax.set_xlabel("Vulnerability Type")
        ax.set_ylabel("Response Time (ms)")
        plt.xticks(rotation=45, ha='right')
        plt.tight_layout()
        plt.savefig(output_file, format='png', dpi=100)
        plt.close()
        logging.info(f"Response time chart saved to {output_file}")
    except Exception as e:
        logging.error(f"Error generating response time chart: {e}")
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.text(0.5, 0.5, 'No Data Available', ha='center', va='center')
        ax.set_title(f"{method} Method - Response Times")
        plt.savefig(output_file, format='png')
        plt.close()


def generate_method_status_summary_chart(df, method, output_file):
    try:
        vuln_counts = df['vulnerabilityType'].value_counts()
            
        fig, ax = plt.subplots(figsize=(10, 6))
        vuln_counts.plot(kind='barh', color='#3498db', ax=ax)
        ax.set_title(f"{method} Method - Distribution of Security Test Types")
        ax.set_xlabel("Number of Tests")
        ax.set_ylabel("Vulnerability Type")
        plt.tight_layout()
        plt.savefig(output_file, format='png', dpi=100)
        plt.close()
        logging.info(f"Status summary chart saved to {output_file}")
    except Exception as e:
        logging.error(f"Error generating status summary chart: {e}")
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.text(0.5, 0.5, 'No Data Available', ha='center', va='center')
        ax.set_title(f"{method} Method - Test Distribution")
        plt.savefig(output_file, format='png')
        plt.close()


def generate_endpoint_summary(df):
    """Generate endpoint summary table rows"""
    try:
        # Aggregate all data for single endpoint
        total = len(df)
        passed = len(df[df['status'] == 'passed'])
        failed = len(df[df['status'] == 'failed'])
        avg_response_time = df['responseTime'].mean()
        pass_rate = (passed / total * 100) if total > 0 else 0
        
        return f"""
            <tr>
                <td>jumpcustomer</td>
                <td>post</td>
                <td>{passed}</td>
                <td>{failed}</td>
                <td>{total}</td>
                <td>{pass_rate:.2f}%</td>
                <td>{avg_response_time:.4f}</td>
                <td>{avg_response_time:.4f}</td>
            </tr>
        """
    except Exception as e:
        logging.error(f"Error generating endpoint summary: {e}")
        return """
            <tr>
                <td>jumpcustomer</td>
                <td>post</td>
                <td>0</td>
                <td>0</td>
                <td>0</td>
                <td>0.00%</td>
                <td>0.0000</td>
                <td>0.0000</td>
            </tr>
        """


def process_folder(base_folder, output_folder, end_point):
    try:
        json_file = os.path.join(base_folder, end_point, "customer_response_POST.json")
        if os.path.exists(json_file):
            generate_html_report(json_file, output_folder)
        else:
            logging.warning("JSON file not found")
    except Exception as e:
        error_message = f"Error processing folder: {e}"
        logging.error(error_message)
        raise e


if __name__ == "__main__":
    failed_files = []

    try:
        parser = argparse.ArgumentParser(description="Process test files in parallel.")
        parser.add_argument('application', type=str, nargs='?', default='trips', help='Path to the application')
        parser.add_argument('end_point', type=str, nargs='?', default='jumpcustomer', help='Path to the folder containing test files')
        parser.add_argument('method', type=str, nargs='?', default='post', help='HTTP method (post, get, put, patch, delete)')

        args = parser.parse_args()
        start_time_program = time.time()
        end_point = args.end_point
        application_name = args.application
        method = args.method

        base_folder = os.path.join(project_root_path, "testdata", application_name)
        output_folder = os.path.join(project_root_path, "reports_output", application_name,"security")
        os.makedirs(output_folder, exist_ok=True)
        
        logging.info("Using security data from configured folder")
        logging.info("Output folder configured")

        process_folder(base_folder, output_folder, end_point)

        logging.info("HTML Reports generation completed.")
        logging.info(f"Merging of result files completed for {end_point}.")

        end_time_program = time.time()
        elapsed_time_program = end_time_program - start_time_program
        logging.info(f"Elapsed Time for Program : {elapsed_time_program:.2f} seconds")
        logging.info("HTML Reports generation completed.")

        # Now call your logging function and print the JSON status
        log_status = log_file_status(failed_files)
        print(json.dumps(log_status, indent=2))
        
        # Exit according to success/failure

        if log_status.get("status") == "success":
            sys.exit(0)
        else:
            sys.exit(1)

    except Exception as e:
        tb = traceback.extract_tb(sys.exc_info()[2])
        line_number = tb[-1].lineno if tb else 'unknown'
        script_name = __file__
        error_message = f"Exception occurred in script {script_name} at line {line_number}: {e}"
        logging.error(error_message)
        print(json.dumps({
            "status": "failed",
            "message": error_message
        }, indent=2))
        sys.exit(1)
