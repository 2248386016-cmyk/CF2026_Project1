# 可分享离线小样本

- 固定区间：2025-01-02 至 2025-03-31
- 固定资产数：10
- 资产：000001.SZ, 000002.SZ, 000004.SZ, 000006.SZ, 000007.SZ, 000008.SZ, 000009.SZ, 000010.SZ, 000011.SZ, 000012.SZ
- 来源：正式数据库导出的原始行情、清洗行情、动态资产池、因子值和未来收益标签。
- 用途：无需Tushare Token即可检查字段、唯一键、清洗口径、因子长表和标签结构。
- 限制：这是教学复现小样本，不用于代表全样本绩效，也不能复现完整策略净值。
- 完整数据获取方式见项目README；每个文件的行数和SHA-256见sample_manifest_sha256.csv。

快速读取：
```python
import pandas as pd
market = pd.read_csv('sample_clean_market.csv', parse_dates=['trade_date'])
factors = pd.read_csv('sample_factor_values.csv', parse_dates=['date'])
assert market.duplicated(['trade_date', 'ts_code']).sum() == 0
assert factors.duplicated(['date', 'asset', 'factor']).sum() == 0
```
