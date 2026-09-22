"""一键运行组合与风险自主拓展。"""
import subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent
def main():
    for filename in ["01_run_portfolio_risk_extension.py","02_analyze_portfolio_risk_extension.py","03_validate_and_report_portfolio_risk_extension.py"]:
        print("\n"+"#"*72+f"\n运行：{filename}\n"+"#"*72)
        subprocess.run([sys.executable,str(ROOT/filename)],check=True)
    print("\n[PASS] 组合与风险自主拓展全部完成。")
if __name__=="__main__": main()
