from .chars import is_quote


def split_line(line):
    fields, cur, i, quoted = [], [], 0, False
    while i < len(line):
        ch = line[i]
        if quoted:
            if is_quote(ch):
                if i + 1 < len(line) and is_quote(line[i + 1]):
                    cur.append(ch)
                    i += 1
                else:
                    quoted = False
            else:
                cur.append(ch)
        elif is_quote(ch):
            quoted = True
        elif ch == ",":
            fields.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
        i += 1
    if cur:
        fields.append("".join(cur))
    return fields


def join_line(fields):
    out = []
    for f in fields:
        if "," in f or '"' in f:
            out.append('"' + f.replace('"', '""') + '"')
        else:
            out.append(f)
    return ",".join(out)
