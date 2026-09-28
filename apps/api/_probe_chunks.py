import pathlib
import re

f = pathlib.Path("generated/projects/pmtest00001/out/_next/static/chunks/webpack-0c6a890f32d5c628.js")
c = f.read_text(encoding="utf-8", errors="replace")
i = c.find("d.tu")
print("d.tu context:", c[i-200:i+300])
print()
# how does main-app load the page chunk? search for the page chunk name in all chunks
root = pathlib.Path("generated/projects/pmtest00001/out/_next/static/chunks")
for g in sorted(root.glob("*.js")):
    cc = g.read_text(encoding="utf-8", errors="replace")
    if "page-ffc06cd4473239c6" in cc:
        print("page chunk name found in:", g.name)
        for m in re.findall(r".{80}page-ffc06cd4473239c6.{40}", cc)[:3]:
            print("  CTX:", m)