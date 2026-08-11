import os
import re
import shutil

src_artifacts = os.path.dirname(__file__)
dst_artifacts = r"C:\Users\<user>\Git\canbus-reveng-vtrux-coda\projects\vtrux\notes\artifacts"
notes_dir = os.path.join(src_artifacts, "..")

os.makedirs(dst_artifacts, exist_ok=True)

artifact_entries = set(os.listdir(src_artifacts))
artifact_entries.discard("copy_referenced_artifacts.py")
artifact_entries.discard("find_referenced_artifacts.py")

notes_text = ""
for root, dirs, files in os.walk(notes_dir):
    dirs[:] = [d for d in dirs if d not in ("artifacts", "__pycache__", "plans")]
    for f in files:
        if f.endswith(".md"):
            path = os.path.join(root, f)
            with open(path, encoding="utf-8", errors="replace") as fh:
                notes_text += fh.read() + "\n"

referenced = [name for name in artifact_entries if name in notes_text]

copied_files = 0
copied_dirs = 0
skipped = 0

for name in sorted(referenced):
    src = os.path.join(src_artifacts, name)
    dst = os.path.join(dst_artifacts, name)
    if os.path.isdir(src):
        if not os.path.exists(dst):
            shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__"))
        copied_dirs += 1
        print(f"  DIR  {name}")
    elif os.path.isfile(src):
        shutil.copy2(src, dst)
        copied_files += 1
    else:
        skipped += 1

print(f"\nCopied {copied_files} files, {copied_dirs} dirs, skipped {skipped}")
