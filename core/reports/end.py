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
project_root_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(project_root_path)

from utils import utils
from utils import gitlab_utils

# Load environment variables
if not os.getenv('CI_PIPELINE'):
    logging.info("Local environment detected. Loading variables from .env file...")
    load_dotenv(dotenv_path=".env", verbose=True, override=True)
else:
    logging.info("CI/CD environment detected. Using CI/CD provided variables...")

environment = os.getenv("ENVIRONMENT", "unknown")
logging.info(f"Using environment: {environment}")

# Set up logging
current_dir = os.path.dirname(os.path.abspath(__file__))
current_date = utils.current_date
param_key = "endpoint_method_gen_report.log"
log_file_path = utils.configure_logging_api(param_key, current_date, current_dir)
logging.info(f"Logging configured. Log file: {log_file_path}")

def generate_html_report(json_file, output_folder):
    """
    Generate an HTML test report with visual charts from a structured JSON file.
    This function reads a JSON file containing test execution results and:
    - Loads test metadata and results into a DataFrame
    - Generates various charts (status summary, response time, trends, pass rate)
    - Populates a predefined HTML template with data and chart references
    - Saves the final HTML report to the specified output folder

    Args:
        json_file (str): Path to the input JSON file containing test data.
        output_folder (str): Directory where the HTML report and charts will be saved.
    """
    logging.info(f"Generating HTML report from: {json_file}")
    try:
        with open(json_file, 'r') as file:
            json_data = json.load(file)
        logging.info(f"Successfully loaded JSON data from {json_file}")
    except FileNotFoundError:
        logging.error(f"Report input file not found: {json_file}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        logging.error(f"Error decoding JSON: {e}")
        sys.exit(1)

    tests = json_data.get("tests", [])
    logging.info(f"Total test cases found: {len(tests)}")
    
    df = pd.DataFrame(tests)
    generate_status_summary_chart(df, os.path.join(output_folder, "test_case_status_summary.png"))
    generate_response_time_chart(df, os.path.join(output_folder, "response_time_comparison.png"))
    generate_status_over_time_chart(df, os.path.join(output_folder, "test_case_status_over_time.png"))
    generate_pass_rate_chart(df, os.path.join(output_folder, "pass_rate_chart.png"))

    template_file_path = os.path.join(project_root_path, "reports", "endpoint_method_template.html")
    try:
        with open(template_file_path, 'r') as file:
            html_template = file.read()
        logging.info("HTML template loaded successfully!")
    except FileNotFoundError:
        logging.error(f"HTML template not found: {template_file_path}")
        sys.exit(1)

    html_report = html_template.replace("{{ testSuite }}", json_data["info"].get("testSuite", "N/A"))
    html_report = html_report.replace("{{ pass_rate_chart }}", f"{output_folder}/pass_rate_chart.png")
    output_file = os.path.join(output_folder, os.path.basename(json_file).replace(".json", ".html"))
    with open(output_file, "w") as file:
        file.write(html_report)
    logging.info(f"HTML report generated: {output_file}")

def generate_status_summary_chart(df, output_file):
    """
    Generate a bar chart summarizing the status of test cases.

    This function creates a bar chart showing the number of passed and failed test cases
    based on the 'status' column in the provided DataFrame. The chart is saved to the specified file.

    Args:
        df (pd.DataFrame): DataFrame containing test case data with a 'status' column.
        output_file (str): Path where the generated chart image (PNG) will be saved.
    """
    logging.info("Generating test case status summary chart...")
    df["status"].value_counts().plot(kind="bar", color=["green", "red"])
    plt.title("Test Case Status Summary")
    plt.xlabel("Status")
    plt.ylabel("Count")
    plt.savefig(output_file)
    plt.close()
    logging.info(f"Status summary chart saved: {output_file}")

def generate_response_time_chart(df, output_file):
    """
    Generate a boxplot comparing response times for passed and failed test cases.
    This function creates a boxplot using seaborn to visualize the distribution of
    response times grouped by test case status (passed/failed). Each box represents 
    the response time spread for that status. The chart is saved as a PNG file.

    Args:
        df (pd.DataFrame): DataFrame containing test case data with 'status' and 'responseTime' columns.
        output_file (str): Path to save the generated chart image.
    """
    logging.info("Generating response time comparison chart...")
    plt.figure(figsize=(10, 6))
    sns.boxplot(data=df, x="status", y="responseTime", hue="status",
                palette={"passed": "green", "failed": "red"}, dodge=False)
    plt.title("Response Time Comparison")
    plt.xlabel("Status")
    plt.ylabel("Response Time (ms)")
    plt.savefig(output_file)
    plt.close()
    logging.info(f"Response time chart saved: {output_file}")

def generate_status_over_time_chart(df, output_file):
    """
    Generate a line chart showing test case status counts over time.
    
    This function creates a time series line chart that displays how many test 
    cases passed or failed on each date, based on the 'startDate' and 'status' 
    columns in the input DataFrame. Dates are parsed and aggregated, and the 
    chart is saved as a PNG file.

    Args:
        df (pd.DataFrame): DataFrame containing test case data with 'startDate' and 'status' columns.
        output_file (str): Path to save the generated chart image.

    Notes:
        - Invalid or missing startDate values are automatically coerced to NaT and excluded.
        - Uses color mapping to differentiate status lines.
    """
    logging.info("Generating test case status over time chart...")
    df["startDate"] = pd.to_datetime(df["startDate"], errors='coerce')
    status_counts_over_time = df.groupby([df["startDate"].dt.date, "status"]).size().unstack(fill_value=0)
    status_counts_over_time.plot(kind="line", marker="o", colormap="coolwarm")
    plt.title("Test Case Status Over Time")
    plt.xlabel("Date")
    plt.ylabel("Count")
    plt.legend(title="Status")
    plt.savefig(output_file)
    plt.close()
    logging.info(f"Status over time chart saved: {output_file}")

def generate_pass_rate_chart(df, output_file):
    """
    Generate a pie chart representing the pass rate percentage of test cases.

    This function calculates the proportion of passed and failed test cases 
    based on the 'status' column in the input DataFrame and visualizes them 
    in a pie chart. The chart shows percentage distribution and is saved 
    to the specified output file path.

    Args:
        df (pd.DataFrame): DataFrame containing test results with a 'status' column.
        output_file (str): File path to save the resulting pie chart (e.g., 'pass_rate_chart.png').

    Notes:
        - If there are no passed or failed test cases, the chart will show 100% failed.
        - Uses green for passed and red for failed sections.
        - Ensures the pie chart is circular using `plt.axis("equal")`.
    """
    logging.info("Generating pass rate percentage chart...")
    status_counts = df["status"].value_counts()
    pass_count = status_counts.get("passed", 0)
    fail_count = status_counts.get("failed", 0)
    total = pass_count + fail_count
    pass_rate = (pass_count / total) * 100 if total > 0 else 0
    fail_rate = 100 - pass_rate

    labels = ["Passed", "Failed"]
    sizes = [pass_rate, fail_rate]
    colors = ["green", "red"]

    plt.figure(figsize=(8, 8))
    plt.pie(sizes, labels=labels, autopct="%.2f%%", startangle=90, colors=colors)
    plt.title("Pass Rate Percentage")
    plt.axis("equal")
    plt.savefig(output_file)
    plt.close()
    logging.info(f"Pass rate percentage chart saved: {output_file}")

def main():
    """
    Entry point for the test report generation process.

    This function initializes the test report generation workflow by:
    - Defining the input JSON file containing test results.
    - Creating the output directory (if it does not exist).
    - Calling the report generation function to produce visual and HTML reports.

    Assumes:
        - The file 'test_results.json' is available in the working directory.
        - The folder 'reports' is used to store all generated output files.
    """
    logging.info("Starting test report generation...")
    json_file = "test_results.json"  # Example JSON file
    output_folder = "reports"  # Example output folder
    os.makedirs(output_folder, exist_ok=True)
    generate_html_report(json_file, output_folder)
    logging.info("Report generation completed successfully!")

if __name__ == "__main__":
    main()
