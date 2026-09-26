# CF2026 Project 1

本项目搭建了一个可复现的A股多因子研究平台，正式主线为动态沪深主板三因子策略，并提供逐日成交回测、周频与月频对照、波动率目标拓展和交互式研究工作台。研究期为2020-01-01至2025-12-31；实际下载区间为2019-10-01至2026-01-31，用于滚动因子和未来收益标签。

## 在线成果

- **交互式研究工作台：** [https://2248386016-cmyk.github.io/CF2026_Project1/](https://2248386016-cmyk.github.io/CF2026_Project1/)
- **最终研究报告 PDF：** [下载或在线查看](outputs/report/CF2026_Project1_Report.pdf)
- **冻结版本：** `cf2026-project1-final-v6`

网页默认展示月频三因子Top 20，可以切换周频对照、15%波动率目标及沪深300机器学习拓展，并查看逐日净值、回撤、成交成本和因子诊断。网页直接读取冻结审计结果，不在浏览器中重新计算绩效。

![CF2026量化研究工作台预览](docs/web-workbench.png)

## 项目结构

```text
_project1/
├─ README.md
├─ requirements.txt
├─ project_config.py
├─ download_utils.py
├─ scripts/
│  ├─ 01_tests/
│  │  ├─ 01_test_token_connection.py
│  │  ├─ 02_test_daily_data.py
│  │  ├─ 03_test_adjustment_factor.py
│  │  ├─ 04_test_trade_calendar.py
│  │  ├─ 05_test_stock_universe.py
│  │  ├─ 06_test_namechange_access.py
│  │  └─ 07_run_all_tests.py
│  ├─ 02_download/
│     ├─ 01_download_reference_data.py
│     ├─ 02_download_core_market_data.py
│     ├─ 03_download_optional_constraints.py
│     ├─ 04_validate_raw_downloads.py
│     ├─ 05_build_research_database.py
│     ├─ 06_run_download_pipeline.py
│     └─ 07_download_mainboard_namechange.py
│  └─ 03_processing/
│     ├─ 01_import_optional_data.py
│     ├─ 02_build_historical_st_status.py
│     ├─ 03_clean_market_data.py
│     ├─ 04_validate_clean_data.py
│     └─ 05_run_processing_pipeline.py
│  └─ 04_universe/
│     ├─ 01_build_dynamic_universe.py
│     ├─ 02_validate_universe_coverage.py
│     └─ 03_run_universe_pipeline.py
│  └─ 05_factors/
│     ├─ 01_build_factor_panel.py
│     ├─ 02_calculate_raw_factors.py
│     ├─ 03_preprocess_factors.py
│     ├─ 04_validate_and_compare_factors.py
│     └─ 05_run_factor_pipeline.py
│  └─ 06_evaluation/
│     ├─ 01_build_forward_returns.py
│     ├─ 02_calculate_ic.py
│     ├─ 03_calculate_group_returns.py
│     ├─ 04_select_top_factors.py
│     ├─ 05_validate_evaluation.py
│     └─ 06_run_evaluation_pipeline.py
│  └─ 07_backtest/
│     ├─ 01_build_strategy_signals.py
│     ├─ 02_run_portfolio_backtest.py
│     ├─ 03_analyze_backtest.py
│     ├─ 04_validate_backtest.py
│     ├─ 05_assess_strategy_stability.py
│     └─ 06_run_backtest_pipeline.py
│  └─ 08_experiments/
│     ├─ 01_run_weekly_vs_monthly.py
│     ├─ 02_compare_weekly_vs_monthly.py
│     ├─ 03_validate_weekly_vs_monthly.py
│     └─ 04_run_weekly_vs_monthly_experiment.py
│  └─ 09_extensions/
│     ├─ 01_run_portfolio_risk_extension.py
│     ├─ 02_analyze_portfolio_risk_extension.py
│     ├─ 03_validate_and_report_portfolio_risk_extension.py
│     └─ 04_run_portfolio_risk_extension.py
│  └─ 10_reproducibility/
│     ├─ 01_generate_gross_net_comparison.py
│     ├─ 02_build_shareable_sample.py
│     ├─ 03_generate_final_reproduction_manifest.py
│     └─ 04_run_final_reproduction_package.py
│  └─ 11_report/
│     ├─ 01_generate_report_figures.py
│     └─ 02_build_latex_report.py
├─ data/
│  ├─ raw/
│  ├─ processed/
│  └─ database/
├─ logs/
└─ outputs/
```

## 环境配置

Python 解释器：

```text
D:\Users\Q\anaconda3\envs\research\python.exe
```

安装依赖：

```powershell
D:\Users\Q\anaconda3\envs\research\python.exe -m pip install -r C:\Users\Q\Desktop\CF2026\_project1\requirements.txt
```

在 PyCharm 的 `Run -> Edit Configurations -> Environment variables` 中添加：

```text
TUSHARE_TOKEN=你的真实Token
```

不要把真实 Token 写入代码或提交到 Git。

## 统一入口

根目录 `main.py` 是正式命令行入口。默认从已经冻结的本地数据快照开始，不会重新下载或改变研究样本：

```powershell
python main.py validate       # 数据接口与基础检查
python main.py core           # 清洗、资产池、因子、评价和正式回测
python main.py experiments    # 周/月频对照、风险拓展、模型验证和网页数据
python main.py report         # 重新生成PDF报告
python main.py reproduce      # 更新小样本、环境与SHA-256清单
python main.py all            # 按上述顺序完整重建
```

数据下载仍使用 `scripts/02_download/06_run_download_pipeline.py` 单独执行，因为下载需要 Tushare Token，并会改变冻结快照。最终封版时应先提交源码和报告，再运行 `python main.py reproduce`，确认元数据中的 Git commit 与当前 `HEAD` 一致。

## 运行测试

在 PyCharm 中运行：

```text
scripts/01_tests/07_run_all_tests.py
```

它会依次运行测试目录中的 01-06。测试输出保存在 `outputs/test_results/`。其中 06 用一只股票测试 `namechange`（股票曾用名）接口权限，不会批量下载。

## 下载核心数据

在 PyCharm 中运行：

```text
scripts/02_download/06_run_download_pipeline.py
```

执行顺序：

```text
01 下载参考数据
02 下载 daily 和 adj_factor
04 验证原始数据
05 建立 DuckDB
```

下载支持断点续传，中断后重新运行即可。历史 ST、停牌和涨跌停接口有额外积分要求，因此 `03_download_optional_constraints.py` 不包含在核心流水线内，可单独运行。

确定研究沪深主板后，可单独运行 `02_download/07_download_mainboard_namechange.py`，按股票下载历史名称，为构造每日 ST 状态提供数据。该脚本只下载与 2020-2025 研究期有交集的沪深主板股票，并支持断点续传。

最终数据库位置：

```text
data/database/cf2026_project1.duckdb
```

## Ridge + LightGBM 动态沪深300基准

新增的模型基准使用历史沪深300成分股、10 个行业/市值中性化因子和严格的时间序列划分：2020–2022 训练、2023–2024 验证、2025 样本外测试。原始输入按接口缓存，正式结果使用独立 `run_id`，不会替换原有 `strategy_targets` 或 `backtest_daily`。

```powershell
python scripts/08_experiments/05_download_csi300_model_inputs.py
python scripts/08_experiments/06_run_ridge_lightgbm_baseline.py
python scripts/08_experiments/07_validate_ridge_lightgbm_baseline.py
```

配置见 `config/model_baseline.yaml`，方法、结果文件与当前限制见 `outputs/backtest/ridge_lightgbm_csi300_v1/README.md`。下载脚本只从环境变量读取 `TUSHARE_TOKEN`，不会保存 Token。

最终报告按照平台执行顺序展开：数据、因子/信号、目标组合、模拟成交、策略净值、评价解释。周频与月频作为独立对照实验；波动率目标、ERC、权重上限、动态沪深300机器学习、Qlib和研究工作台统一放在“拓展实验”中分点报告。机器学习不作为基础三因子结论成立的前提，其数字仍直接读取 `outputs/backtest/ridge_lightgbm_csi300_v1/regime_overlay_metrics.csv`。

生成最终报告：

```powershell
python scripts/11_report/02_build_latex_report.py
```

报告同时写入仓库证据目录和 `C:\CodexWork\CF2026_Deliverables\final\CF2026_Project1_Final_Report.pdf`，最终提交文件不放桌面目录。

## 清洗数据

可选数据下载完成后，在 PyCharm 中运行：

```text
scripts/03_processing/05_run_processing_pipeline.py
```

它会把停牌、涨跌停和历史名称数据导入 DuckDB，根据名称生效区间构造每日 ST 状态，重新生成排除历史 ST 的 `market_data_clean` 表，并输出清洗质量报告。原始 Parquet 文件不会被修改。

流水线还会运行 `06_generate_data_audit_package.py`，在 `outputs/data_audit/` 生成数据字典、全部原始文件 SHA-256 快照、Python/依赖环境快照和清洗前后互斥原因对账表。Tushare `daily` 中 `vol` 单位为手（1手=100股），`amount` 单位为千元。

## 构建和验证动态资产池

清洗完成后，在 PyCharm 中运行：

```text
scripts/04_universe/03_run_universe_pipeline.py
```

脚本按每个交易日、上市/退市日期和历史 ST 状态构建沪深主板 A 股动态资产池。数据库表为 `research_universe_daily`，入池视图为 `research_universe_members`。覆盖率报告保存在 `outputs/universe/`，缺失行情会区分已知停牌和无法解释的缺失，不会静默删除。

## 构建候选因子

动态资产池验证后，在 PyCharm 中运行：

```text
scripts/05_factors/05_run_factor_pipeline.py
```

因子卡和参数分别保存在 `config/factor_cards.yaml` 和 `config/factor_config.yaml`。流水线构建7个候选因子，保存原始值、缩尾值、Z-score和百分位排名，并输出覆盖率、描述统计、截面 Rank 相关性和高分组重合率报告。

## 因子评价与择优

因子构建后，在 PyCharm 中运行：

```text
scripts/06_evaluation/06_run_evaluation_pipeline.py
```

该流水线从 T+1 开始构建1/5/20日未来收益标签，计算 IC、Rank IC、五分组收益和高低组价差。选择仅使用2020-2023研究期和2024验证期，2025只用于选择后的样本外报告。

## 正式策略回测

回测参数集中在 `config/backtest_config.yaml`，包括研究日期、信号滞后、调仓频率、持仓数、权重、初始资金、交易限制、费率、退市回收率、年化天数和无风险收益率。

在 PyCharm 中运行：

```text
scripts/07_backtest/06_run_backtest_pipeline.py
```

回测包含3个单因子策略和1个等权多因子策略。每周第一个交易日开盘调仓，使用前一交易日收盘后因子；涨停不买、跌停不卖、停牌不交易，未成交持仓保留。买入费率0.03%，卖出费率0.13%。对退市后仍未能卖出的持仓采用保守的0回收率核销，避免以最后价格长期虚增净值。

## 周频 vs 月频对照实验

运行：

```text
scripts/08_experiments/04_run_weekly_vs_monthly_experiment.py
```

两组使用同一数据快照、样本区间、三因子、前20名等权持仓、成交约束和交易成本，唯一改变调仓频率。证据包保存在 `outputs/backtest/weekly_vs_monthly/`。

## 组合与风险自主拓展

运行：

```text
scripts/09_extensions/04_run_portfolio_risk_extension.py
```

拓展固定月频三因子 Top 20 信号、样本和成本口径，比较等权、10%/15%/20%波动率目标、完整协方差矩阵的ERC风险平价、8%目标权重上限及组合方案。风险估计只使用形成日及以前60个交易日，波动率目标不使用杠杆，未投资部分作为零收益现金。结果与自动检查保存在 `outputs/backtest/portfolio_risk_extension/`。

8%是调仓时目标权重上限，并非每日实际持仓权重上限；价格变化或交易受限可能使实际权重暂时超过8%。当前结果推荐15%波动率目标作为收益与风险较均衡的方案，10%和20%用于参数敏感性，风险平价的未改善结果同样保留。

## 毛收益与净收益口径

项目采用同成交路径费用归因：沿用净回测的实际成交日期、价格和数量，仅将累计已支付交易费用作为未投资现金加回，得到毛净值，不重新下单。因此毛净差异只归因于显式交易费，不混入另一条成交路径。该口径不包含冲击成本、滑点、整手限制和现金利息。

生成毛净收益、小样本和最终复现清单：

```text
scripts/10_reproducibility/04_run_final_reproduction_package.py
```

## 可分享小样本与最终复现包

`outputs/reproducibility/shareable_sample/` 包含固定10只股票、2025-01-02至2025-03-31的原始行情、清洗行情、动态资产池、因子长表和未来收益标签。该样本无需Tushare Token即可检查字段、唯一键和数据结构，但不能代表完整样本绩效。

`outputs/reproducibility/` 还包含：

- 源代码、配置和文档的SHA-256清单；
- 研究证据输出的SHA-256清单；
- DuckDB数据库及原始数据快照清单的校验值；
- Python、操作系统、Git状态和生成时间；
- 原始文件逐项校验继续使用 `outputs/data_audit/06_raw_snapshot_manifest_sha256.csv`。

若项目目录不是Git仓库，`git_commit`会记录为空；此时以逐文件SHA-256清单作为代码版本标识。

## LaTeX研究报告

报告源文件为 `report/CF2026_Project1_Report.tex`，对照实验和自主拓展分别成章。报告图表均从冻结的CSV和DuckDB结果生成，包括研究架构、因子诊断、净值与回撤、同路径成本归因及风险拓展比较。

已安装XeLaTeX时运行：

```text
scripts/11_report/02_build_latex_report.py
```

脚本会重新生成图表、连续编译两次，并输出：

```text
outputs/report/CF2026_Project1_Report.pdf
```
