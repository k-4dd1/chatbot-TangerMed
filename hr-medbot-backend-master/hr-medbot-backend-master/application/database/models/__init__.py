import importlib
import pkgutil
from pathlib import Path

__all__ = []

for finder, name, ispkg in pkgutil.iter_modules([str(Path(__file__).parent)]):
    if name == "__init__" or ispkg:
        continue

    mod = importlib.import_module(f".{name}", __package__)
    globals()[name] = mod

    # use module’s own __all__ if present, else grab all its classes
    names = getattr(mod, "__all__", [
        attr for attr, obj in vars(mod).items()
        if isinstance(obj, type) and obj.__module__ == mod.__name__
    ])
    for attr in names:
        globals()[attr] = getattr(mod, attr)
    __all__.extend(names)
