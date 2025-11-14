#!/bin/python3
# ====================================================================
# Filename: load_and_run_yml.py
# Author: Andreu Roca
# Created: 03/11/25
# ====================================================================
# Description: This script remotes via SSH into both raspberries and
#              launches the command defined in the config.yml file.
#
# Usage:      ./loader.py [run]
# ====================================================================

import os
import subprocess
import threading
import datetime
import sys

# Try to import yaml if available (optional)
try:
    import yaml
except ImportError:
    yaml = None
    import json

CONFIG_FILE = "config.yml"

# === CONFIG LOADING ===
def load_config(path):
    with open(path, "r") as f:
        data = f.read()

    if yaml:  # Use PyYAML if installed
        return yaml.safe_load(data)
    else:
        # fallback: basic JSON-compatible YAML
        print(data)
        return json.loads(data)

config = load_config(CONFIG_FILE)

REPO_LOCAL_DIR = os.path.abspath(config["repo_local_dir"])
LOCAL_RESULTS_DIR = os.path.abspath(config["local_results_dir"])
os.makedirs(LOCAL_RESULTS_DIR, exist_ok=True)
RASPBERRIES = config["raspberries"]
WSL = config["wsl"]

# === UTILS ===
def run_command(cmd, live_output=True, logfile=None):
    """Run a shell command, optionally showing live output and saving to logfile."""
    process = subprocess.Popen(
        cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )
    with (open(logfile, "w") if logfile else open(os.devnull, "w")) as log:
        for line in process.stdout:
            if live_output:
                print(line, end="")
            log.write(line)
        process.wait()
    return process.returncode

def sync_repo(pi):
    print(f"\n=== Syncing repo to {pi['name']} ({pi['host']}) ===")
    # first clean the existing repo in the raspberry
    ssh_cmd = "powershell.exe \"" if WSL else ""
    ssh_cmd += f"ssh {pi['host']} 'cd {pi['remote_dir']} && rm -rf src && rm -rf sample-files'"
    ssh_cmd = ssh_cmd + "\"" if WSL else ssh_cmd
    print(ssh_cmd)
    run_command(ssh_cmd)

    cmd = "powershell.exe \"" if WSL else ""
    cmd += "cp -r sample-files mtp_transfer/sample-files; "
    cmd += "cp -r src mtp_transfer/src; "
    cmd += f"scp -r {REPO_LOCAL_DIR}/mtp_transfer/* {pi['host']}:{pi['remote_dir']}/; "
    cmd += "rm -Force -Recurse mtp_transfer "
    cmd = cmd + "\"" if WSL else cmd
    print(cmd)
    return run_command(cmd)

def run_remote(pi):
    print(f"\n=== Running program on {pi['name']} ({pi['host']}) ===")
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    logfile = os.path.join(LOCAL_RESULTS_DIR, f"{pi['name']}_{timestamp}.log")
    ssh_cmd = "powershell.exe \"" if WSL else ""
    ssh_cmd += f"ssh {pi['host']} 'cd {pi['remote_dir']} && {pi['run_cmd']}'"
    ssh_cmd = ssh_cmd + "\"" if WSL else ssh_cmd
    return run_command(ssh_cmd, live_output=pi['show_output'], logfile=logfile)

def copy_results(pi):
    print(f"\n=== Copying results from {pi['name']} ({pi['host']}) ===")
    dest_dir = os.path.join(LOCAL_RESULTS_DIR, pi['name'])
    os.makedirs(dest_dir, exist_ok=True)
    cmd = "powershell.exe \"" if WSL else ""
    cmd += f"scp -r {pi['host']}:{pi['remote_dir']}/{pi['results_dir']}/* {dest_dir}/"
    cmd = cmd + "\"" if WSL else cmd
    print(cmd)
    return run_command(cmd)

# === MAIN WORKFLOW ===
def main():
    print("=== Starting deployment ===")

    for pi in RASPBERRIES:
        sync_repo(pi)

    if len(sys.argv) > 1 and sys.argv[1] == 'run':
        threads = []
        for pi in RASPBERRIES:
            t = threading.Thread(target=run_remote, args=(pi,), daemon=True)
            t.start()
            threads.append(t)

        for t in threads:
            t.join()

        for pi in RASPBERRIES:
            copy_results(pi)

        print("\n=== All done! Results collected in:", LOCAL_RESULTS_DIR, "===")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted by user. Exiting.")
        sys.exit(1)

