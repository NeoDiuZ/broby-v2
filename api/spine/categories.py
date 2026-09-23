ALIASES = {
    'bloods': 'lab_result', 'lab': 'lab_result', 'lab_result': 'lab_result',
    'x-ray': 'x_ray', 'xray': 'x_ray', 'x_ray': 'x_ray',
    'consultation': 'consult', 'consult': 'consult',
    'vaccine': 'vaccination', 'vaccination': 'vaccination',
}


def canonical(value):
    key = value.strip().lower()
    return ALIASES.get(key, key)


def aliases(value):
    key = canonical(value)
    return list({key, *(k for k, v in ALIASES.items() if v == key)})
