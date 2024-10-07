#!/bin/sh

set -e

# Function to check if a command is available
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Check for Git dependency
if ! command_exists git; then
    echo "Error: Git is not installed or not in your PATH."
    echo "Git is required to clone repositories."
    echo "To install Git:"
    echo "  - On many Linux distributions: Use your package manager (e.g., apt, yum, dnf)"
    echo "  - On macOS: Install Xcode Command Line Tools or use Homebrew"
    echo "Please install Git and run this script again."
    exit 1
fi

# Check if the CSV file exists
if [ ! -f "github_apps.csv" ]; then
    echo "Error: github_apps.csv file not found"
    echo "Please make sure the CSV file is in the same directory as this script."
    exit 1
fi

LAST_UPDATE_FILE=".last_updates"

# Function to get the last update time for a repository
get_last_update() {
    repo_name="$1"
    if [ -f "$LAST_UPDATE_FILE" ]; then
        grep "^$repo_name," "$LAST_UPDATE_FILE" | cut -d',' -f2
    fi
}

# Function to set the last update time for a repository
set_last_update() {
    repo_name="$1"
    current_time=$(date +%s)
    if [ -f "$LAST_UPDATE_FILE" ]; then
        sed -i.bak "/^$repo_name,/d" "$LAST_UPDATE_FILE"
    fi
    echo "$repo_name,$current_time" >> "$LAST_UPDATE_FILE"
}

# Function to check if it's time to update a repository
should_update() {
    repo_name="$1"
    update_frequency="$2"
    last_update=$(get_last_update "$repo_name")

    # If there's no last update time, it's time to update
    if [ -z "$last_update" ]; then
        return 0
    fi

    current_time=$(date +%s)
    time_since_last_update=$((current_time - last_update))

    # Check if enough time has passed since the last update
    [ "$time_since_last_update" -ge "$update_frequency" ]
}

# Read the CSV file line by line
while IFS=',' read -r repo_url update_frequency update_type || [ -n "$repo_url" ]; do
    # Remove any leading/trailing whitespace
    repo_url=$(echo "$repo_url" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')
    update_frequency=$(echo "$update_frequency" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')
    update_type=$(echo "$update_type" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')

    # Skip empty lines
    if [ -z "$repo_url" ]; then
        continue
    fi

    # Extract the repository name from the URL
    repo_name=$(echo "$repo_url" | sed -e 's/.*\///' -e 's/\.git$//')
    repo_path="../$repo_name"

    # Check if it's time to update this repository
    if ! should_update "$repo_name" "$update_frequency"; then
        echo "Skipping $repo_name, not time to update yet"
        continue
    fi

    echo "Processing repository: $repo_name"
    echo "Local path: $repo_path"
    echo "Update frequency: every $update_frequency seconds"
    echo "Update type: $update_type"

    # Check if the repository already exists
    if [ -d "$repo_path" ]; then
        if [ "$update_type" = "REPLACE" ]; then
            echo "Removing existing repository at $repo_path"
            rm -rf "$repo_path"
            # Clone the repository
            echo "Cloning $repo_url to $repo_path"
            if git clone "$repo_url" "$repo_path"; then
                echo "Successfully cloned $repo_name"
            else
                echo "Failed to clone $repo_name"
            fi
        elif [ "$update_type" = "GIT PULL" ]; then
            echo "Updating existing repository at $repo_path"
            cd "$repo_path"
            # Commit any changes before pulling
            if [ -n "$(git status --porcelain)" ]; then
                echo "Changes detected, committing before pull"
                git add .
                git commit -m "Auto-commit before pull"
            else
                echo "No changes to commit"
            fi
            # Now perform the pull
            if git pull; then
                echo "Successfully updated $repo_name"
            else
                echo "Failed to update $repo_name"
            fi
            cd - > /dev/null
        else
            echo "Invalid update type for $repo_name: $update_type"
        fi
    else
        # Clone the repository
        echo "Cloning $repo_url to $repo_path"
        if git clone "$repo_url" "$repo_path"; then
            echo "Successfully cloned $repo_name"
        else
            echo "Failed to clone $repo_name"
        fi
    fi

    # Update the last update time for this repository
    set_last_update "$repo_name"

    echo "-----------------------------------"
done < "github_apps.csv"

echo "Process completed"
