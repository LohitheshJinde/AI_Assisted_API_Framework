import json
import os
import sys
import logging
import time
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from concurrent.futures import ProcessPoolExecutor
from jinja2 import Template
from dotenv import load_dotenv
import argparse
import traceback
import requests

# Load configuration from the config file
project_root_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
sys.path.append(project_root_path)

try:
    from core.utils import utils, gitlab_utils
except ImportError:
    # Fallback for basic functionality without utils
    class MockUtils:
        current_date = time.strftime('%Y%m%d')
        @staticmethod
        def configure_logging_api(param_key, current_date, current_dir):
            logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
            return None
    
    class MockGitlabUtils:
        @staticmethod
        def get_gitlab_variable(var_name):
            return os.getenv(var_name, "")
    
    utils = MockUtils()
    gitlab_utils = MockGitlabUtils()

if not os.getenv('CI_PIPELINE'):  # GitLab CI/CD sets the CI environment variable
    print("Local environment detected. Loading variables from .env file...")
    # Load configuration from the .env file
    load_dotenv(dotenv_path=".env", verbose=True, override=True)
else:
    print("CI/CD environment detected. Using CI/CD provided variables...")

# Get the environment from the variable (from .env for local or directly from CI/CD)
environment = os.getenv("ENVIRONMENT")

if environment:
    print(f"Using environment-specific variables for: {environment}")
else:
    print("No specific environment set, assuming CI/CD environment variables are provided...")

# Set up logging
current_dir = os.path.dirname(os.path.abspath(__file__))
current_date = utils.current_date
param_key = "endpoint_method_gen_report.log"
log_file_path = utils.configure_logging_api(param_key, current_date, current_dir)

def generate_html_report(json_file, output_folder):
    """Generate HTML report and charts from a JSON file."""
    try:
        with open(json_file, 'r') as file:
            json_data = json.load(file)
        logging.info(f"Loaded JSON data from {json_file}")
    except FileNotFoundError:
        logging.error(f"Report Input File not found: {json_file}")
        exit(1)
    except json.JSONDecodeError as e:
        logging.error(f"Error decoding JSON: {e}")
        exit(1)

    # Convert JSON tests section into a DataFrame
    tests = json_data.get("tests", [])

    # Keep only required attributes and add contract testing data
    filtered_tests = []
    for test in tests:
        filtered_test = {
            "testKey": test["testKey"],
            "testCaseName": test["testCaseName"],
            "testDescription": test["testDescription"],
            "endpointMethod": test["endpointMethod"],
            "responseTime": test["responseTime"],
            "testCaseTime": test["testCaseTime"],
            "status": test.get("overallStatus", test.get("status", "unknown")),
        }
        
        # Handle contract testing results
        if "contractTestResult" in test:
            contract_result = test["contractTestResult"]
            filtered_test["contractStatus"] = contract_result.get("contractStatus", "N/A")
            
            # Extract request issues
            request_issues = contract_result.get("request_issues", {})
            filtered_test["reqMissingAttrs"] = len(request_issues.get("missing_attributes", []))
            filtered_test["reqMissingAttrsList"] = request_issues.get("missing_attributes", [])
            filtered_test["reqTypeMismatches"] = len(request_issues.get("type_mismatches", []))
            filtered_test["reqTypeMismatchesList"] = request_issues.get("type_mismatches", [])
            filtered_test["reqExtraAttrs"] = len(request_issues.get("extra_attributes", []))
            filtered_test["reqExtraAttrsList"] = request_issues.get("extra_attributes", [])
            filtered_test["reqDefaultMismatches"] = len(request_issues.get("default_mismatches", []))
            filtered_test["reqDefaultMismatchesList"] = request_issues.get("default_mismatches", [])
            
            # Extract response issues
            response_issues = contract_result.get("response_issues", {})
            filtered_test["respMissingAttrs"] = len(response_issues.get("missing_attributes", []))
            filtered_test["respMissingAttrsList"] = response_issues.get("missing_attributes", [])
            filtered_test["respTypeMismatches"] = len(response_issues.get("type_mismatches", []))
            filtered_test["respTypeMismatchesList"] = response_issues.get("type_mismatches", [])
            filtered_test["respExtraAttrs"] = len(response_issues.get("extra_attributes", []))
            filtered_test["respExtraAttrsList"] = response_issues.get("extra_attributes", [])
            filtered_test["respDefaultMismatches"] = len(response_issues.get("default_mismatches", []))
            filtered_test["respDefaultMismatchesList"] = response_issues.get("default_mismatches", [])
            
            # Total issues count
            total_issues = (
                filtered_test["reqMissingAttrs"] + filtered_test["reqTypeMismatches"] + 
                filtered_test["reqExtraAttrs"] + filtered_test["reqDefaultMismatches"] +
                filtered_test["respMissingAttrs"] + filtered_test["respTypeMismatches"] + 
                filtered_test["respExtraAttrs"] + filtered_test["respDefaultMismatches"]
            )
            filtered_test["contractIssues"] = total_issues
        else:
            filtered_test["contractStatus"] = "N/A"
            filtered_test["contractIssues"] = 0
            # Set default values for all contract fields
            for field in ["reqMissingAttrs", "reqTypeMismatches", "reqExtraAttrs", "reqDefaultMismatches",
                         "respMissingAttrs", "respTypeMismatches", "respExtraAttrs", "respDefaultMismatches"]:
                filtered_test[field] = 0
            for field in ["reqMissingAttrsList", "reqTypeMismatchesList", "reqExtraAttrsList", "reqDefaultMismatchesList",
                         "respMissingAttrsList", "respTypeMismatchesList", "respExtraAttrsList", "respDefaultMismatchesList"]:
                filtered_test[field] = []
            
        # Legacy fields for backward compatibility
        filtered_test["unmatched"] = test.get("unmatched", 0)
        filtered_test["unmatchedAttributes"] = test.get("unmatchedAttributes", [])
        
        # Add overall passed status (both API and contract must pass)
        api_passed = filtered_test["status"] == "passed"
        contract_passed = filtered_test.get("contractStatus") == "passed"
        filtered_test["overallPassed"] = "PASS" if (api_passed and contract_passed) else "FAIL"
        
        filtered_tests.append(filtered_test)
        
    df = pd.DataFrame(filtered_tests)
    dfc = pd.DataFrame(tests)

    generate_status_summary_chart(dfc, output_file=os.path.join(output_folder, "test_case_status_summary.png"))
    generate_response_time_chart(dfc, output_file=os.path.join(output_folder, "response_time_comparison.png"))
    generate_status_over_time_chart(dfc, output_file=os.path.join(output_folder, "test_case_status_over_time.png"))
    generate_pass_rate_chart(dfc, output_file=os.path.join(output_folder, "pass_rate_chart.png"))

    # Read the HTML template (use contract testing template)
    template_file_path = os.path.join(project_root_path, "core", "reports", "contract_testing", "endpoint_method_template_bootstrap.html")
    try:
        with open(template_file_path, 'r') as file:
            html_template = file.read()
        logging.info("HTML template loaded successfully!")
    except FileNotFoundError:
        logging.error(f"HTML template not found: {template_file_path}")
        exit(1)

    # Generate table rows from the DataFrame with color highlighting
    rows = ""
    for _, row in df.iterrows():
        # Processing row data
        status_class = "failed" if row["status"] == "failed" else "passed"
        row_color = "#eca386" if row["status"] == "failed" else "#94a4f1"  # Highlight color based on status
        
        # Generate Bootstrap enhanced row with modern styling
        
        req_missing = "|".join(row.get('reqMissingAttrsList', []))
        req_type_mismatch = "|".join(row.get('reqTypeMismatchesList', []))
        req_extra = "|".join(row.get('reqExtraAttrsList', []))
        req_default = "|".join(row.get('reqDefaultMismatchesList', []))
        resp_missing = "|".join(row.get('respMissingAttrsList', []))
        resp_type_mismatch = "|".join(row.get('respTypeMismatchesList', []))
        resp_extra = "|".join(row.get('respExtraAttrsList', []))
        resp_default = "|".join(row.get('respDefaultMismatchesList', []))
        
        desc = row['testDescription'][:40] + '...' if len(row['testDescription']) > 40 else row['testDescription']
        status_badge = f'<span class="status-badge status-passed"><i class="bi bi-check-circle"></i> PASS</span>' if row['status'] == 'passed' else f'<span class="status-badge status-failed"><i class="bi bi-x-circle"></i> FAIL</span>'
        contract_badge = f'<span class="status-badge status-passed"><i class="bi bi-check-circle"></i> PASS</span>' if row.get('contractStatus') == 'passed' else f'<span class="status-badge status-failed"><i class="bi bi-x-circle"></i> FAIL</span>'
        
        rows += f"""
            <tr>
                <td><strong>{row['testKey']}</strong></td>
                <td>{row['testCaseName']}</td>
                <td><span title="{row['testDescription']}">{desc}</span></td>
                <td><code class="text-primary">{row['endpointMethod']}</code></td>
                <td>{row['responseTime']:.2f}</td>
                <td>{row['testCaseTime']:.2f}</td>
                <td>{status_badge}</td>
                <td>{contract_badge}</td>
                <td><span class="badge bg-{'danger' if row.get('contractIssues', 0) > 0 else 'success'} fs-6">{row.get('contractIssues', 0)}</span></td>
                <td><button class="btn contract-btn {'zero' if row.get('reqMissingAttrs', 0) == 0 else ''}" onclick="toggleDetails('{row['testKey']}', 'reqMissing', '{req_missing}', this)" {'disabled' if row.get('reqMissingAttrs', 0) == 0 else ''}>{row.get('reqMissingAttrs', 0)}</button></td>
                <td><button class="btn contract-btn {'zero' if row.get('reqTypeMismatches', 0) == 0 else ''}" onclick="toggleDetails('{row['testKey']}', 'reqTypeMismatch', '{req_type_mismatch}', this)" {'disabled' if row.get('reqTypeMismatches', 0) == 0 else ''}>{row.get('reqTypeMismatches', 0)}</button></td>
                <td><button class="btn contract-btn {'zero' if row.get('reqExtraAttrs', 0) == 0 else ''}" onclick="toggleDetails('{row['testKey']}', 'reqExtra', '{req_extra}', this)" {'disabled' if row.get('reqExtraAttrs', 0) == 0 else ''}>{row.get('reqExtraAttrs', 0)}</button></td>
                <td><button class="btn contract-btn {'zero' if row.get('reqDefaultMismatches', 0) == 0 else ''}" onclick="toggleDetails('{row['testKey']}', 'reqDefault', '{req_default}', this)" {'disabled' if row.get('reqDefaultMismatches', 0) == 0 else ''}>{row.get('reqDefaultMismatches', 0)}</button></td>
                <td><button class="btn contract-btn {'zero' if row.get('respMissingAttrs', 0) == 0 else ''}" onclick="toggleDetails('{row['testKey']}', 'respMissing', '{resp_missing}', this)" {'disabled' if row.get('respMissingAttrs', 0) == 0 else ''}>{row.get('respMissingAttrs', 0)}</button></td>
                <td><button class="btn contract-btn {'zero' if row.get('respTypeMismatches', 0) == 0 else ''}" onclick="toggleDetails('{row['testKey']}', 'respTypeMismatch', '{resp_type_mismatch}', this)" {'disabled' if row.get('respTypeMismatches', 0) == 0 else ''}>{row.get('respTypeMismatches', 0)}</button></td>
                <td><button class="btn contract-btn {'zero' if row.get('respExtraAttrs', 0) == 0 else ''}" onclick="toggleDetails('{row['testKey']}', 'respExtra', '{resp_extra}', this)" {'disabled' if row.get('respExtraAttrs', 0) == 0 else ''}>{row.get('respExtraAttrs', 0)}</button></td>
                <td><button class="btn contract-btn {'zero' if row.get('respDefaultMismatches', 0) == 0 else ''}" onclick="toggleDetails('{row['testKey']}', 'respDefault', '{resp_default}', this)" {'disabled' if row.get('respDefaultMismatches', 0) == 0 else ''}>{row.get('respDefaultMismatches', 0)}</button></td>
                <td>{row['unmatched']}</td>
                <td><span title="{row['unmatchedAttributes']}">{len(str(row['unmatchedAttributes'])) if row['unmatchedAttributes'] else 0}</span></td>
                <td><span class="status-badge {'status-passed' if row.get('overallPassed') == 'PASS' else 'status-failed'}"><i class="bi bi-{'check-circle' if row.get('overallPassed') == 'PASS' else 'x-circle'}"></i> {row.get('overallPassed', 'N/A')}</span></td>
            </tr>
        """
    # Generate CI JOB URL
    ci_job_id = os.getenv("CI_JOB_ID", "")  # Default to empty string if None
    ci_job_url = os.getenv("CI_JOB_URL", "")

    ci_job_full_url = ci_job_url + ci_job_id  # Concatenation

    # Populate the template
    html_report = html_template.replace("{{ testSuite }}", json_data["info"]["testSuite"])
    html_report = html_report.replace("{{ summary }}", json_data["info"]["summary"])
    html_report = html_report.replace("{{ duration }}", json_data['info']['duration'])
    html_report = html_report.replace("{{ environment }}", json_data["info"]["environment"])
    html_report = html_report.replace("{{ testPlanKey }}", json_data["info"]["testPlanKey"])
    html_report = html_report.replace("{{ testExecutionKey }}", json_data["info"]["testExecutionKey"])
    html_report = html_report.replace("{{ CI_JOB_URL }}", ci_job_full_url)
    html_report = html_report.replace("{{ total }}", str(json_data["info"]["results"]["total"]))
    html_report = html_report.replace("{{ passed }}", str(json_data["info"]["results"]["passed"]))
    html_report = html_report.replace("{{ failed }}", str(json_data["info"]["results"]["failed"]))
    html_report = html_report.replace("{{ pass_rate }}", f"{json_data['info']['results']['pass rate %']}%")
    html_report = html_report.replace("{{ average_response_time }}", f"{json_data['info']['results']['average_response_time']}")
    html_report = html_report.replace("{{ average_test_case_time }}", f"{json_data['info']['results']['average_test_case_time']}")
    html_report = html_report.replace("{{ rows }}", rows)
    html_report = html_report.replace("{{ pass_rate_chart }}", f"{output_folder}/pass_rate_chart.png")
    html_report = html_report.replace("{{ test_case_status_summary }}", f"{output_folder}/test_case_status_summary.png")
    html_report = html_report.replace("{{ response_time_comparison }}", f"{output_folder}/response_time_comparison.png")
    html_report = html_report.replace("{{ test_case_status_over_time }}", f"{output_folder}/test_case_status_over_time.png")

    output_file = os.path.join(output_folder, os.path.basename(json_file).replace(".json", ".html"))
    with open(output_file, "w") as file:
        file.write(html_report)
    logging.info(f"HTML report generated: {output_file}")

# Function to create the Test Case Status Summary chart
def generate_status_summary_chart(df, output_file="status_summary_chart.png"):
    # Use overallStatus if available, otherwise fall back to status
    status_col = 'overallStatus' if 'overallStatus' in df.columns else 'status'
    if status_col in df.columns:
        df[status_col].value_counts().plot(kind="bar", color=["green", "red"])
        plt.title("Test Case Status Summary")
        plt.xlabel("Status")
        plt.ylabel("Count")
        plt.savefig(output_file)
        plt.close()
        logging.info(f"Status summary chart saved: {output_file}")
    else:
        logging.warning(f"No status column found for chart generation")

# Function to create the Response Time Comparison chart
def generate_response_time_chart(df, output_file="response_time_chart.png"):
    # Use overallStatus if available, otherwise fall back to status
    status_col = 'overallStatus' if 'overallStatus' in df.columns else 'status'
    if status_col in df.columns and 'responseTime' in df.columns:
        plt.figure(figsize=(10, 6))
        sns.boxplot(data=df, x=status_col, y="responseTime", hue=status_col,
                    palette={"passed": "green", "failed": "red"}, dodge=False)
        plt.title("Response Time Comparison")
        plt.xlabel("Status")
        plt.ylabel("Response Time (ms)")
        plt.legend([], [], frameon=False)  # Hide the legend
        plt.savefig(output_file)
        plt.close()
        logging.info(f"Response time chart saved: {output_file}")
    else:
        logging.warning(f"Missing required columns for response time chart")

# Function to create the Test Case Status Over Time chart
def generate_status_over_time_chart(df, output_file="status_over_time_chart.png"):
    # Use overallStatus if available, otherwise fall back to status
    status_col = 'overallStatus' if 'overallStatus' in df.columns else 'status'
    if status_col in df.columns and 'startDate' in df.columns:
        df["startDate"] = pd.to_datetime(df["startDate"])  # Ensure startDate is a datetime object
        status_counts_over_time = df.groupby([df["startDate"].dt.date, status_col]).size().unstack(fill_value=0)
        status_counts_over_time.plot(kind="line", marker="o", colormap="coolwarm")
        plt.title("Test Case Status Over Time")
        plt.xlabel("Date")
        plt.ylabel("Count")
        plt.legend(title="Status")
        plt.savefig(output_file)
        plt.close()
        logging.info(f"Status over time chart saved: {output_file}")
    else:
        logging.warning(f"Missing required columns for status over time chart")

# Function to create the Test Case Pass Rate Percentage Chart
def generate_pass_rate_chart(df, output_file="pass_rate_chart.png"):
    # Use overallStatus if available, otherwise fall back to status
    status_col = 'overallStatus' if 'overallStatus' in df.columns else 'status'
    if status_col in df.columns:
        # Calculate pass and fail counts
        status_counts = df[status_col].value_counts()
        pass_count = status_counts.get("passed", 0)
        fail_count = status_counts.get("failed", 0)
        total = pass_count + fail_count

        # Calculate pass rate percentage
        pass_rate = (pass_count / total) * 100 if total > 0 else 0
        fail_rate = 100 - pass_rate

        # Prepare data for the pie chart
        labels = ["Passed", "Failed"]
        sizes = [pass_rate, fail_rate]
        colors = ["green", "red"]

        # Plot the pie chart
        plt.figure(figsize=(8, 8))
        plt.pie(sizes, labels=labels, autopct="%.2f%%", startangle=90, colors=colors)
        plt.title("Pass Rate Percentage")
        plt.axis("equal")  # Equal aspect ratio ensures the pie chart is circular
        plt.savefig(output_file)
        plt.close()
        logging.info(f"Pass rate percentage chart saved: {output_file}")
    else:
        logging.warning(f"No status column found for pass rate chart")

def update_test_execution_info(json_file):
    """
    Update the 'info' section of a JSON file with test execution details from GitLab variables.
    """
    try:
        # Load the JSON file
        with open(json_file, 'r') as file:
            data = json.load(file)
        
        if os.getenv("CI_PIPELINE"):
            test_execution_key = gitlab_utils.get_gitlab_variable("TEST_EXECUTION_KEY")
            test_execution_id = gitlab_utils.get_gitlab_variable("TEST_EXECUTION_ID")
            logging.info("[INFO] get CICD pipeline variables with Test Execution details.")
        else:
            test_execution_key = os.getenv("TEST_EXECUTION_KEY")
            test_execution_id = os.getenv("TEST_EXECUTION_ID")
            logging.info("[INFO] get .env file with Test Execution details.")

        # Update the `info` section
        #test_execution_key = get_gitlab_variable("TEST_EXECUTION_KEY")
        #test_execution_id = get_gitlab_variable("TEST_EXECUTION_ID")
        
        if not data.get("info"):
            data["info"] = {}

        data["info"]["testExecutionKey"] = test_execution_key
        data["info"]["testExecutionId"] = test_execution_id
        
        logging.info(f"[INFO] Updated test execution info in {json_file}.")
        
        # Save the updated JSON back to the same file
        with open(json_file, 'w') as file:
            json.dump(data, file, indent=4)
        logging.info(f"[INFO] Updated test execution info and saved file: {json_file}.")
        
        return data
    
    except Exception as e:
        logging.error(f"[ERROR] Failed to update test execution info in {json_file}: {e}")
        return None
    
def process_folder(folder_path, output_folder, end_point):
    """
    Process contract testing JSON files and generate HTML reports.
    """
    print(f"Processing folder: {folder_path}")
    print(f"Output folder: {output_folder}")
    print(f"Endpoint: {end_point}")
    
    json_files = [
        os.path.join(root, file)
        for root, _, files in os.walk(folder_path)
        for file in files if file.endswith("report_data.json")
    ]
    
    print(f"Found {len(json_files)} JSON files: {json_files}")
    
    for json_file in json_files:
        subfolder = os.path.dirname(json_file).split(os.path.sep)[-1]
        print(f"Processing subfolder: {subfolder}")
        
        # Process contract testing files
        if ('_' in subfolder or '-' in subfolder) and (f"{end_point}" in subfolder or end_point == 'cases'):
            print(f"Matched subfolder: {subfolder}")
            subfolder_output = os.path.join(output_folder, subfolder)
            os.makedirs(subfolder_output, exist_ok=True)
            print(f"Created output directory: {subfolder_output}")
            
            # Update test execution info
            updated_json_data = update_test_execution_info(json_file)
            
            if updated_json_data:
                # Generate HTML report with contract testing integration
                print(f"Generating HTML report for: {json_file}")
                generate_html_report(json_file, subfolder_output)
            else:
                logging.error(f"[ERROR] Skipping file {json_file} due to update failure.")
        else:
            print(f"Skipped subfolder: {subfolder} (doesn't match criteria)")

def generate_index_html(output_folder):
    """Generate index HTML file with links to all reports."""
    links = []
    for root, _, files in os.walk(output_folder):
        for file in files:
            if file.endswith(".html"):
                relative_path = os.path.relpath(os.path.join(root, file), output_folder)
                links.append(f"<li><a href='{relative_path}'>{file}</a></li>")
    index_content = f"<html><body><h1>Index of Reports</h1><ul>{''.join(links)}</ul></body></html>"
    index_file = os.path.join(output_folder, "index.html")
    with open(index_file, "w") as file:
        file.write(index_content)
    logging.info(f"Index file generated: {index_file}")

if __name__ == "__main__":
    try:
        parser = argparse.ArgumentParser(description="Process test files in parallel.")
        parser.add_argument('application', type=str, nargs='?', default='csop', help='Path to the application')
        parser.add_argument('end_point', type=str, nargs='?', default='cases', help='Path to the folder containing test files')

        args = parser.parse_args()
        start_time_program = time.time()
        end_point = args.end_point
        application_name = args.application

        # Define paths for contract testing
        base_folder = os.path.join(project_root_path, "results", "contract_testing", application_name)
        output_folder = os.path.join(project_root_path, "reports_output", "contract_testing", application_name)

        # Control the number of parallel processes
        num_processes = int(os.getenv("NUM_PROCESSES", 2))

        # Process JSON files directly (not in parallel for debugging)
        process_folder(base_folder, output_folder, end_point)

        # Generate index HTML
        #generate_index_html(output_folder)
        logging.info("HTML Reports generation completed.")

        logging.info(f"Merging of result files completed for {end_point}.")

        end_time_program = time.time()
        elapsed_time_program = end_time_program - start_time_program
        logging.info(f"Elapsed Time for Program : {elapsed_time_program:.2f} seconds")
        logging.info("HTML Reports generation completed.")

    except Exception as e:
        # Log the exception traceback with script name and line number
        logging.error(f"Exception occurred in script {__file__} at line {traceback.extract_tb(sys.exc_info()[2])[-1][1]}: {str(e)}")
        sys.exit(1)
