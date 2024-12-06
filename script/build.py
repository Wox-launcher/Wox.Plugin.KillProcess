import os
import pathlib
import subprocess
import shutil
import zipapp
import zipfile

# Define base paths
SCRIPT_DIR = pathlib.Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
DIST_DIR = PROJECT_ROOT / "dist"
SRC_DIR = PROJECT_ROOT / "src"
REQUIREMENTS_FILE = PROJECT_ROOT / "requirements.txt"

# Clean and create dist directory
shutil.rmtree(DIST_DIR, ignore_errors=True)
os.makedirs(DIST_DIR / "dependencies", exist_ok=True)

# Handle requirements.txt
if REQUIREMENTS_FILE.exists():
    REQUIREMENTS_FILE.unlink()

# Freeze and install dependencies
os.system(f"uv pip freeze > {REQUIREMENTS_FILE}")
os.system(f"uv pip install -r {REQUIREMENTS_FILE} --target {DIST_DIR}/dependencies")
REQUIREMENTS_FILE.unlink()

# Copy source files to dist
for file in SRC_DIR.iterdir():
    dest_path = DIST_DIR / file.name
    if file.is_dir() and not file.name.endswith('.egg-info'):
        shutil.copytree(file, dest_path)
    else:
        shutil.copy2(file, dest_path)

# Clean up metadata directories and unnecessary files
for root, dirs, files in os.walk(DIST_DIR / "dependencies"):
    root_path = pathlib.Path(root)
    # Clean up directories
    for dir_name in dirs[:]:  # Create a copy of the list to modify during iteration
        if dir_name.endswith(('.dist-info', '.egg-info')):
            shutil.rmtree(root_path / dir_name)
    
    # Clean up files
    for file_name in files:
        if file_name.startswith('__editable__') or file_name == '.lock':
            (root_path / file_name).unlink()

# Create the load_dependencies.py file
plugin_content = """
import os
import sys
import site

# Add dependencies directory to Python path
deps_dir = os.path.join(os.path.dirname(__file__), "dependencies")
if deps_dir not in sys.path:
    sys.path.insert(0, deps_dir)

# Import your actual plugin code
from main import plugin
"""

# Write the new entry point
with open(DIST_DIR / "__init__.py", "w") as f:
    f.write(plugin_content)