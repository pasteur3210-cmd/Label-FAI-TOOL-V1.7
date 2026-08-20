from pathlib import Path
import logging
from datetime import datetime

def setup_logging(base_dir="logs"):
    p = Path(base_dir)
    p.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    execution = p / f"execution_{stamp}.log"
    debug = p / f"debug_{stamp}.log"

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")

    fh = logging.FileHandler(debug, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    root.addHandler(fh)

    eh = logging.FileHandler(execution, encoding="utf-8")
    eh.setLevel(logging.INFO)
    eh.setFormatter(fmt)
    root.addHandler(eh)

    return str(execution), str(debug)
