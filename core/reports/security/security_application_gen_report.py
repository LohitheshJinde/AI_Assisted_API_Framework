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
import html


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
param_key = "security_application_gen_report.log"
log_file_path = utils.configure_logging_api(param_key, current_date, current_dir)

def extract_attack_payload(test):
    """Extract the malicious payload from test data."""
    test_name = test.get('test_case_name', '').lower()
    
    # Map vulnerability types to payloads
    payload_map = {
        'xxe': '<?xml version="1.0"?><!DOCTYPE root [<!ENTITY test SYSTEM "file:///etc/passwd">]>',
        'xss': '<script>alert("XSS")</script>',
        'ssrf': 'http://169.254.169.254/latest/meta-data/',
        'broken_access_control': '../../../admin/users',
        'command_injection': '; cat /etc/passwd',
        'path_traversal': '../../../etc/passwd',
        'sql_injection': "' OR '1'='1' --",
        'brute_force': 'admin:password123',
        'insecure_deserialization': 'O:8:"stdClass":1:{s:4:"exec";s:10:"system(ls)";}',
        'security_misconfiguration': 'debug=true&admin=1',
        'sensitive_data_exposure': 'password=plaintext123'
    }
    
    # Find matching payload - check for generated_ prefix
    for vuln_type, payload in payload_map.items():
        if f'generated_{vuln_type}' in test_name or vuln_type in test_name:
            return payload
    
    return "N/A"


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
    elif 'injection' in test_lower:
        return 'Injection Attack'
    else:
        return 'Input Validation'


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


def calculate_security_score(df):
    total_tests = len(df)
    if total_tests == 0:
        return 100.0
    
    vulnerable_count = len(df[df['status'] == 'failed'])
    sql_injection_count = len(df[df['vulnerabilityType'] == 'SQL Injection'])
    brute_force_count = len(df[df['vulnerabilityType'] == 'Brute Force'])
    xss_count = len(df[df['vulnerabilityType'] == 'XSS'])
    command_injection_count = len(df[df['vulnerabilityType'] == 'Command Injection'])
    xxe_count = len(df[df['vulnerabilityType'] == 'XXE'])
    ssrf_count = len(df[df['vulnerabilityType'] == 'SSRF'])
    path_traversal_count = len(df[df['vulnerabilityType'] == 'Path Traversal'])
    insecure_deserialization_count = len(df[df['vulnerabilityType'] == 'Insecure Deserialization'])
    broken_access_control_count = len(df[df['vulnerabilityType'] == 'Broken Access Control'])
    
    vulnerability_penalty = (vulnerable_count / total_tests) * 50
    critical_penalty = ((sql_injection_count + xss_count + command_injection_count + xxe_count + ssrf_count) / total_tests) * 30
    high_penalty = ((brute_force_count + path_traversal_count + insecure_deserialization_count + broken_access_control_count) / total_tests) * 20
    
    score = 100 - vulnerability_penalty - critical_penalty - high_penalty
    return max(0, score)

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

def generate_html_report(json_file, output_folder):
    """Generate comprehensive HTML security report for application-level vulnerability testing."""
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

    test_data = tests.get("tests", tests) if isinstance(tests, dict) else tests
    filtered_tests = []
    
    for test in test_data:
        filtered_test = {
            "testKey": test.get("test_key", "N/A"),
            "testCaseName": test.get("test_case_name", "N/A"),
            "testDescription": test.get("test_description", "N/A"),
            "endpoint": "/customers",
            "method": "POST",
            "responseTime": test.get("elapsed_time_req", 0) * 1000,  # Convert to milliseconds
            "status": test.get("status", "unknown"),
            "vulnerabilityType": categorize_vulnerability(test.get("test_case_name", "")),
            "attackPayload": extract_attack_payload(test),
            "statusCode": get_status_code(test)
        }
        filtered_tests.append(filtered_test)
        
    df = pd.DataFrame(filtered_tests)

    # Generate endpoint summary data
    endpoint_summary = generate_endpoint_summary(df)
    
    generate_application_overview_chart(df, os.path.join(output_folder, "application_security_overview.png"))
    generate_risk_assessment_chart(df, os.path.join(output_folder, "application_risk_assessment.png"))
    generate_endpoint_security_chart(df, os.path.join(output_folder, "application_endpoint_security.png"))
    generate_vulnerability_trend_chart(df, os.path.join(output_folder, "application_vulnerability_trends.png"))

    template_file_path = os.path.join(project_root_path, "core", "reports", "security", "security_application_template.html")
    try:
        with open(template_file_path, 'r', encoding='utf-8') as file:
            html_template = file.read()
        logging.info("HTML template loaded successfully!")
    except Exception as e:
        logging.error(f"Template error: {e}")
        return
    
    # Generate table rows
    rows_list = []
    for _, row in df.iterrows():
        status_class = "vulnerable" if row["status"] == "failed" else "secure"
        status_text = "FAILED" if row["status"] == "failed" else "PASSED"
        response_time = float(row['responseTime']) if pd.notna(row['responseTime']) and row['responseTime'] is not None else 0.0
        
        # Determine risk level based on vulnerability type
        vuln_type = row['vulnerabilityType']
        if vuln_type in ['SQL Injection', 'XSS', 'Injection Attack', 'Command Injection', 'XXE', 'SSRF']:
            risk_level = 'Critical'
        elif vuln_type in ['Brute Force', 'Path Traversal', 'Insecure Deserialization', 'Broken Access Control']:
            risk_level = 'High'
        else:
            risk_level = 'Medium'
        
        rows_list.append(f"""
            <tr>
                <td>{html.escape(str(row['testKey']))}</td>
                <td>{html.escape(str(row['testCaseName']))}</td>
                <td>{html.escape(str(row['vulnerabilityType']))}</td>
                <td>{risk_level}</td>
                <td><div class="payload">{html.escape(str(row['attackPayload'])[:40])}...</div></td>
                <td>{response_time:.2f}ms</td>
                <td><span class="status-badge status-{status_class}">{status_text}</span></td>
            </tr>
        """)
    
    rows_html = ''.join(rows_list)

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
    
    # Log all vulnerability counts for debugging
    logging.info(f"Vulnerability breakdown: {dict(vuln_breakdown)}")
    
    # Risk assessment using vulnerability types
    critical_risks = sql_injection_count + xss_count + command_injection_count + xxe_count + ssrf_count
    high_risks = brute_force_count + path_traversal_count + insecure_deserialization_count + broken_access_control_count
    medium_risks = security_misconfiguration_count + sensitive_data_exposure_count
    
    avg_response_time = df['responseTime'].mean()
    security_score = calculate_security_score(df)

    recommendations = generate_security_recommendations(df, vulnerability_rate)

    html_report = html_template.replace("{{ applicationName }}", "trips")
    html_report = html_report.replace("{{ summary }}", "Security vulnerability assessment for the application")
    html_report = html_report.replace("{{ environment }}", "Test Environment")
    html_report = html_report.replace("{{ testPlanKey }}", "SEC-8537")
    html_report = html_report.replace("{{ testExecutionKey }}", "SEC-1044")
    html_report = html_report.replace("{{ total_tests }}", str(total_tests))
    html_report = html_report.replace("{{ vulnerable_tests }}", str(vulnerable_tests))
    html_report = html_report.replace("{{ secure_tests }}", str(secure_tests))
    html_report = html_report.replace("{{ vulnerability_rate }}", rate_text)
    html_report = html_report.replace("{{ critical_risks }}", str(critical_risks))
    html_report = html_report.replace("{{ high_risks }}", str(high_risks))
    html_report = html_report.replace("{{ medium_risks }}", str(medium_risks))
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
    html_report = html_report.replace("{{ average_response_time }}", f"{avg_response_time:.2f}")
    html_report = html_report.replace("{{ security_score }}", f"{security_score:.1f}")
    html_report = html_report.replace("{{ rows }}", rows_html)
    html_report = html_report.replace("{{ endpoint_summary_rows }}", endpoint_summary)
    html_report = html_report.replace("{{ application_security_overview }}", "application_security_overview.png")
    html_report = html_report.replace("{{ application_risk_assessment }}", "application_risk_assessment.png")
    html_report = html_report.replace("{{ application_endpoint_security }}", "application_endpoint_security.png")
    html_report = html_report.replace("{{ application_vulnerability_trends }}", "application_vulnerability_trends.png")
    html_report = html_report.replace("{{ recommendations }}", recommendations)

    output_file = os.path.join(output_folder, "customer_security_application_report.html")
    
    try:
        with open(output_file, "w", encoding='utf-8') as file:
            file.write(html_report)
        logging.info(f"Security application HTML report generated: {output_file}")
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
    failed_df = df[df['status'] == 'failed']
    vuln_types = failed_df['vulnerabilityType'].value_counts() if not failed_df.empty else pd.Series(dtype=int)
    
    for vuln_type, count in vuln_types.items():
        if vuln_type == 'SQL Injection' and count > 0:
            recommendations.append({
                "priority": "Critical",
                "title": "Application-Wide SQL Injection Fix",
                "description": f"Found {count} SQL injection vulnerabilities across the application.",
                "code": """# Database connection with ORM
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

class DatabaseManager:
    def __init__(self, connection_string):
        self.engine = create_engine(connection_string)
        self.Session = sessionmaker(bind=self.engine)
    
    def safe_query(self, query, **params):
        session = self.Session()
        try:
            result = session.execute(text(query), params)
            return result.fetchall()
        finally:
            session.close()

# Usage
db = DatabaseManager('postgresql://user:pass@localhost/db')
result = db.safe_query(
    "SELECT * FROM customers WHERE id = :customer_id",
    customer_id=customer_id
)"""
            })
        elif vuln_type == 'Brute Force' and count > 0:
            recommendations.append({
                "priority": "Medium",
                "title": "Application-Wide Rate Limiting",
                "description": f"Found {count} brute force vulnerabilities.",
                "code": """# Global rate limiting configuration
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import redis

# Redis-backed rate limiter
limiter = Limiter(
    app,
    key_func=get_remote_address,
    storage_uri="redis://localhost:6379",
    default_limits=["1000 per day", "100 per hour"]
)

# Apply to all routes
@app.before_request
def limit_remote_addr():
    limiter.check()

# Specific endpoint limits
@app.route('/customers', methods=['POST'])
@limiter.limit("5 per minute")
def create_customer():
    pass"""
            })
        elif vuln_type == 'XSS' and count > 0:
            recommendations.append({
                "priority": "Critical",
                "title": "XSS Protection",
                "description": f"Found {count} XSS vulnerabilities.",
                "code": """# XSS protection
from markupsafe import escape
from flask import request

@app.before_request
def sanitize_input():
    if request.json:
        sanitized = {}
        for key, value in request.json.items():
            if isinstance(value, str):
                sanitized[key] = escape(value)
            else:
                sanitized[key] = value
        request.json = sanitized"""
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
    # Whitelist allowed commands
    allowed_commands = ['ls', 'cat', 'grep']
    if command not in allowed_commands:
        raise ValueError("Command not allowed")
    
    # Sanitize arguments
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
    
    # Ensure file is within base directory
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
import xml.etree.ElementTree as ET
from defusedxml import ElementTree as DefusedET

def safe_xml_parse(xml_data):
    # Use defusedxml to prevent XXE
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
    
    # Block internal IPs
    blocked_hosts = ['localhost', '127.0.0.1', '169.254.169.254']
    if parsed.hostname in blocked_hosts:
        raise ValueError("Blocked host")
    
    # Only allow specific schemes
    if parsed.scheme not in ['http', 'https']:
        raise ValueError("Invalid scheme")
    
    return requests.get(url, timeout=5)"""
            })
    
    recommendations.extend([
        {
            "priority": "Medium",
            "title": "Application Security Configuration",
            "description": "Comprehensive security hardening for the entire application.",
            "code": """# Application security configuration
from flask_talisman import Talisman
from flask_cors import CORS

# Security headers and HTTPS enforcement
Talisman(app, force_https=True)

# CORS configuration
CORS(app, origins=['https://yourdomain.com'])

# Security middleware
@app.before_request
def security_headers():
    if request.endpoint and request.method == 'POST':
        # CSRF protection
        if not validate_csrf_token(request.headers.get('X-CSRF-Token')):
            abort(403)

@app.after_request
def add_security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    return response"""
        },
        {
            "priority": "Low",
            "title": "Security Monitoring & Logging",
            "description": "Implement comprehensive security monitoring.",
            "code": """# Security monitoring setup
import logging
from datetime import datetime

# Security event logger
security_logger = logging.getLogger('security')
security_handler = logging.FileHandler('security.log')
security_logger.addHandler(security_handler)

def log_security_event(event_type, details, request):
    security_logger.warning({
        'timestamp': datetime.utcnow().isoformat(),
        'event': event_type,
        'ip': request.remote_addr,
        'user_agent': request.headers.get('User-Agent'),
        'details': details
    })

# Usage in routes
@app.route('/customers', methods=['POST'])
def create_customer():
    try:
        # Process request
        pass
    except SecurityException as e:
        log_security_event('SECURITY_VIOLATION', str(e), request)
        abort(403)"""
        }
    ])
    
    if not recommendations:
        return "<p>No specific recommendations at this time.</p>"
    
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



def generate_application_overview_chart(df, output_file):
    try:
        status_counts = df['status'].value_counts()
        vulnerable_count = status_counts.get('failed', 0)
        secure_count = status_counts.get('passed', 0)
            
        labels = ['Vulnerable', 'Secure']
        sizes = [vulnerable_count, secure_count]
        colors = ['#e74c3c', '#27ae60']

        fig, ax = plt.subplots(figsize=(8, 8))
        ax.pie(sizes, labels=labels, autopct='%1.1f%%', startangle=90, colors=colors)
        ax.set_title("Application Security Overview")
        plt.axis('equal')
        plt.savefig(output_file, format='png', dpi=100)
        plt.close()
        logging.info(f"Application overview chart saved to {output_file}")
    except Exception as e:
        logging.error(f"Error generating overview chart: {str(e)}")
        fig, ax = plt.subplots(figsize=(8, 8))
        ax.text(0.5, 0.5, 'No Data Available', ha='center', va='center')
        ax.set_title("Application Security Overview")
        plt.savefig(output_file, format='png')
        plt.close()

def generate_risk_assessment_chart(df, output_file):
    try:
        vuln_status = df.groupby(['vulnerabilityType', 'status']).size().unstack(fill_value=0)
        
        fig, ax = plt.subplots(figsize=(12, 6))
        vuln_status.plot(kind='bar', stacked=True, 
                        color={'failed': '#e74c3c', 'passed': '#27ae60'}, ax=ax)
        ax.set_title("Application Risk Assessment")
        ax.set_xlabel("Vulnerability Type")
        ax.set_ylabel("Number of Tests")
        ax.legend(['Passed', 'Failed'])
        plt.xticks(rotation=45, ha='right')
        plt.tight_layout()
        plt.savefig(output_file, format='png', dpi=100)
        plt.close()
        logging.info(f"Risk assessment chart saved to {output_file}")
    except Exception as e:
        logging.error(f"Error generating risk assessment chart: {str(e)}")
        fig, ax = plt.subplots(figsize=(12, 6))
        ax.text(0.5, 0.5, 'No Data Available', ha='center', va='center')
        ax.set_title("Application Risk Assessment")
        plt.savefig(output_file, format='png')
        plt.close()

def generate_endpoint_security_chart(df, output_file):
    try:
        avg_times = df.groupby('vulnerabilityType')['responseTime'].mean()
            
        fig, ax = plt.subplots(figsize=(10, 6))
        avg_times.plot(kind='bar', color='#3498db', ax=ax)
        ax.set_title("Application Endpoint Security - Response Times")
        ax.set_xlabel("Vulnerability Type")
        ax.set_ylabel("Response Time (ms)")
        plt.xticks(rotation=45, ha='right')
        plt.tight_layout()
        plt.savefig(output_file, format='png', dpi=100)
        plt.close()
        logging.info(f"Endpoint security chart saved to {output_file}")
    except Exception as e:
        logging.error(f"Error generating endpoint security chart: {str(e)}")
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.text(0.5, 0.5, 'No Data Available', ha='center', va='center')
        ax.set_title("Application Endpoint Security")
        plt.savefig(output_file, format='png')
        plt.close()


def generate_vulnerability_trend_chart(df, output_file):
    try:
        vuln_counts = df['vulnerabilityType'].value_counts()
            
        fig, ax = plt.subplots(figsize=(10, 6))
        vuln_counts.plot(kind='barh', color='#3498db', ax=ax)
        ax.set_title("Application Vulnerability Trends")
        ax.set_xlabel("Number of Tests")
        ax.set_ylabel("Vulnerability Type")
        plt.tight_layout()
        plt.savefig(output_file, format='png', dpi=100)
        plt.close()
        logging.info(f"Vulnerability trend chart saved to {output_file}")
    except Exception as e:
        logging.error(f"Error generating vulnerability trend chart: {str(e)}")
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.text(0.5, 0.5, 'No Data Available', ha='center', va='center')
        ax.set_title("Application Vulnerability Trends")
        plt.savefig(output_file, format='png')
        plt.close()
    
def process_folder(base_folder, output_folder, application_name):
    try:
        # For application level, look for all endpoint folders and aggregate data
        all_tests = []
        endpoint_folders = [d for d in os.listdir(base_folder) if os.path.isdir(os.path.join(base_folder, d))]
        
        for endpoint in endpoint_folders:
            json_file = os.path.join(base_folder, endpoint, "customer_response_POST.json")
            if os.path.exists(json_file):
                with open(json_file, 'r') as file:
                    tests = json.load(file)
                    test_data = tests.get("tests", tests) if isinstance(tests, dict) else tests
                    all_tests.extend(test_data)
        
        if all_tests:
            # Create a temporary aggregated file
            temp_file = os.path.join(output_folder, "temp_aggregated_tests.json")
            with open(temp_file, 'w') as file:
                json.dump(all_tests, file)
            generate_html_report(temp_file, output_folder)
            os.remove(temp_file)  # Clean up temp file
        else:
            logging.warning("No JSON files found for application report")
    except Exception as e:
        error_message = f"Error processing folder: {e}"
        logging.error(error_message)
        raise e


if __name__ == "__main__":
    failed_files = []

    try:
        parser = argparse.ArgumentParser(description="Process test files in parallel.")
        parser.add_argument('application', type=str, nargs='?', default='trips', help='Path to the application')
        parser.add_argument('method', type=str, nargs='?', default='post', help='HTTP method (post, get, put, patch, delete)')

        args = parser.parse_args()
        start_time_program = time.time()
        method = args.method
        application_name = args.application

        base_folder = os.path.join(project_root_path, "testdata", application_name)
        output_folder = os.path.join(project_root_path, "reports_output", application_name, "security")
        os.makedirs(output_folder, exist_ok=True)
        
        logging.info("Using security data from configured folder")
        logging.info("Output folder configured")

        process_folder(base_folder, output_folder, application_name)

        logging.info("HTML Reports generation completed.")
        logging.info(f"Application report generation completed for {application_name}.")

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