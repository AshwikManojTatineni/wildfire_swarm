#!/usr/bin/env python3
"""Print one scalar from config/runtime.yaml: `cfg.py FILE dotted.key`.

The host python3 on Torch login/compute nodes may lack PyYAML, so this reads the
small YAML subset runtime.yaml uses: nested block maps, inline `{k: v}` maps,
scalars, quotes and `#` comments. tests/test_cfg.py pins it against PyYAML.
"""
import re
import sys


def _scalar(text):
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        return text[1:-1]
    return text


def _strip_comment(line):
    quote = None
    for i, ch in enumerate(line):
        if ch in "\"'":
            quote = None if quote == ch else (quote or ch)
        elif ch == "#" and quote is None and (i == 0 or line[i - 1].isspace()):
            return line[:i]
    return line


def _inline_map(text):
    body = text.strip()[1:-1]
    out = {}
    for part in re.split(r",(?=(?:[^\"']*[\"'][^\"']*[\"'])*[^\"']*$)", body):
        if part.strip():
            k, v = part.split(":", 1)
            out[k.strip()] = _scalar(v)
    return out


def load(path):
    root, stack = {}, [(-1, None)]
    stack[0] = (-1, root)
    for raw in open(path, encoding="utf-8"):
        line = _strip_comment(raw).rstrip()
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        key, _, value = line.strip().partition(":")
        while stack[-1][0] >= indent:
            stack.pop()
        parent = stack[-1][1]
        value = value.strip()
        if value == "":
            parent[key] = {}
            stack.append((indent, parent[key]))
        elif value.startswith("{"):
            parent[key] = _inline_map(value)
        else:
            parent[key] = _scalar(value)
    return root


def main(argv):
    if len(argv) != 3:
        print("usage: cfg.py FILE dotted.key", file=sys.stderr)
        return 2
    node = load(argv[1])
    for part in argv[2].split("."):
        if not isinstance(node, dict) or part not in node:
            print(f"cfg.py: key not found: {argv[2]}", file=sys.stderr)
            return 1
        node = node[part]
    if isinstance(node, dict):
        print(f"cfg.py: {argv[2]} is a map", file=sys.stderr)
        return 1
    print(node)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
