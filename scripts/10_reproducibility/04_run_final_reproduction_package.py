"""一键生成毛净收益归因、小样本和最终复现清单。"""
import subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent
def main():
    for filename in ["01_generate_gross_net_comparison.py","02_build_shareable_sample.py","03_generate_final_reproduction_manifest.py"]:
        print("\n"+"#"*72+f"\n运行：{filename}\n"+"#"*72)
        subprocess.run([sys.executable,str(ROOT/filename)],check=True)
    print("\n[PASS] 最终复现包全部生成。")
if __name__=="__main__": main()
