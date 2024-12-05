import os
import subprocess
import shutil
import zipapp

shutil.rmtree("dist", ignore_errors=True)
os.makedirs("dist/dependencies", exist_ok=True)
    
# remove requirements.txt, if exists
if os.path.exists("requirements.txt"):  
    os.remove("requirements.txt")
# freeze the dependencies
os.system("uv pip freeze > requirements.txt")

# install the dependencies
os.system("uv pip install -r requirements.txt --target dist/dependencies")

os.remove("requirements.txt")

# copy all files and directories in src directory to dist directory
for file in os.listdir("src"):
    src_path = os.path.join("src", file)
    dest_path = os.path.join("dist", file)
    if os.path.isdir(src_path) and not file.endswith('.egg-info'):
        shutil.copytree(src_path, dest_path)
    else:
        shutil.copy2(src_path, dest_path)

# Clean up metadata directories and unnecessary files
for root, dirs, files in os.walk("dist/dependencies"):
    # Clean up directories
    for dir_name in dirs:
        if dir_name.endswith(('.dist-info', '.egg-info')):
            shutil.rmtree(os.path.join(root, dir_name))
    
    # Clean up files
    for file_name in files:
        if file_name.startswith('__editable__') or file_name == '.lock':
            os.remove(os.path.join(root, file_name))


# create the load_dependencies.py file
with open("dist/load_dependencies.py", "w") as f:
    f.write("""
import os
import sys
import site

# Add dependencies directory to Python path
deps_dir = os.path.join(os.path.dirname(__file__), "dependencies")
if deps_dir not in sys.path:
    sys.path.insert(0, deps_dir)
""")

# Create the zipapp archive
zipapp.create_archive(
    "dist",  # Source directory
    "plugin.pyz",  # Output file
    compressed=True  # Enable compression
)


# remove the dist directory
shutil.rmtree("dist", ignore_errors=True)