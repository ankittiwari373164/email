"""
Chrome Version Fixer
═══════════════════

This script fixes the ChromeDriver version mismatch error:
"This version of ChromeDriver only supports Chrome version 151"
"Current browser version is 150.0.7871.125"

The problem: Your ChromeDriver (151) doesn't match your Chrome (150)
The solution: Update Chrome OR reinstall the matching ChromeDriver
"""

import subprocess
import sys
import os
import shutil
import platform

def get_chrome_version():
    """Get installed Chrome version."""
    system = platform.system()
    
    if system == "Windows":
        # Windows
        paths = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
        ]
        
        for path in paths:
            if os.path.exists(path):
                try:
                    result = subprocess.run([path, "--version"], capture_output=True, text=True)
                    version = result.stdout.strip().replace("Google Chrome ", "")
                    return version
                except:
                    pass
    
    elif system == "Darwin":
        # macOS
        path = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        if os.path.exists(path):
            try:
                result = subprocess.run([path, "--version"], capture_output=True, text=True)
                version = result.stdout.strip().replace("Google Chrome ", "")
                return version
            except:
                pass
    
    elif system == "Linux":
        # Linux
        try:
            result = subprocess.run(["google-chrome", "--version"], capture_output=True, text=True)
            version = result.stdout.strip().replace("Google Chrome ", "")
            return version
        except:
            pass
    
    return None


def main():
    print("=" * 70)
    print("CHROME VERSION DIAGNOSTIC")
    print("=" * 70)
    
    chrome_version = get_chrome_version()
    
    if not chrome_version:
        print("\n❌ Could not find Chrome installation")
        print("\nPlease download Chrome from: https://www.google.com/chrome")
        return
    
    print(f"\n✓ Found Chrome version: {chrome_version}")
    
    major_version = int(chrome_version.split(".")[0])
    print(f"✓ Major version: {major_version}")
    
    print("\n" + "=" * 70)
    print("FIXING CHROMEDRIVER")
    print("=" * 70)
    
    print(f"\nUpdating webdriver-manager to get ChromeDriver {major_version}...")
    
    try:
        # Uninstall old chromedriver cache
        cache_dir = os.path.expanduser("~/.wdm/drivers/chromedriver")
        if os.path.exists(cache_dir):
            print(f"Clearing old ChromeDriver cache: {cache_dir}")
            shutil.rmtree(cache_dir)
            print("✓ Cache cleared")
        
        # Update webdriver-manager
        print("\nInstalling/updating webdriver-manager...")
        subprocess.run([sys.executable, "-m", "pip", "install", "--upgrade", "webdriver-manager"], check=True)
        print("✓ webdriver-manager updated")
        
        # Update undetected-chromedriver
        print("\nInstalling/updating undetected-chromedriver...")
        subprocess.run([sys.executable, "-m", "pip", "install", "--upgrade", "undetected-chromedriver"], check=True)
        print("✓ undetected-chromedriver updated")
        
    except subprocess.CalledProcessError as e:
        print(f"❌ Error updating drivers: {e}")
        return
    
    print("\n" + "=" * 70)
    print("✓ DONE! Try running your scraper now:")
    print("=" * 70)
    print('\npython local_scraper_production.py --login-only\n')


if __name__ == "__main__":
    main()