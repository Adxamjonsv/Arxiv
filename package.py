from pathlib import Path
import zipfile
ROOT=Path(__file__).resolve().parent
OUT=ROOT.parent/"telegram_archive_recovery.zip"
EXCLUDE={".git",".venv","__pycache__","storage","sessions"}
def main():
    with zipfile.ZipFile(OUT,"w",zipfile.ZIP_DEFLATED) as z:
        for p in ROOT.rglob("*"):
            if p.is_file() and not any(x in EXCLUDE for x in p.parts) and p.name not in {".env","archive.db",OUT.name} and p.suffix not in {".pyc",".pyo"}:
                z.write(p,p.relative_to(ROOT))
    print(OUT)
if __name__=="__main__":main()
