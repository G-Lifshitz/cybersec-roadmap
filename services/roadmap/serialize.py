"""Turn the domain's frozen dataclasses into JSON-ready dicts.

In Assignment 1 the Jinja templates read properties such as phase.date_range
directly. The static UI can't call Python, so the properties it needs are
computed here and sent along with the fields.
"""
import dataclasses
from datetime import date, datetime


def jsonable(value):
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        out = {f.name: jsonable(getattr(value, f.name)) for f in dataclasses.fields(value)}
        for name, attr in vars(type(value)).items():
            if isinstance(attr, property):
                out[name] = jsonable(getattr(value, name))
        return out
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value
