from pathlib import Path

from rich.console import Console
from rich.tree import Tree


def display_file_tree(root_dir: Path):
    def add_dir(tree: Tree, path: Path):
        for child in path.iterdir():
            if child.is_dir():
                sub_tree = tree.add(f"📁 {child.name}")
                add_dir(sub_tree, child)
            elif child.name == "_.syftperm":
                tree.add(f"🛡️ {child.name}")
            else:
                tree.add(f"📄 {child.name}")

    console = Console()
    file_tree = Tree(f"📁 {root_dir.name}")
    add_dir(file_tree, root_dir)

    console.print(file_tree)
