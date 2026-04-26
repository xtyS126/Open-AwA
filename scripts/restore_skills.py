"""Restore skills.py from git"""
import subprocess
import os

repo_dir = r"d:\代码\Open-AwA"
result = subprocess.run(
    ["git", "checkout", "--", "backend/api/routes/skills.py"],
    cwd=repo_dir,
    capture_output=True,
    text=True,
    timeout=30
)
print("STDOUT:", result.stdout)
print("STDERR:", result.stderr)
print("Return code:", result.returncode)
