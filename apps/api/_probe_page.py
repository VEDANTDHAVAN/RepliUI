path = "apps/web/src/app/page.tsx"
c = open(path, encoding="utf-8").read()
line = c.split("\n")[12]
with open("apps/api/_probe_out.txt", "w", encoding="utf-8") as f:
    f.write("around 2653:\n")
    f.write(repr(line[2600:2720]) + "\n")
    f.write("char 2653 = " + repr(line[2652]) + "\n")
    # brace balance up to 2653
    seg = line[:2653]
    f.write(f"braces before 2653: {{ = {seg.count('{')}, }} = {seg.count('}')}\n")