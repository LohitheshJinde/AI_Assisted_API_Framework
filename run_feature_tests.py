import os
import time
import subprocess
import argparse
from concurrent.futures import ThreadPoolExecutor

def run_behave_feature(feature_path):
    start_time = time.time()
    behave_executable = os.path.join(os.getcwd(), '.venv', 'Scripts', 'behave.exe')
    subprocess.run([behave_executable, feature_path, '--tags', '~@skip'])
    elapsed_time = time.time() - start_time
    return elapsed_time

def run_sequential(feature_files):
    elapsed_times = {}
    for feature_file in feature_files:
        elapsed_times[feature_file] = run_behave_feature(feature_file)
    return elapsed_times

def run_parallel(feature_files, max_parallel):
    elapsed_times = {}
    
    # Define a thread pool executor to control the number of parallel tasks
    with ThreadPoolExecutor(max_workers=max_parallel) as executor:
        # Submit tasks to the executor for each feature file
        future_to_feature = {executor.submit(run_behave_feature, feature_file): feature_file for feature_file in feature_files}
        
        # Process completed tasks as they finish
        for future in future_to_feature:
            feature_file = future_to_feature[future]
            try:
                elapsed_times[feature_file] = future.result()
            except Exception as e:
                print(f"Error running {feature_file}: {e}")

    return elapsed_times

if __name__ == '__main__':
    # Argument parser to accept feature file names and execution mode
    parser = argparse.ArgumentParser(description="Run Behave tests in parallel or sequential mode.")
    parser.add_argument('feature_files', nargs='*', default=['ui'], help="List of feature file names (without .feature extension)")
    parser.add_argument('--execution_mode', choices=['parallel', 'sequential'], default='sequential',
                        help="Execution mode: 'parallel' or 'sequential'")
    parser.add_argument('--max_parallel', type=int, default=2, help="Maximum number of parallel feature files to run")

    args = parser.parse_args()
    
    # Construct full paths to feature files by adding "features/" and ".feature"
    feature_files = [f"features_ui/{file_name}.feature" for file_name in args.feature_files]
    execution_mode = args.execution_mode
    max_parallel = args.max_parallel

    start_time = time.time()

    if execution_mode == 'sequential':
        print("Running in sequential mode...")
        elapsed_times = run_sequential(feature_files)
    else:
        print(f"Running in parallel mode with a maximum of {max_parallel} parallel tasks...")
        elapsed_times = run_parallel(feature_files, max_parallel)

    # Print elapsed times
    for feature_file, elapsed_time in elapsed_times.items():
        print(f"Elapsed Time for {feature_file}: {elapsed_time:.2f} seconds")

    # Total elapsed time
    total_elapsed_time = time.time() - start_time
    print("Total Elapsed Time:", total_elapsed_time)
