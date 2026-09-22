"""从冻结结果生成研究报告图表。"""
from pathlib import Path
import sys
import duckdb
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[2]; sys.path.insert(0,str(ROOT))
from project_config import DATABASE_DIR
OUT=ROOT/"report"/"figures"; OUT.mkdir(parents=True,exist_ok=True)
plt.rcParams.update({"font.sans-serif":["Microsoft YaHei","SimHei","Arial Unicode MS"],"axes.unicode_minus":False,"figure.dpi":150,"savefig.dpi":220,"font.size":9})
COLORS={"blue":"#2F5597","orange":"#ED7D31","green":"#70AD47","red":"#C00000","gray":"#7F7F7F","light":"#D9E2F3"}

def save(name):
    plt.tight_layout(); plt.savefig(OUT/name,bbox_inches="tight",facecolor="white"); plt.close()

def architecture():
    fig,ax=plt.subplots(figsize=(11,4.2)); ax.axis("off")
    boxes=[("数据\n清洗、标准化与快照",.17,.73),("因子 / 信号\n把可用信息转成指标",.50,.73),("目标组合\n确定资产及目标权重",.83,.73),("评估与解释\n分析收益与风险",.17,.29),("策略净值\n记录收益与风险指标",.50,.29),("回测 / 模拟成交\n模拟成交并计入成本",.83,.29)]
    for label,x,y in boxes:
        ax.text(x,y,label,ha="center",va="center",transform=ax.transAxes,color=COLORS["blue"],fontsize=10,fontweight="bold",bbox=dict(boxstyle="square,pad=.75",fc="#F3F6FA",ec="#C7D3E3",lw=1.2))
    arrows=[((.29,.73),(.38,.73)),((.62,.73),(.71,.73)),((.83,.60),(.83,.42)),((.71,.29),(.62,.29)),((.38,.29),(.29,.29))]
    for start,end in arrows: ax.annotate("",xy=end,xytext=start,xycoords=ax.transAxes,arrowprops=dict(arrowstyle="->",lw=1.8,color=COLORS["blue"]))
    ax.text(.5,.05,"贯穿全流程：YAML配置  ·  DuckDB中间表  ·  CSV证据  ·  SHA-256快照  ·  自动质量检查",ha="center",va="center",transform=ax.transAxes,bbox=dict(boxstyle="round,pad=.38",fc="#F2F2F2",ec="#BFBFBF"),fontsize=8.5)
    save("01_research_architecture.png")

def factor_diagnostics():
    ic=pd.read_csv(ROOT/"outputs"/"evaluation"/"02_ic_summary.csv")
    groups=pd.read_csv(ROOT/"outputs"/"evaluation"/"03_group_return_summary.csv")
    selected=["low_volatility_20","reversal_5","amihud_illiquidity_20"]
    names={"low_volatility_20":"20日低波动","reversal_5":"5日反转","amihud_illiquidity_20":"Amihud非流动性"}
    subset=ic[(ic.factor.isin(selected))&(ic.horizon==5)&(ic.sample_period.isin(["train_2020_2023","validation_2024","test_2025"]))].copy()
    subset["period"]=subset.sample_period.map({"train_2020_2023":"训练期","validation_2024":"验证期","test_2025":"测试期"})
    fig,axes=plt.subplots(1,2,figsize=(11,4.1))
    x=np.arange(3); width=.24
    for j,factor in enumerate(selected):
        vals=[subset[(subset.factor==factor)&(subset.period==p)].mean_rank_ic.iloc[0] for p in ["训练期","验证期","测试期"]]
        axes[0].bar(x+(j-1)*width,vals,width,label=names[factor])
    axes[0].axhline(0,color="black",lw=.7); axes[0].set_xticks(x,["训练期\n2020–2023","验证期\n2024","测试期\n2025"]); axes[0].set_ylabel("5日 Rank IC均值"); axes[0].set_title("入选因子的跨阶段排序能力"); axes[0].legend(fontsize=8); axes[0].grid(axis="y",alpha=.25)
    g=groups[(groups.factor.isin(selected))&(groups.horizon==5)&(groups.sample_period=="train_2020_2023")]
    for factor in selected:
        part=g[g.factor==factor].sort_values("factor_group")
        axes[1].plot(part.factor_group,part.mean_group_return*100,marker="o",lw=2,label=names[factor])
    axes[1].set_xticks(range(1,6)); axes[1].set_xlabel("因子五分组（1低，5高）"); axes[1].set_ylabel("平均5日未来收益（%）"); axes[1].set_title("训练期五分组收益"); axes[1].legend(fontsize=8); axes[1].grid(alpha=.25)
    save("02_factor_diagnostics.png")

def nav_drawdown():
    con=duckdb.connect(str(DATABASE_DIR/"cf2026_project1.duckdb"),read_only=True)
    weekly=con.execute("SELECT date,nav FROM experiment_weekly_backtest_daily WHERE strategy='multi_equal_3' ORDER BY date").fetchdf()
    monthly=con.execute("SELECT date,nav FROM experiment_monthly_backtest_daily WHERE strategy='multi_equal_3' ORDER BY date").fetchdf(); con.close()
    fig,axes=plt.subplots(2,1,figsize=(11,6),sharex=True,gridspec_kw={"height_ratios":[2,1]})
    for frame,label,color in [(weekly,"周频",COLORS["orange"]),(monthly,"月频",COLORS["blue"])]:
        frame["date"]=pd.to_datetime(frame.date); frame["net_value"]=frame.nav/1_000_000
        frame["drawdown"]=frame.nav/frame.nav.cummax()-1
        axes[0].plot(frame.date,frame.net_value,label=label,color=color,lw=1.8)
        axes[1].plot(frame.date,frame.drawdown*100,label=label,color=color,lw=1.3)
    axes[0].set_ylabel("累计净值"); axes[0].set_title("三因子策略净值：周频与月频"); axes[0].legend(); axes[0].grid(alpha=.25)
    axes[1].set_ylabel("回撤（%）"); axes[1].set_xlabel("日期"); axes[1].grid(alpha=.25); axes[1].xaxis.set_major_locator(mdates.YearLocator()); axes[1].xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    save("03_nav_and_drawdown.png")

def cost_extension():
    compare=pd.read_csv(ROOT/"outputs"/"backtest"/"weekly_vs_monthly"/"02_multi_factor_comparison.csv")
    ext=pd.read_csv(ROOT/"outputs"/"backtest"/"portfolio_risk_extension"/"02_key_results.csv")
    gross=pd.read_csv(ROOT/"outputs"/"backtest"/"gross_net"/"01_gross_net_summary_same_path.csv")
    fig,axes=plt.subplots(1,2,figsize=(11,4.3))
    gm=gross[(gross.strategy=="multi_equal_3")&(gross.experiment.isin(["weekly","monthly"]))]
    labels=["周频","月频"]; net=[gm[gm.experiment==x].net_total_return.iloc[0]*100 for x in ["weekly","monthly"]]; grossv=[gm[gm.experiment==x].gross_total_return_same_path.iloc[0]*100 for x in ["weekly","monthly"]]
    x=np.arange(2); axes[0].bar(x-.18,grossv,.36,label="毛收益",color=COLORS["light"],edgecolor=COLORS["blue"]); axes[0].bar(x+.18,net,.36,label="净收益",color=COLORS["blue"])
    for i in range(2): axes[0].text(i,(grossv[i]+net[i])/2,f"成本拖累\n{grossv[i]-net[i]:.1f}pp",ha="center",va="center",fontsize=8)
    axes[0].set_xticks(x,labels); axes[0].set_ylabel("累计收益（%）"); axes[0].set_title("同成交路径毛净收益与成本拖累"); axes[0].legend(); axes[0].grid(axis="y",alpha=.2)
    order=["monthly_equal","monthly_vol_target_10","monthly_vol_target_15","monthly_vol_target_20","monthly_risk_parity","monthly_risk_parity_cap_08","monthly_risk_parity_cap_08_vol_15"]
    short={"monthly_equal":"等权","monthly_vol_target_10":"波动目标10%","monthly_vol_target_15":"波动目标15%","monthly_vol_target_20":"波动目标20%","monthly_risk_parity":"ERC","monthly_risk_parity_cap_08":"ERC+上限","monthly_risk_parity_cap_08_vol_15":"ERC+上限+15%"}
    part=ext.set_index("strategy").loc[order].reset_index(); colors=[COLORS["gray"],COLORS["green"],COLORS["blue"],"#5B9BD5",COLORS["orange"],"#FFC000",COLORS["red"]]
    axes[1].scatter(part.annualized_volatility*100,part.annualized_return*100,s=90,c=colors)
    for row in part.itertuples(): axes[1].annotate(short[row.strategy],(row.annualized_volatility*100,row.annualized_return*100),xytext=(4,3),textcoords="offset points",fontsize=7.5)
    axes[1].set_xlabel("年化波动率（%）"); axes[1].set_ylabel("年化收益率（%）"); axes[1].set_title("风险拓展：收益—风险位置"); axes[1].grid(alpha=.25)
    save("04_cost_and_extension.png")

if __name__=="__main__":
    architecture(); factor_diagnostics(); nav_drawdown(); cost_extension(); print("[PASS] 报告图表已生成。")
