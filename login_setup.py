"""
LOGIN SETUP — run this ONCE before using local_scraper.py

Google refuses to let you sign in inside a Selenium-controlled window
("This browser or app may not be secure") — that's a deliberate Google
security feature detecting the automation flag, and not something this
project will try to strip or spoof to get around.

The legitimate way around it: log in through PLAIN, ordinary Chrome
(no automation involved at all) pointed at the same profile folder
local_scraper.py uses. Once you're logged in there, close it — the
session/cookies are saved to disk in that profile folder, and
local_scraper.py's Selenium session will pick them up automatically
without ever needing to perform the sign-in flow itself.

USAGE:
   python login_setup.py

This finds your installed Chrome, launches it normally (not via
Selenium) with the same dedicated profile folder, and waits for you to
close it after logging in.
"""

import os
import shutil
import subprocess
import sys

PROFILE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chrome_profile")

CHROME_PATHS_WINDOWS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
]


def find_chrome():
    # Try PATH first
    for name in ("chrome", "chrome.exe", "google-chrome", "google-chrome-stable"):
        found = shutil.which(name)
        if found:
            return found
    # Common Windows install locations
    for path in CHROME_PATHS_WINDOWS:
        if os.path.exists(path):
            return path
    return None


def main():
    chrome_path = find_chrome()
    if not chrome_path:
        print("Couldn't find Chrome automatically.")
        print("Please provide the full path to chrome.exe as an argument:")
        print(r'   python login_setup.py "C:\Program Files\Google\Chrome\Application\chrome.exe"')
        if len(sys.argv) > 1:
            chrome_path = sys.argv[1]
        else:
            sys.exit(1)

    os.makedirs(PROFILE_DIR, exist_ok=True)

    print("=" * 70)
    print("Launching plain Chrome (not automated) with the dedicated")
    print("profile local_scraper.py will reuse.")
    print("=" * 70)
    print("\n1. Log into your Google account normally in the window that opens.")
    print("2. Once logged in, just close that Chrome window.")
    print("3. Then run: python local_scraper.py \"category\" \"city\"\n")

    # Launched as a normal OS process — NOT via Selenium/webdriver, so
    # none of the automation flags that trigger Google's block are set.
    subprocess.run([chrome_path, f"--user-data-dir={PROFILE_DIR}", "https://accounts.google.com"])

    print("\nChrome closed. If you logged in, the session is saved.")
    print("You can now run local_scraper.py — it'll reuse this login.")


if __name__ == "__main__":
    main()