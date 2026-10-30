"""Save installed versions and verified build hashes; never invent hardware results."""
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]


def capture(sdk_path=None,tools_path=None):
    packages={d.metadata["Name"]:d.version for d in importlib.metadata.distributions()}
    result={"protocol":"1.0","recorded_date":"2026-10-29","python":platform.python_version(),
            "python_executable":sys.executable,"os":platform.platform(),"packages":dict(sorted(packages.items())),
            "native_compiler":"Zig 0.14.1 / bundled Clang", "esp_idf":None,
            "local_paths":{"source":str(ROOT),"idf_path":sdk_path,"tools_path":tools_path,
                           "subst_target":str(Path(sdk_path).resolve().parents[1]) if sdk_path else None,
                           "build_root":str(Path.home()/"shdev/firmware-work")},
            "hardware_verified":False,"android_verified":False}
    if sdk_path:
        def git(*args):
            p=subprocess.run(["git","-C",sdk_path,*args],text=True,capture_output=True)
            return p.stdout.strip() if p.returncode==0 else None
        result["esp_idf"]={"requested_tag":"v5.5.1","commit":git("rev-parse","HEAD"),
                           "description":git("describe","--tags","--dirty"),"status":git("status","--short")}
    if tools_path:
        environments=list((Path(tools_path)/"python_env").glob("idf5.5_py*_env/Scripts/python.exe"))
        if len(environments)==1:
            sdk_python=environments[0]
            frozen=subprocess.check_output([str(sdk_python),"-m","pip","freeze"],text=True)
            (ROOT/"requirements.idf.lock.txt").write_text(frozen,encoding="utf-8")
            result["esp_idf"]["python_environment"]=str(sdk_python)
            result["esp_idf"]["python_dependencies"]="requirements.idf.lock.txt"
    (ROOT/"versions.lock").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    builds=[]
    for folder in sorted((ROOT/"build").glob("firmware-*")):
        binary=folder/"sound_haptic.bin"
        if binary.exists():
            stage=Path.home()/"shdev/firmware-work"/folder.name.removeprefix("firmware-")/"firmware"
            matches=stage.exists() and all((stage/p.relative_to(ROOT/"firmware")).exists() and
                p.read_bytes()==(stage/p.relative_to(ROOT/"firmware")).read_bytes()
                for p in (ROOT/"firmware").rglob("*") if p.is_file() and p.suffix in (".c",".h") and p.name!="hardware_profile.h")
            builds.append({"configuration":folder.name,"bytes":binary.stat().st_size,
                           "sha256":hashlib.sha256(binary.read_bytes()).hexdigest(),
                           "file":str(binary),"flashed":False,"staged_c_sources_match":matches})
    sources={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
             for p in (ROOT/"firmware").rglob("*") if p.is_file() and "build" not in p.parts}
    report={"date":"2026-10-29","builds":builds,"source_sha256":sources,
            "sdk":result["esp_idf"],"hardware_tests":"not run","android_tests":"not run"}
    (ROOT/"harness/reports/firmware_report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return report


if __name__=="__main__":
    print(json.dumps(capture(*(sys.argv[1:3])),ensure_ascii=False,indent=2))
