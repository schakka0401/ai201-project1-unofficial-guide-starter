"""
inspect_clean.py — print the FULL cleaned text of one source, for the
"print one document and read it" verification step.

Usage:
    python inspect_clean.py                 # lists available sources
    python inspect_clean.py kbb_fpp         # prints cleaned text for that source
    python inspect_clean.py kbb_fpp --head 60   # first 60 lines only

Read the output and look for: leftover HTML tags, &amp;/&nbsp; entities,
navigation menus, cookie banners, "Read more"/share buttons, comment counts,
or text that isn't from your domain. If you see any, that source needs more
cleaning before you build the index.
"""

import sys
import load


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    head = None
    if "--head" in sys.argv:
        i = sys.argv.index("--head")
        head = int(sys.argv[i + 1])

    records = {r["name"]: r for r in load.read_manifest()
               if not r.get("error")}

    if not args:
        print("Available sources:")
        for name, r in records.items():
            print(f"  {name:<20} ({r['source_type']})  {r['url']}")
        print("\nRun: python inspect_clean.py <source_name>")
        return

    name = args[0]
    if name not in records:
        print(f"No source named {name!r}. Available: {', '.join(records)}")
        return

    text = load.load_document(records[name])
    lines = text.split("\n")
    shown = lines[:head] if head else lines

    print(f"=== {name}  ({records[name]['source_type']}) ===")
    print(f"=== {records[name]['url']} ===")
    print(f"=== {len(text):,} chars, {len(lines)} lines"
          f"{f' (showing first {head})' if head else ''} ===\n")
    print("\n".join(shown))

    # Quick automated red-flags so you don't have to eyeball everything.
    print("\n--- automated checks ---")
    flags = []
    if "<" in text and ">" in text and any(
            t in text.lower() for t in ("<div", "<span", "<p>", "<a ", "</")):
        flags.append("possible leftover HTML tags")
    for ent in ("&amp;", "&nbsp;", "&#", "&quot;", "&lt;", "&gt;"):
        if ent in text:
            flags.append(f"leftover entity {ent}")
    if flags:
        print("FLAGS:", "; ".join(flags))
    else:
        print("no obvious tags or entities detected")


if __name__ == "__main__":
    main()