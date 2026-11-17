from .copying import deep_copy


def merge(base, override):
    result = deep_copy(base)
    for key, value in override.items():
        if isinstance(key, str) and key.startswith("+"):
            name = key[1:]
            existing = result.get(name, [])
            if not isinstance(existing, list) or not isinstance(value, list):
                raise ValueError(f"cannot append to {name!r}")
            result[name] = existing + deep_copy(value)
        elif value is None:
            result.pop(key, None)
        elif isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge(result[key], value)
        else:
            result[key] = deep_copy(value)
    return result
