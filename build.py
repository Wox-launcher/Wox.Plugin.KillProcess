import os
import shutil
import subprocess
import sys
from pathlib import Path

def run_cmd(cmd, cwd=None):
    print(f"Running: {' '.join(cmd)}")
    # shell=False is safer and usually correct for list args, unless using built-ins (not uv)
    # On Windows, shell=True is sometimes needed to find executables if not in direct path, 
    # but 'uv' should be in path. We will try shell=True for Windows compatibility with 'uv' command if list fails?
    # Actually, shutil.which can help.
    
    # Force shell=True on Windows for command resolution if needed, but 'uv' is an exe.
    use_shell = (os.name == 'nt')
    
    try:
        result = subprocess.run(
            cmd, 
            cwd=cwd, 
            capture_output=True, 
            text=True, 
            shell=use_shell
        )
        if result.returncode != 0:
            print("STDOUT:", result.stdout)
            print("STDERR:", result.stderr)
            raise subprocess.CalledProcessError(result.returncode, cmd)
        print(result.stdout)
    except Exception as e:
        print(f"Error running command: {e}")
        raise

def merge_directories(src, dst):
    """Recursively merge src into dst."""
    src = Path(src)
    dst = Path(dst)
    
    for item in src.rglob("*"):
        if item.is_dir():
            continue
            
        rel_path = item.relative_to(src)
        target_path = dst / rel_path
        
        target_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Copy file. careful not to overwrite if we want to preserve semantics?
        # Binaries usually have distinct names (_psutil_windows.pyd vs _psutil_linux.so)
        # Shared python files (e.g. __init__.py) are identical or compatible.
        shutil.copy2(item, target_path)

def main():
    root = Path.cwd()
    dist = root / "dist"
    
    # 1. Clean dist
    if dist.exists():
        print(f"Cleaning {dist}")
        shutil.rmtree(dist)
    dist.mkdir()
    
    deps_root = dist / "dependencies"
    deps_root.mkdir()
    
    # 2. Install Dependencies for multiple platforms
    platforms = [
        ("temp_win", "windows"),
        ("temp_mac", "macos"),
        ("temp_linux", "linux"),
    ]
    
    for temp_name, platform_tag in platforms:
        print(f"\n--- Building dependencies for {platform_tag} ---")
        temp_dir = dist / temp_name
        temp_dir.mkdir()
        
        # Install from pyproject.toml (current directory)
        cmd = [
            "uv", "pip", "install", ".",
            "--target", str(temp_dir),
            "--python-platform", platform_tag
        ]
        
        run_cmd(cmd, cwd=root)
            
        # Merge into final dependencies
        merge_directories(temp_dir, deps_root)
        
        # Cleanup temp
        shutil.rmtree(temp_dir)

    # 3. Clean up the self-package (killprocess) from dependencies
    if (deps_root / "killprocess").exists():
        shutil.rmtree(deps_root / "killprocess")
    
    # Remove all dist-info/egg-info to keep it clean? 
    # Or keep them? Usually good to keep for version info, 
    # but we have mixed platforms. Keeping them might be confusing but harmless?
    # The user might want a clean folder. Let's clean the root ones.
    # Note: If we have multiple versions/platforms, dist-info might conflict if names identical.
    # uv creates .dist-info based on version.
    # Let's clean them to save space and avoid conflicts, 
    # unless plugin loader needs them (usually doesn't).
    for item in deps_root.rglob("*.dist-info"):
        shutil.rmtree(item)
    for item in deps_root.rglob("*.egg-info"):
        shutil.rmtree(item)
    for item in deps_root.rglob("__pycache__"):
        shutil.rmtree(item)
    bin_dir = deps_root / "bin"
    if bin_dir.exists():
        shutil.rmtree(bin_dir)

    # 4. Copy Source Code
    print("\n--- Copying Source Code ---")
    dest_plugin = dist / "killprocess"
    dest_plugin.mkdir(parents=True)
    
    # Copy src contents to dist/killprocess
    src_plugin = root / "src"
    for item in src_plugin.rglob("*"):
        if item.is_dir():
            continue
        rel = item.relative_to(src_plugin)
        dst = dest_plugin / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, dst)

    # 5. Create __init__.py shim
    print("\n--- Creating Entry Point ---")
    shim_path = dist / "__init__.py"
    with open(shim_path, "w", encoding="utf-8") as f:
        f.write('import os\nimport sys\n\n# Add dependencies directory to Python path\ndeps_dir = os.path.join(os.path.dirname(__file__), "dependencies")\nif deps_dir not in sys.path:\n    sys.path.insert(0, deps_dir)\n\n# Import your actual plugin code\nfrom .killprocess.main import plugin\n\n__all__ = ["plugin"]\n')

    # 6. Copy Manifest and Assets
    shutil.copy2(root / "plugin.json", dist / "plugin.json")
    
    img_dest = dist / "image"
    img_dest.mkdir()
    for img in (root / "image").iterdir():
        shutil.copy2(img, img_dest / img.name)
        
    print(f"\nBuild Complete. Artifacts in '{dist}'")
    
    # 7. Publish (Zip) if requested
    if "--publish" in sys.argv:
        print("\n--- Publishing ---")
        package_name = "wox.plugin.killprocess.wox"
        zip_path = root / package_name
        if zip_path.exists():
            zip_path.unlink()
            
        print(f"Creating {package_name}...")
        shutil.make_archive(str(root / "wox.plugin.killprocess"), 'zip', dist)
        
        # shutil.make_archive adds .zip extension automatically
        final_zip = root / "wox.plugin.killprocess.zip"
        if final_zip.exists():
             shutil.move(str(final_zip), str(zip_path))
             
        print(f"Package created: {zip_path}")
        
        # Cleanup dist with retry/robustness
        print("Cleaning up dist directory...")
        
        def on_rm_error(func, path, exc_info):
            # Attempt to fix read-only files
            import stat
            os.chmod(path, stat.S_IWRITE)
            try:
                func(path)
            except Exception:
                pass
                
        # Simple retry
        import time
        for i in range(3):
            try:
                shutil.rmtree(dist, onerror=on_rm_error)
                break
            except Exception:
                time.sleep(1)

if __name__ == "__main__":
    main()
