"""CLI flag parsing"""

_FLAGS_WITH_VALUES = {
    "--profile", "--host", "--token", "--filter", "--scope",
    "--limit", "--depth", "--id", "--path", "--warehouse",
    "--catalog", "--schema", "--name", "--sql", "--cluster",
    "--output", "--model", "--rows",
}


def parse_flags(args: list) -> dict:
    flags = {
        "run": False, "fresh": False, "cached": False,
        "aggressive": False, "extended": False,
        "profile": None, "host": None, "token": None,
        "filter": None, "scope": None, "id": None,
        "path": None, "warehouse": None, "catalog": None,
        "schema": None, "name": None, "sql": None,
        "cluster": None, "output": None, "model": None,
        "limit": 100, "depth": 0, "rows": None,
    }
    i = 0
    while i < len(args):
        a = args[i]
        if a.startswith("--"):
            key = a[2:].replace("-", "_")
            if a in _FLAGS_WITH_VALUES and i + 1 < len(args):
                flags[key] = args[i + 1]
                i += 2
                continue
            else:
                flags[key] = True
        i += 1

    for k in ("limit", "depth"):
        try:
            flags[k] = int(flags[k])
        except (TypeError, ValueError):
            flags[k] = 100 if k == "limit" else 0

    if flags["rows"] is not None:
        try:
            flags["rows"] = int(flags["rows"])
        except (TypeError, ValueError):
            flags["rows"] = 5

    return flags


def extract_positionals(argv: list) -> list:
    result = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in _FLAGS_WITH_VALUES:
            i += 2
        elif a.startswith("--"):
            i += 1
        else:
            result.append(a)
            i += 1
    return result


def limit(items: list, n: int) -> list:
    return items[:n] if n > 0 else items
