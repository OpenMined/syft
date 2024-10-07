import os
import re
import signal
import subprocess
import time

RUNNING_SERVERS = {}


def find_and_run_script(task_path, extra_args):
    script_path = os.path.realpath(os.path.join(task_path, "run.sh"))  # Resolve symlink
    pid_file_path = os.path.join(task_path, "run.pid")
    env = os.environ.copy()  # Copy the current environment

    # Check if the script exists
    if os.path.isfile(script_path):
        # Set execution bit (+x)
        os.chmod(script_path, os.stat(script_path).st_mode | 0o111)

        # Check if the script has a shebang
        with open(script_path, "r") as script_file:
            first_line = script_file.readline().strip()
            has_shebang = first_line.startswith("#!")

        # Prepare the command based on whether there's a shebang or not
        command = (
            [script_path] + extra_args
            if has_shebang
            else ["/bin/bash", script_path] + extra_args
        )

        # Start the process and save the PID to the file
        with open(pid_file_path, "w") as pid_file:
            process = subprocess.Popen(
                command,
                cwd=task_path,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            pid_file.write(str(process.pid))  # Save the PID to the file
            print(f"✅ Server started with PID {process.pid}")
            return process

    else:
        raise FileNotFoundError(f"run.sh not found in {task_path}")


def kill_process_by_path(script_path):
    # Use `ps` to list all processes and their command lines
    try:
        result = subprocess.run(
            ["ps", "aux"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )

        for line in result.stdout.splitlines():
            if script_path in line:
                # Extract the PID from the `ps` output (2nd column)
                pid = int(line.split()[1])
                print(f"⚠️ Killing process {pid} running {script_path}")
                try:
                    os.kill(pid, signal.SIGTERM)
                except ProcessLookupError:
                    print(f"⚠️ No process with PID {pid} found, it might have exited.")
    except Exception as e:
        print(f"Error while killing process: {e}")


def is_server_running(script_path):
    # Use pgrep to find the server process based on the realpath of the script
    try:
        real_script_path = os.path.realpath(script_path)  # Resolve symlink
        result = subprocess.run(
            ["pgrep", "-f", real_script_path],  # -f matches the full command line
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if result.stdout.strip():
            print(f"✅ Server is running with PID {result.stdout.strip()}")
            return True
        return False
    except Exception as e:
        print(f"Error while checking server process: {e}")
        return False


def get_bore_remote_port(log_file):
    port_pattern = re.compile(r"remote_port=(\d+)")

    # Wait until the log file is created and has content
    while not os.path.exists(log_file):
        time.sleep(1)

    with open(log_file, "r") as f:
        for line in f:
            match = port_pattern.search(line)
            if match:
                return int(match.group(1))

    return None


def start_server(client_config, path):
    server_name = os.path.basename(path)
    script_path = os.path.realpath(os.path.join(path, "run.sh"))  # Resolve symlink

    extra_args = []

    try:
        # Check if the server is already running (using pgrep or similar)
        if is_server_running(script_path):
            print(f" - {server_name} is already running.")
            bore_log_path = os.path.realpath(os.path.join(path, "bore_output.log"))
            bore_port = get_bore_remote_port(bore_log_path)
            print("Got bore port", bore_port)
            return

        # Start the process
        print(f"⚙️ Starting {server_name} app", end="")
        process = find_and_run_script(path, extra_args)

        # Store the process in RUNNING_SERVERS if it starts successfully
        if process:
            RUNNING_SERVERS[server_name] = process
            print(f" - started with PID {process.pid}")

            bore_log_path = os.path.realpath(os.path.join(path, "bore_output.log"))
            bore_port = get_bore_remote_port(bore_log_path)
            print("Got bore port", bore_port)

    except Exception as e:
        print(f"Failed to run {server_name}. {e}")


def run_servers(client_config):
    # Create the directory
    apps_path = client_config.sync_folder + "/" + "servers"
    os.makedirs(apps_path, exist_ok=True)

    apps = os.listdir(apps_path)
    for app in apps:
        app_path = os.path.abspath(apps_path + "/" + app)
        if os.path.isdir(app_path):
            start_server(client_config, app_path)


def run(shared_state):
    client_config = shared_state.client_config
    run_servers(client_config)
