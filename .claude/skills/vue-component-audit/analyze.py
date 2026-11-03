#!/usr/bin/env python3
"""Structural audit of Vue single-file components.

Output lists candidates, not verdicts: every finding needs a read of the flagged code.
"""
import argparse
import hashlib
import json
import os
import re
from collections import defaultdict
from pathlib import Path

# client/CLAUDE.md: extract a component once the template passes 100 lines or the script 150
TEMPLATE_LIMIT = 100
SCRIPT_LIMIT = 150
MIN_RULE_DECLS = 3
MIN_BODY_CHARS = 60
MIN_SHARED_RULES = 5
IGNORED_CALLS = {"t"}
UTILITY_NAME = re.compile(r"^(format|get|is|calc|compute|translate|parse|to)[A-Z]")

BLOCK_OPEN = re.compile(r"^<(template|script|style)\b[^>]*>\s*$")
VFOR = re.compile(r'v-for="([^"]+?)\s+(?:in|of)\s+([^"]+)"')
KEY_ATTR = re.compile(r'(?::|v-bind:)key="([^"]*)"')
CALL = re.compile(r"(?<![\w.])([A-Za-z_]\w*)\(")
SCAN = re.compile(
    r"\.(?:find|findIndex|filter|reduce|some|every|map|sort|indexOf|includes)\(|\bfor\s*\(|\bwhile\s*\("
)
# Preceded by whitespace so the // in 'http://...' string literals survives.
LINE_COMMENT = re.compile(r"(?m)(?:^|\s)//[^\n]*")
BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
FUNC_DECL = re.compile(
    r"(?:const|let)\s+(\w+)\s*=\s*(?:async\s*)?(?:\([^)]*\)|\w+)\s*=>\s*"
    r"|(?:async\s+)?function\s+(\w+)\s*\([^)]*\)\s*"
)
COMPUTED_DECL = re.compile(r"(?:const|let)\s+(\w+)\s*=\s*computed\(")
RULE = re.compile(r"([^{}]+)\{([^{}]*)\}")


def split_blocks(lines):
    """Map block kind to (1-based number of its first body line, body lines)."""
    blocks = {}
    i = 0
    while i < len(lines):
        m = BLOCK_OPEN.match(lines[i])
        if m:
            kind = m.group(1)
            end = next(
                (j for j in range(i + 1, len(lines)) if lines[j].startswith("</" + kind + ">")),
                len(lines),
            )
            blocks.setdefault(kind, (i + 2, lines[i + 1:end]))
            i = end
        i += 1
    return blocks


def indent(line):
    return len(line) - len(line.lstrip())


def read_body(src, pos):
    if src[pos:pos + 1] != "{":
        end = src.find("\n", pos)
        return src[pos:end if end != -1 else len(src)]
    depth, quote, i = 0, None, pos
    while i < len(src):
        c = src[i]
        if quote:
            if c == "\\":
                i += 1
            elif c == quote:
                quote = None
        elif c in "'\"`":
            quote = c
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return src[pos:i + 1]
        i += 1
    return src[pos:]


def strip_comments(src):
    # Line numbers of functions are counted in the stripped text, so newlines must survive.
    keep_newlines = lambda m: "\n" * m.group().count("\n")
    return LINE_COMMENT.sub(keep_newlines, BLOCK_COMMENT.sub(keep_newlines, src))


def extract_functions(src):
    """Return [(name, offset, body)] for arrow-function consts and function declarations."""
    found = []
    for m in FUNC_DECL.finditer(src):
        found.append((m.group(1) or m.group(2), m.start(), read_body(src, m.end())))
    return found


def tag_window(body, idx):
    start = idx
    while start > 0 and idx - start < 10 and not re.match(r"\s*<[A-Za-z]", body[start]):
        start -= 1
    end = idx
    while end < len(body) - 1 and end - idx < 14 and not body[end].rstrip().endswith(">"):
        end += 1
    return start, end


def loop_region(body, start, end):
    base = indent(body[start])
    out = []
    for line in body[end + 1:]:
        if line.strip() not in ("", ">", "/>") and indent(line) <= base:
            break
        out.append(line)
    return out


def audit_template(rel, first_line, body, scanning_funcs, add):
    loop_calls = defaultdict(int)
    first_loop = None
    for idx, line in enumerate(body):
        m = VFOR.search(line)
        if not m:
            continue
        lineno = first_line + idx
        first_loop = first_loop or lineno
        start, end = tag_window(body, idx)
        tag = " ".join(l.strip() for l in body[start:end + 1])
        names = re.findall(r"\w+", m.group(1))
        source = m.group(2).strip()

        key = KEY_ATTR.search(tag)
        if not key:
            add("perf", "warn", rel, lineno, "v-for-key", "v-for without :key")
        elif key.group(1).strip() in names[1:] or key.group(1).strip() in ("index", "idx", "i"):
            add("perf", "warn", rel, lineno, "v-for-index-key",
                "v-for keyed by index (%s): rows are reused wrongly when the list changes" % key.group(1).strip())
        if re.search(r"(?<![-\w])v-if=", tag):
            add("perf", "warn", rel, lineno, "v-if-with-v-for",
                "v-if on the same element as v-for; filter in a computed instead")
        if not source.isdigit() and re.search(r"\w\(", source):
            add("perf", "info", rel, lineno, "list-in-template",
                "list built inside the template (%s) and rebuilt on every render; move it to a computed" % source)

        scanned = [VFOR.sub("", l) for l in body[start:end + 1]] + loop_region(body, start, end)
        for called in CALL.findall("\n".join(scanned)):
            if called in IGNORED_CALLS or called not in scanning_funcs:
                continue
            if scanning_funcs[called]:
                add("perf", "warn", rel, lineno, "method-in-loop",
                    "%s() scans an array and runs once per row (quadratic); precompute a lookup in a computed" % called)
            else:
                loop_calls[called] += 1
    if loop_calls:
        summary = ", ".join("%s x%d" % kv for kv in sorted(loop_calls.items()))
        add("perf", "info", rel, first_loop, "plain-calls-in-loop",
            "plain functions called per row: %s (cheap unless the data is large)" % summary)


def style_rules(first_line, body):
    text = BLOCK_COMMENT.sub(lambda m: "\n" * m.group().count("\n"), "\n".join(body))
    for m in RULE.finditer(text):
        decls = sorted(" ".join(d.lower().split()) for d in m.group(2).split(";") if d.strip())
        if len(decls) < MIN_RULE_DECLS:
            continue
        sel = m.group(1)
        offset = m.start(1) + len(sel) - len(sel.lstrip())
        yield (
            hashlib.md5("; ".join(decls).encode()).hexdigest(),
            " ".join(sel.split()),
            len(decls),
            first_line + text[:offset].count("\n"),
        )


def collect(paths):
    files = []
    for p in paths:
        path = Path(p)
        found = [path] if path.is_file() else sorted(path.rglob("*.vue"))
        files += [f for f in found if "node_modules" not in f.parts]
    return files


def audit_router(root, add):
    if not root.is_dir():
        return
    for path in sorted(root.rglob("*.js")):
        if "node_modules" in path.parts or "createRouter" not in path.read_text(errors="replace"):
            continue
        text = path.read_text(errors="replace")
        for m in re.finditer(r"^import\s+(\w+)\s+from\s+['\"][^'\"]*views/[^'\"]+\.vue['\"]", text, re.M):
            add("perf", "info", os.path.relpath(path), text[:m.start()].count("\n") + 1, "eager-route",
                "route view %s is imported eagerly; () => import(...) splits it out of the first bundle" % m.group(1))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("paths", nargs="+", help=".vue files or directories")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--limit", type=int, default=20, help="entries per section in text output")
    args = ap.parse_args()

    findings, metrics = [], []

    def add(group, severity, file, line, kind, message):
        findings.append({"group": group, "severity": severity, "file": file, "line": line,
                         "kind": kind, "message": message})

    hash_funcs = defaultdict(list)
    name_funcs = defaultdict(list)
    rule_sites = defaultdict(list)

    files = collect(args.paths)
    for path in files:
        rel = os.path.relpath(path)
        lines = path.read_text(errors="replace").split("\n")
        blocks = split_blocks(lines)
        tpl_first, tpl = blocks.get("template", (1, []))
        scr_first, scr = blocks.get("script", (1, []))
        sty_first, sty = blocks.get("style", (1, []))
        metrics.append({"file": rel, "lines": len(lines), "template": len(tpl),
                        "script": len(scr), "style": len(sty)})

        if len(tpl) > TEMPLATE_LIMIT:
            add("reuse", "info", rel, tpl_first, "large-template",
                "template is %d lines (limit %d); look for repeated markup to extract" % (len(tpl), TEMPLATE_LIMIT))
        if len(scr) > SCRIPT_LIMIT:
            add("reuse", "info", rel, scr_first, "large-script",
                "script is %d lines (limit %d); look for logic to move into a composable" % (len(scr), SCRIPT_LIMIT))

        script_src = strip_comments("\n".join(scr))
        funcs = extract_functions(script_src)
        computed = set(COMPUTED_DECL.findall(script_src))
        scanning = {n: bool(SCAN.search(b)) for n, _, b in funcs if n not in computed}
        audit_template(rel, tpl_first, tpl, scanning, add)

        for i, line in enumerate(scr):
            if re.search(r"deep:\s*true", line):
                add("perf", "info", rel, scr_first + i, "deep-watch",
                    "deep watcher traverses the whole structure on every change; watch a narrower source")

        for name, offset, body in funcs:
            norm = re.sub(r"\s+", "", body)
            if len(norm) >= MIN_BODY_CHARS:
                site = (rel, scr_first + script_src[:offset].count("\n"), name)
                hash_funcs[hashlib.md5(norm.encode()).hexdigest()].append(site)
                name_funcs[name].append((site, norm))

        for key, selector, ndecl, lineno in style_rules(sty_first, sty):
            rule_sites[key].append((rel, lineno, selector, ndecl))

    for sites in hash_funcs.values():
        if len({s[0] for s in sites}) > 1:
            where = ", ".join("%s:%d %s()" % s for s in sites)
            add("reuse", "warn", sites[0][0], sites[0][1], "duplicate-function",
                "identical function body in %d files: %s" % (len(sites), where))
    for name, entries in name_funcs.items():
        if UTILITY_NAME.match(name) and len({e[0][0] for e in entries}) > 1 and len({e[1] for e in entries}) > 1:
            where = ", ".join("%s:%d" % e[0][:2] for e in entries)
            add("reuse", "info", entries[0][0][0], entries[0][0][1], "diverged-function",
                "%s() exists in several files with different bodies (%s); confirm the difference is intended" % (name, where))

    pair_counts = defaultdict(int)
    for sites in rule_sites.values():
        owners = sorted({s[0] for s in sites})
        if len(owners) < 2:
            continue
        sample = sites[0]
        add("reuse", "info", sample[0], sample[1], "duplicate-style",
            "rule with %d declarations repeats in %d files (e.g. %s): %s"
            % (sample[3], len(owners), sample[2], ", ".join("%s:%d" % s[:2] for s in sites)))
        for a in range(len(owners)):
            for b in range(a + 1, len(owners)):
                pair_counts[(owners[a], owners[b])] += 1
    for (a, b), n in pair_counts.items():
        if n >= MIN_SHARED_RULES:
            add("reuse", "warn", a, 1, "shared-styles",
                "%s and %s share %d identical style rules; a shared stylesheet or base component would remove them" % (a, b, n))

    for arg in args.paths:
        audit_router(Path(arg), add)

    order = {"warn": 0, "info": 1}
    findings.sort(key=lambda f: (order[f["severity"]], f["file"], f["line"]))
    metrics.sort(key=lambda m: -m["lines"])

    if args.json:
        print(json.dumps({"files": len(files), "metrics": metrics, "findings": findings}, indent=2))
        return

    print("Vue component audit: %d files\n" % len(files))
    print("Largest components")
    for m in metrics[:8]:
        print("  %5d lines  %s  (template %d, script %d, style %d)"
              % (m["lines"], m["file"], m["template"], m["script"], m["style"]))
    for group, title in (("perf", "Performance"), ("reuse", "Reuse")):
        picked = [f for f in findings if f["group"] == group]
        print("\n%s (%d)" % (title, len(picked)))
        for f in picked[:args.limit]:
            print("  [%s] %s:%d  %s  %s" % (f["severity"], f["file"], f["line"], f["kind"], f["message"]))
        if len(picked) > args.limit:
            print("  ... %d more, raise --limit or use --json" % (len(picked) - args.limit))


if __name__ == "__main__":
    main()
