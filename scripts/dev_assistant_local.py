import os
import subprocess
from dotenv import load_dotenv

load_dotenv()
repo = os.getenv("LOCAL_REPO_PATH", "")
branch = input("Branch to checkout: ").strip()
ide = input("Open with (idea/code/none): ").strip()

subprocess.check_call(["git", "-C", repo, "fetch"])
subprocess.check_call(["git", "-C", repo, "checkout", branch])

if ide == "idea":
    subprocess.Popen(["idea", repo])
elif ide == "code":
    subprocess.Popen(["code", repo])

print("Done.")
