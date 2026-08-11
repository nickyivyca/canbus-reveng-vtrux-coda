import os

artifacts_dir = os.path.dirname(__file__)
notes_dir = os.path.join(artifacts_dir, "..")

EXCLUDED_DIRS = {"artifacts", "__pycache__", "plans", "my-trucks", "rpo", "deprecated"}

artifact_files = set(os.listdir(artifacts_dir))
artifact_files.discard("find_referenced_artifacts.py")
artifact_files.discard("copy_referenced_artifacts.py")

notes_text = ""
searched_files = []
for root, dirs, files in os.walk(notes_dir):
    dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS]
    for f in files:
        if f.endswith(".md"):
            path = os.path.join(root, f)
            with open(path, encoding="utf-8", errors="replace") as fh:
                notes_text += fh.read() + "\n"
            searched_files.append(os.path.relpath(path, notes_dir))

referenced = set()
for name in artifact_files:
    if name in notes_text:
        referenced.add(name)

not_referenced = artifact_files - referenced

print(f"Notes files searched: {len(searched_files)}")
print(f"Total artifacts: {len(artifact_files)}")
print(f"Referenced in published notes: {len(referenced)}")
print(f"Not referenced: {len(not_referenced)}")
print()
print("=== REFERENCED ===")
for f in sorted(referenced):
    print(f" {f}")
print()
print("=== NOT REFERENCED (would be excluded) ===")
for f in sorted(not_referenced):
    print(f" {f}")
