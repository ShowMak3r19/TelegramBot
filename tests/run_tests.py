"""统一通过 pytest 运行，支持 tmp_path、monkeypatch 等夹具。"""
from pathlib import Path
import subprocess
import sys

if __name__ == "__main__":
    raise SystemExit(subprocess.call([sys.executable, "-m", "pytest", "-q", str(Path(__file__).parent)]))
