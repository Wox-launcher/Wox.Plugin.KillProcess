import os
import pathlib
import shutil
import zipfile

SCRIPT_DIR = pathlib.Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
DIST_DIR = PROJECT_ROOT / "dist"

with zipfile.ZipFile(PROJECT_ROOT / 'wox.plugin.killprocess.wox', 'w') as zip:
    # Write plugin.json
    zip.write('plugin.json')
    
    # Write all files in image directory recursively
    for file in (PROJECT_ROOT / 'image').rglob('*'):
        if file.is_file():
            relative_path = file.relative_to(PROJECT_ROOT)
            zip.write(file, str(relative_path))
    
    # Write all files in dist directory recursively  
    for file in DIST_DIR.rglob('*'):
        if file.is_file():
            relative_path = file.relative_to(DIST_DIR)
            zip.write(file, str(relative_path))


# Remove dist directory
shutil.rmtree(DIST_DIR, ignore_errors=True)