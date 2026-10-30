"""Create an allowlisted developer handoff ZIP; never include live audio captures."""
import hashlib
import json
from pathlib import Path
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from harness.demo import run


def main():
    examples=ROOT/"build/share-examples"
    run(examples)
    output=ROOT/"dist"
    output.mkdir(exist_ok=True)
    archive=output/"sound-haptic-devkit-v1.0.0.zip"
    files={}
    for name in ("README.md","pyproject.toml","requirements-dev.txt","requirements.lock.txt","requirements.idf.lock.txt","versions.lock",
                 "BLE_INTERFACE.ko.md","HARNESS_DESIGN.ko.md","IMPLEMENTATION_BRIEF.ko.md",".gitignore"):
        files[name]=ROOT/name
    for folder in ("contracts","docs","firmware","hardware","tests","scripts"):
        for path in (ROOT/folder).rglob("*"):
            if path.is_file() and not any(p in ("__pycache__","build") for p in path.relative_to(ROOT).parts) and path.name!="sdkconfig":
                files[path.relative_to(ROOT).as_posix()]=path
    for path in (ROOT/"harness").rglob("*.py"):
        files[path.relative_to(ROOT).as_posix()]=path
    for path in (ROOT/"harness/reports").glob("*"):
        if path.suffix in (".json",".xml",".txt"):
            files[path.relative_to(ROOT).as_posix()]=path
    for path in examples.iterdir():
        if path.is_file():files["examples/"+path.name]=path
    manifest={key:hashlib.sha256(path.read_bytes()).hexdigest() for key,path in sorted(files.items())}
    with zipfile.ZipFile(archive,"w",compression=zipfile.ZIP_DEFLATED) as z:
        for key,path in sorted(files.items()):z.write(path,key)
        z.writestr("MANIFEST.sha256.json",json.dumps(manifest,indent=2))
    checksum=hashlib.sha256(archive.read_bytes()).hexdigest()
    (output/(archive.name+".sha256")).write_text(checksum+"  "+archive.name+"\n",encoding="ascii")
    print(json.dumps({"archive":str(archive),"files":len(files)+1,"bytes":archive.stat().st_size,"sha256":checksum},indent=2))


if __name__=="__main__":main()
