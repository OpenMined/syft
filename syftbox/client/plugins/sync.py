import os
import traceback
from collections import defaultdict
from datetime import datetime
from threading import Event
from typing import Tuple

import requests
from watchdog.events import DirModifiedEvent

from syftbox.lib import (
    DirState,
    FileChange,
    FileChangeKind,
    FileInfo,
    PermissionTree,
    ResettableTimer,
    bintostr,
    get_datasites,
    hash_dir,
    strtobin,
)

CLIENT_CHANGELOG_FOLDER = "syft_changelog"
CLIENT_APPS = "apps"
STAGING = "staging"
IGNORE_FOLDERS = [CLIENT_CHANGELOG_FOLDER, STAGING, CLIENT_APPS]


def get_ignore_rules(dir_state: DirState) -> Tuple[str, str, str]:
    # get the ignore files
    syft_ignore_files = []
    folder_path = dir_state.sync_folder + "/" + dir_state.sub_path
    for afile, file_info in dir_state.tree.items():
        full_path = folder_path + "/" + afile
        sub_folder = os.path.dirname(full_path)

        if afile.endswith(".syftignore") and os.path.isfile(full_path):
            ignore_list = []
            with open(full_path) as f:
                ignore_list = f.readlines()
            for ignore_rule in ignore_list:
                ignore_rule = ignore_rule.strip()
                rule_prefix = sub_folder + "/" + ignore_rule
                syft_ignore_files.append((rule_prefix, sub_folder, afile))

    return syft_ignore_files


def filter_ignore_files(dir_state: DirState) -> DirState:
    # get the ignore files
    pruned_tree = dir_state.tree.copy()
    folder_path = dir_state.sync_folder + "/" + dir_state.sub_path
    syft_ignore_files = get_ignore_rules(dir_state)

    for rule_prefix, ignore_folder, ignore_file_path in syft_ignore_files:
        for afile, file_info in dir_state.tree.items():
            full_path = folder_path + "/" + afile
            if full_path.startswith(rule_prefix):
                # print("> File ignored by .syftignore", afile, ignore_rule)
                if afile in pruned_tree:
                    del pruned_tree[afile]

    now = datetime.now().timestamp()
    return DirState(
        tree=pruned_tree,
        timestamp=now,
        sync_folder=dir_state.sync_folder,
        sub_path=dir_state.sub_path,
    )


# Recursive function to add folder structure
def add_to_folder_tree(leaf, parts):
    if not parts:
        return
    part = parts[0]
    if part not in leaf:
        leaf[part] = defaultdict(dict)
    add_to_folder_tree(leaf[part], parts[1:])


# Function to remove empty folders, working from deepest to shallowest
def remove_empty_folders(leaf, current_path, root_dir):
    # List all keys and attempt to remove empty subfolders first
    for folder in list(leaf.keys()):
        folder_path = os.path.join(current_path, folder)

        # If the folder contains subfolders, recursively check them
        if isinstance(leaf[folder], dict):
            remove_empty_folders(leaf[folder], folder_path, root_dir)

            # Now that we've processed the subfolders, check if it's empty on the filesystem
            full_path = root_dir + "/" + folder_path
            if os.path.isdir(full_path) and not os.listdir(full_path):
                os.rmdir(full_path)  # Remove the empty folder from the file system
                del leaf[folder]  # Remove it from the folder tree as well
            else:
                pass


# write operations
def diff_dirstate(old, new):
    sync_folder = old.sync_folder
    old_sub_path = old.sub_path
    try:
        changes = []
        for afile, file_info in new.tree.items():
            kind = None
            if afile in old.tree.keys():
                old_file_info = old.tree[afile]
                if (
                    old_file_info.file_hash != file_info.file_hash
                    and file_info.last_modified >= old_file_info.last_modified
                ):
                    # update
                    kind = FileChangeKind.WRITE
                else:
                    pass
                    # print(
                    #     old_sub_path,
                    #     afile,
                    #     f"> 🔥 File hash eq=={old_file_info.file_hash == file_info.file_hash} "
                    #     f"or timestamp newer: {file_info.last_modified >= old_file_info.last_modified} "
                    #     f"dropping sync down {file_info}",
                    # )
            else:
                # create
                kind = FileChangeKind.CREATE

            if kind:
                change = FileChange(
                    kind=kind,
                    parent_path=old_sub_path,
                    sub_path=afile,
                    file_hash=file_info.file_hash,
                    last_modified=file_info.last_modified,
                    sync_folder=sync_folder,
                )
                changes.append(change)

        for afile, file_info in old.tree.items():
            if afile not in new.tree.keys():
                # delete
                now = datetime.now().timestamp()
                # TODO we need to overhaul this to prevent these kinds of edge cases
                SECS_SINCE_CHANGE = 5
                if now >= (file_info.last_modified + SECS_SINCE_CHANGE):
                    kind = FileChangeKind.DELETE
                    change = FileChange(
                        kind=kind,
                        parent_path=old.sub_path,
                        sub_path=afile,
                        file_hash=file_info.file_hash,
                        last_modified=file_info.last_modified,
                        sync_folder=sync_folder,
                    )
                    changes.append(change)
                else:
                    print(
                        f"🔥 Skipping delete {file_info}. File change is < 3 seconds ago"
                    )
        return changes
    except Exception as e:
        print("Error in diff_dirstate", str(e))
        raise e


def prune_invalid_changes(new, valid_changes) -> DirState:
    new_tree = {}
    for file, file_info in new.tree.items():
        internal_path = new.sub_path + "/" + file
        if internal_path in valid_changes:
            new_tree[file] = file_info

    return DirState(
        tree=new_tree,
        timestamp=new.timestamp,
        sync_folder=new.sync_folder,
        sub_path=new.sub_path,
    )


def delete_files(new, deleted_files) -> DirState:
    new_tree = {}
    for file, file_info in new.tree.items():
        internal_path = new.sub_path + "/" + file
        if internal_path not in deleted_files:
            new_tree[file] = file_info

    return DirState(
        tree=new_tree,
        timestamp=new.timestamp,
        sync_folder=new.sync_folder,
        sub_path=new.sub_path,
    )


stop_event = Event()


stop_event = Event()

PLUGIN_NAME = "sync"


def filter_changes(
    user_email: str,
    changes: list[FileChange],
    perm_tree: PermissionTree,
):
    valid_changes = []
    valid_change_files = []
    invalid_changes = []
    for change in changes:
        if change.kind in [
            FileChangeKind.WRITE,
            FileChangeKind.CREATE,
            FileChangeKind.DELETE,
        ]:
            perm_file_at_path = perm_tree.permission_for_path(change.full_path)
            if (
                user_email in perm_file_at_path.write
                or "GLOBAL" in perm_file_at_path.write
            ) or user_email in perm_file_at_path.admin:
                valid_changes.append(change)
                valid_change_files.append(change.sub_path)
                continue
            # # todo we need to handle this properly
            # if perm_file_at_path.admin == [user_email]:
            #     if change.internal_path.endswith("_.syftperm"):
            #         # include changes for syft_perm file even if only we have read perms.
            #         valid_changes.append(change)
            #         valid_change_files.append(change.sub_path)
            #         continue

        invalid_changes.append(change)
    return valid_changes, valid_change_files, invalid_changes


def push_changes(client_config, changes):
    written_changes = []
    for change in changes:
        try:
            data = {
                "email": client_config.email,
                "change": change.to_dict(),
            }
            if change.kind_write:
                if os.path.isdir(change.full_path):
                    # Handle directory
                    data["is_directory"] = True
                else:
                    # Handle file
                    data["data"] = bintostr(change.read())
            elif change.kind_delete:
                # no data for delete operations
                pass

            response = requests.post(
                f"{client_config.server_url}/write",
                json=data,
            )
            write_response = response.json()
            change_result = write_response["change"]
            change_result["kind"] = FileChangeKind(change_result["kind"])
            ok_change = FileChange(**change_result)
            if response.status_code == 200:
                if "accepted" in write_response and write_response["accepted"]:
                    written_changes.append(ok_change)
                else:
                    print("> 🔥 Rejected change", ok_change)
            else:
                print(
                    f"> {client_config.email} FAILED /write {change.kind} {change.internal_path}",
                )
        except Exception as e:
            print(
                f"Failed to call /write on the server for {change.internal_path}",
                str(e),
            )
    return written_changes


def pull_changes(client_config, changes):
    remote_changes = []
    for change in changes:
        try:
            data = {
                "email": client_config.email,
                "change": change.to_dict(),
            }
            response = requests.post(
                f"{client_config.server_url}/read",
                json=data,
            )
            read_response = response.json()
            change_result = read_response["change"]
            change_result["kind"] = FileChangeKind(change_result["kind"])
            ok_change = FileChange(**change_result)

            if ok_change.kind_write:
                if read_response.get("is_directory", False):
                    data = None
                else:
                    data = strtobin(read_response["data"])
            elif change.kind_delete:
                data = None

            if response.status_code == 200:
                remote_changes.append((ok_change, data))
            else:
                print(
                    f"> {client_config.email} FAILED /read {change.kind} {change.internal_path}",
                )
        except Exception as e:
            print("Failed to call /read on the server", str(e))
    return remote_changes


def list_datasites(client_config):
    datasites = []
    try:
        response = requests.get(
            f"{client_config.server_url}/list_datasites",
        )
        read_response = response.json()
        remote_datasites = read_response["datasites"]

        if response.status_code == 200:
            datasites = remote_datasites
        else:
            print(f"> {client_config.email} FAILED /list_datasites")
    except Exception as e:
        print("Failed to call /list_datasites on the server", str(e))
    return datasites


def get_remote_state(client_config, sub_path: str):
    try:
        data = {
            "email": client_config.email,
            "sub_path": sub_path,
        }

        response = requests.post(
            f"{client_config.server_url}/dir_state",
            json=data,
        )
        state_response = response.json()
        if response.status_code == 200:
            dir_state = DirState(**state_response["dir_state"])
            fix_tree = {}
            for key, value in dir_state.tree.items():
                fix_tree[key] = FileInfo(**value)
            dir_state.tree = fix_tree
            return dir_state
        print(f"> {client_config.email} FAILED /dir_state: {sub_path}")
        return None
    except Exception as e:
        print("Failed to call /dir_state on the server", str(e))


def create_datasites(client_config):
    datasites = list_datasites(client_config)
    for datasite in datasites:
        # get the top level perm file
        os.makedirs(os.path.join(client_config.sync_folder, datasite), exist_ok=True)


def ascii_for_change(changes) -> str:
    count = 0
    change_text = ""
    for change in changes:
        count += 1
        pipe = "├──"
        if count == len(changes):
            pipe = "└──"
        change_text += pipe + change + "\n"
    return change_text


def handle_empty_folders(client_config, datasite):
    changes = []
    datasite_path = os.path.join(client_config.sync_folder, datasite)

    for root, dirs, files in os.walk(datasite_path):
        if not files and not dirs:
            # This is an empty folder
            relative_path = os.path.relpath(root, datasite_path)
            if relative_path == ".":
                continue  # Skip the root folder

            change = FileChange(
                kind=FileChangeKind.CREATE,
                parent_path=datasite,
                sub_path=relative_path,
                file_hash="",  # Empty folders don't have a hash
                last_modified=os.path.getmtime(root),
                sync_folder=client_config.sync_folder,
            )
            changes.append(change)

    return changes


def filter_changes_ignore(pre_filter_changes, syft_ignore_files):
    filtered_changes = []
    for change in pre_filter_changes:
        keep = True
        for syft_ignore in syft_ignore_files:
            if change.full_path.startswith(syft_ignore[0]):
                keep = False
                break
        if keep:
            filtered_changes.append(change)

    return filtered_changes


def sync_up(client_config):
    # create a folder to store the change log
    change_log_folder = f"{client_config.sync_folder}/{CLIENT_CHANGELOG_FOLDER}"
    os.makedirs(change_log_folder, exist_ok=True)

    # get all the datasites
    datasites = get_datasites(client_config.sync_folder)

    n_changes = 0

    for datasite in datasites:
        # get the top level perm file
        datasite_path = os.path.join(client_config.sync_folder, datasite)

        perm_tree = PermissionTree.from_path(datasite_path)

        dir_filename = f"{change_log_folder}/{datasite}.json"

        # get the old dir state
        old_dir_state = None
        try:
            # it might not exist yet
            old_dir_state = DirState.load(dir_filename)
            fix_tree = {}
            for key, value in old_dir_state.tree.items():
                fix_tree[key] = FileInfo(**value)
            old_dir_state.tree = fix_tree
        except Exception:
            pass

        if old_dir_state is None:
            old_dir_state = DirState(
                tree={},
                timestamp=0,
                sync_folder=client_config.sync_folder,
                sub_path=datasite,
            )

        # get the new dir state
        unfiltered_new_dir_state = hash_dir(
            client_config.sync_folder, datasite, IGNORE_FOLDERS
        )

        # ignore files
        syft_ignore_files = get_ignore_rules(unfiltered_new_dir_state)
        new_dir_state = filter_ignore_files(unfiltered_new_dir_state)

        pre_filter_changes = diff_dirstate(old_dir_state, new_dir_state)

        # Add handling for empty folders
        empty_folder_changes = handle_empty_folders(client_config, datasite)
        pre_filter_changes.extend(empty_folder_changes)

        changes = filter_changes_ignore(pre_filter_changes, syft_ignore_files)

        if len(changes) == 0:
            continue

        val, val_files, inval = filter_changes(client_config.email, changes, perm_tree)

        # send val changes
        results = push_changes(client_config, val)

        deleted_files = []
        changed_files = []
        for result in results:
            if result.kind_write:
                changed_files.append(result.internal_path)
            elif result.kind_delete:
                deleted_files.append(result.internal_path)

        synced_dir_state = prune_invalid_changes(new_dir_state, changed_files)

        # combine successful changes qwith old dir state
        combined_tree = old_dir_state.tree

        # add new successful changes
        combined_tree.update(synced_dir_state.tree)
        synced_dir_state.tree = combined_tree

        synced_dir_state = delete_files(synced_dir_state, deleted_files)

        change_text = ""
        if len(changed_files):
            change_text += f"🔼 Syncing Up {len(changed_files)} Changes\n"
            change_text += ascii_for_change(changed_files)

        if len(deleted_files):
            change_text += f"❌ Syncing Up {len(deleted_files)} Deletes\n"
            change_text += ascii_for_change(deleted_files)

        synced_dir_state.save(dir_filename)
        n_changes += len(changed_files) + len(deleted_files)

    return n_changes


def sync_down(client_config) -> int:
    # create a folder to store the change log
    change_log_folder = f"{client_config.sync_folder}/{CLIENT_CHANGELOG_FOLDER}"
    os.makedirs(change_log_folder, exist_ok=True)

    n_changes = 0

    # get all the datasites
    datasites = get_datasites(client_config.sync_folder)
    for datasite in datasites:
        # get the top level perm file

        dir_filename = f"{change_log_folder}/{datasite}.json"

        # datasite_path = os.path.join(client_config.sync_folder, datasite)

        # perm_tree = PermissionTree.from_path(datasite_path)

        # get the new dir state

        unfiltered_new_dir_state = hash_dir(
            client_config.sync_folder, datasite, IGNORE_FOLDERS
        )
        syft_ignore_files = get_ignore_rules(unfiltered_new_dir_state)

        # ignore files
        new_dir_state = filter_ignore_files(unfiltered_new_dir_state)

        remote_dir_state = get_remote_state(client_config, datasite)
        if not remote_dir_state:
            # print(f"No remote state for dir: {datasite}")
            continue

        pre_filter_changes = diff_dirstate(new_dir_state, remote_dir_state)

        # Add handling for empty folders
        empty_folder_changes = handle_empty_folders(client_config, datasite)
        pre_filter_changes.extend(empty_folder_changes)

        changes = filter_changes_ignore(pre_filter_changes, syft_ignore_files)

        if len(changes) == 0:
            continue

        # fetch writes from the /read endpoint
        fetch_files = []
        for change in changes:
            if change.kind_write:
                fetch_files.append(change)

        results = pull_changes(client_config, fetch_files)

        # make writes
        changed_files = []
        for change, data in results:
            change.sync_folder = client_config.sync_folder
            if change.kind_write:
                if data is None:  # This is an empty directory
                    os.makedirs(change.full_path, exist_ok=True)
                    changed_files.append(change.internal_path)
                else:
                    result = change.write(data)
                    if result:
                        changed_files.append(change.internal_path)

        # delete local files dont need the server
        deleted_files = []
        for change in changes:
            change.sync_folder = client_config.sync_folder
            if change.kind_delete:
                # perm_file_at_path = perm_tree.permission_for_path(change.sub_path)
                # if client_config.email in perm_file_at_path.admin:
                #     continue
                result = change.delete()
                if result:
                    deleted_files.append(change.internal_path)

        # remove empty folders
        folder_tree = defaultdict(dict)
        # Process each file and build the folder structure
        for item in deleted_files:
            folders = os.path.dirname(item).split("/")
            add_to_folder_tree(folder_tree, folders)

        # Remove empty folders, starting from the root directory
        remove_empty_folders(folder_tree, "/", root_dir=client_config.sync_folder)

        synced_dir_state = prune_invalid_changes(new_dir_state, changed_files)

        # combine successfulc hanges qwith old dir state
        # we use unfiltered so they keep being ignored but we could change these to another list?
        combined_tree = unfiltered_new_dir_state.tree
        combined_tree.update(synced_dir_state.tree)
        synced_dir_state.tree = combined_tree

        synced_dir_state = delete_files(synced_dir_state, deleted_files)

        change_text = ""
        if len(changed_files):
            change_text += f"⏬ Syncing Down {len(changed_files)} Changes\n"
            change_text += ascii_for_change(changed_files)
        if len(deleted_files):
            change_text += f"❌ Syncing Down {len(deleted_files)} Deletes\n"
            change_text += ascii_for_change(deleted_files)

        if len(change_text) > 0:
            print(change_text)

        synced_dir_state.save(dir_filename)
        n_changes += len(changed_files) + len(deleted_files)

    return n_changes


SYNC_UP_ENABLED = True
SYNC_DOWN_ENABLED = True


def do_sync(shared_state):
    event_length = len(shared_state.fs_events)
    shared_state.fs_events = []
    try:
        if not stop_event.is_set():
            num_changes = 0
            if shared_state.client_config.token:
                try:
                    create_datasites(shared_state.client_config)
                except Exception as e:
                    traceback.print_exc()
                    print("failed to get_datasites", e)

                try:
                    if SYNC_UP_ENABLED:
                        num_changes += sync_up(shared_state.client_config)
                    else:
                        print("❌ Sync Up Disabled")
                except Exception as e:
                    traceback.print_exc()
                    print("failed to sync up", e)

                try:
                    if SYNC_DOWN_ENABLED:
                        num_changes += sync_down(shared_state.client_config)
                    else:
                        print("❌ Sync Down Disabled")
                except Exception as e:
                    traceback.print_exc()
                    print("failed to sync down", e)
            if num_changes == 0:
                if event_length:
                    print(f"✅ Synced {event_length} File Events")
                else:
                    print("✅ Synced due to Timer")
    except Exception as e:
        print("Failed to run plugin", e)


FLUSH_SYNC_TIMEOUT = 0.5
DEFAULT_SCHEDULE = 10000


def run(shared_state, *args, **kwargs):
    if len(args) == 1:
        event = args[0]
        # ignore certain files / folders
        if hasattr(event, "src_path"):
            if CLIENT_CHANGELOG_FOLDER in event.src_path:
                return

        # ignore these events for now on linux
        # FileOpenedEvent
        # FileClosedNoWriteEvent
        # DirModifiedEvent
        if event.event_type in ["opened", "closed_no_write"]:
            return

        if isinstance(event, DirModifiedEvent):
            return

        shared_state.fs_events.append(event)

    if "sync" not in shared_state.timers:
        shared_state.timers["sync"] = ResettableTimer(
            timeout=FLUSH_SYNC_TIMEOUT,
            callback=do_sync,
        )

    shared_state.timers["sync"].start(shared_state=shared_state)
