"""冻结最终代码、配置、证据输出和大数据引用的SHA-256复现清单。"""
from __future__ import annotations
import hashlib,json,platform,subprocess,sys
from datetime import datetime
from pathlib import Path
import pandas as pd
PROJECT_ROOT=Path(__file__).resolve().parents[2]
OUTPUT_DIR=PROJECT_ROOT/"outputs"/"reproducibility"
def digest(path):
    h=hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda:stream.read(1048576),b""): h.update(chunk)
    return h.hexdigest()
def record(path,category):
    return dict(category=category,relative_path=path.relative_to(PROJECT_ROOT).as_posix(),size_bytes=path.stat().st_size,modified_time=datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds"),sha256=digest(path))
def main():
    OUTPUT_DIR.mkdir(parents=True,exist_ok=True)
    source=[]
    for path in sorted(PROJECT_ROOT.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts or ".git" in path.parts: continue
        relative=path.relative_to(PROJECT_ROOT)
        if relative.parts[0] in {"data","outputs","logs"}: continue
        if path.suffix.lower() in {".py",".yaml",".yml",".md",".txt",".tex"} or path.name in {"requirements.txt","README.md"}:
            source.append(record(path,"source_config_documentation"))
    evidence=[]
    for path in sorted((PROJECT_ROOT/"outputs").rglob("*")):
        if path.is_file() and "reproducibility" not in path.parts:
            evidence.append(record(path,"evidence_output"))
    large=[]
    for path,label in [(PROJECT_ROOT/"data"/"database"/"cf2026_project1.duckdb","database_snapshot"),(PROJECT_ROOT/"outputs"/"data_audit"/"06_raw_snapshot_manifest_sha256.csv","raw_snapshot_manifest")]:
        if path.exists(): large.append(record(path,label))
    pd.DataFrame(source).to_csv(OUTPUT_DIR/"03_source_code_config_manifest_sha256.csv",index=False,encoding="utf-8-sig")
    pd.DataFrame(evidence).to_csv(OUTPUT_DIR/"03_evidence_outputs_manifest_sha256.csv",index=False,encoding="utf-8-sig")
    pd.DataFrame(large).to_csv(OUTPUT_DIR/"03_large_artifacts_manifest_sha256.csv",index=False,encoding="utf-8-sig")
    try:
        commit=subprocess.run(["git","-C",str(PROJECT_ROOT),"rev-parse","HEAD"],capture_output=True,text=True,check=True).stdout.strip()
        dirty=bool(subprocess.run(["git","-C",str(PROJECT_ROOT),"status","--porcelain"],capture_output=True,text=True,check=True).stdout.strip())
    except Exception:
        commit=None; dirty=None
    metadata=dict(generated_at=datetime.now().isoformat(timespec="seconds"),python=sys.version,platform=platform.platform(),git_commit=commit,git_worktree_dirty=dirty,source_file_count=len(source),evidence_file_count=len(evidence),large_artifact_count=len(large),raw_file_level_manifest="outputs/data_audit/06_raw_snapshot_manifest_sha256.csv",manifest_scope="源码/配置/文档逐文件；outputs证据逐文件；数据库与原始数据清单为大文件引用；原始文件逐项哈希见raw_file_level_manifest")
    (OUTPUT_DIR/"03_reproduction_metadata.json").write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(metadata,ensure_ascii=False,indent=2)); print("[PASS] 最终分层复现清单已冻结。")
if __name__=="__main__": main()
