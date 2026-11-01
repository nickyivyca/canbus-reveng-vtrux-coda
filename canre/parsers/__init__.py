"""Log file parsers for various CAN bus tools: a re-export of can-tools' ``canbench.parsers``.

The readers live in the git repo nickyivyca/can-tools (``canbench/parsers/``); this package
only forwards to them, so ``from canre.parsers import parse_file`` and the module paths
(``canre.parsers.busmaster``, ``canre.parsers.base`` ...) keep working. Documentation:
``canre/parsers/parsers.md``, which points to can-tools' ``canbench/parsers/parsers.md``.

``canbench`` is found the normal way first (on a reverse-it machine, the per-machine clone via
its ``.pth`` file; see tools-reference.md, section "can-tools"), then in the ``can-tools/``
submodule at the root of a public-repo clone.
"""
import importlib
import sys
from pathlib import Path

_SUBMODULES = ("autodetect", "base", "busmaster", "candump", "peak_trc", "savvycan",
               "vector_asc")


def _import_canbench_parsers():
    try:
        return importlib.import_module("canbench.parsers")
    except ImportError:
        pass
    submodule = Path(__file__).resolve().parents[2] / "can-tools"
    if (submodule / "canbench" / "parsers" / "__init__.py").is_file():
        sys.path.insert(0, str(submodule))
        try:
            return importlib.import_module("canbench.parsers")
        except ImportError:
            pass
    raise ImportError(
        "canre.parsers re-exports canbench.parsers (git repo nickyivyca/can-tools), and no "
        "canbench with a parsers package is importable. In a clone of the public repo run "
        "'git submodule update --init'; on a reverse-it machine set up the can-tools clone "
        "per tools-reference.md, section 'can-tools'.")


_impl = _import_canbench_parsers()

for _name in _SUBMODULES:
    _module = importlib.import_module(f"canbench.parsers.{_name}")
    sys.modules[f"{__name__}.{_name}"] = _module
    globals()[_name] = _module

CANFrame = _impl.CANFrame
CANEvent = _impl.CANEvent
BaseParser = _impl.BaseParser
detect_format = _impl.detect_format
parse_file = _impl.parse_file

__all__ = ["CANFrame", "CANEvent", "BaseParser", "detect_format", "parse_file"]
