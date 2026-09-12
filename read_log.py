import sys
with open("backend.log", "r", encoding="utf-8", errors="replace") as f:
    lines = f.readlines()
    for line in lines[-50:]:
        print(line, end="")
