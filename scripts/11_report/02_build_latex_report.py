"""生成图表，以XeLaTeX编译两次，并复制最终研究报告。"""
from pathlib import Path
import shutil,subprocess,sys
ROOT=Path(__file__).resolve().parents[2]
REPORT=ROOT/"report"; BUILD=REPORT/"build"; OUTPUT=ROOT/"outputs"/"report"
def main():
    BUILD.mkdir(parents=True,exist_ok=True); OUTPUT.mkdir(parents=True,exist_ok=True)
    subprocess.run([sys.executable,str(Path(__file__).with_name("01_generate_report_figures.py"))],check=True)
    compiler=shutil.which("xelatex")
    if not compiler: raise RuntimeError("未找到xelatex，请安装MiKTeX或TeX Live并加入PATH。")
    tex=REPORT/"CF2026_Project1_Report.tex"
    command=[compiler,"-interaction=nonstopmode","-halt-on-error",f"-output-directory={BUILD}",str(tex)]
    for _ in range(2): subprocess.run(command,cwd=REPORT,check=True)
    source=BUILD/"CF2026_Project1_Report.pdf"; target=OUTPUT/"CF2026_Project1_Report.pdf"
    shutil.copy2(source,target)
    print(f"[PASS] 最终研究报告：{target}")
if __name__=="__main__": main()
