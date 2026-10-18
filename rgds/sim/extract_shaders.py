#!/usr/bin/env python3
"""Copy the GLSL string constants (VERT_SRC, FRAG_*) out of libdrastouch.c into shaders.h."""
import re, sys
src = open(sys.argv[1]).read()
pat = re.compile(r'static const char \*((?:VERT|FRAG|NITRO)_\w+)\s*=\s*((?:\s*"(?:[^"\\]|\\.)*")+)\s*;')
out = []
names = []
for name, lit in pat.findall(src):
    out.append(f"static const char *{name} ={lit};\n")
    names.append(name)
out.append("static const struct { const char *name; const char **src; } FRAGS[] = {\n")
for n in names:
    if n.startswith("FRAG_"):
        out.append(f'    {{ "{n[5:].lower().replace("_", "-")}", &{n} }},\n')
out.append("};\n")
open(sys.argv[2], "w").write("".join(out))
print(" ".join(names))
