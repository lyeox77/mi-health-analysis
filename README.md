# 小米运动健康：本地导出与分析包示例

这是独立的下游示例，不是小米官方工具，也不是上游仓库的完整副本。Python 3.11+，仅使用标准库；运行示例不需要账号、Token、网络或模型 API。

## 立即试跑（Windows）

解压到 `D:\mi-health-example`，双击 `run_demo.bat`，或在 PowerShell 中：

```powershell
cd D:\mi-health-example
python health_demo.py --demo --start 2026-10-01 --end 2026-10-14 --out my_demo
```

打开 `my_demo\report.html`。所有演示结果均为固定种子的合成数据，不反映你的健康状况。`example_output` 已附带实际运行的示例结果。

输出：
- `analysis_packet.json`：日期、汇总、每日值、睡眠候选及质量说明。
- `daily.csv`：每日数据，Excel 可打开；空白表示没有可用记录。
- `report.html`：离线表格和数据质量页面，无远程脚本或资源。
- `analysis_request.txt`：提交分析时可直接使用的提示。
- `submit_to_chatgpt.zip`：仅打包 JSON、CSV 与分析提示。也可直接上传 JSON。

每次选择一个新输出目录，程序拒绝覆盖已有输出。

## 接入真实导出

本示例对接 `shkyyy18/mi_fitness_data_bridge` 的 `schema_version=1.0` JSON 导出信封和字段；只处理 sleep、daily_activity、heart_rate。它不读取小米官方下载压缩包、不直接登录小米、不读取凭证或原始数据库。上游接口变更时需复核适配。

先在独立虚拟环境安装和验证上游项目。真实账号配置必须在自己的电脑完成；本示例不提供 Token 获取流程。参阅：
https://github.com/shkyyy18/mi_fitness_data_bridge/blob/main/docs/compatibility.md

已有 bridge 数据库时，以醒来日期 10/01—10/14 为例，导出范围多向前取一天，避免遗漏跨午夜睡眠：

```powershell
mi-fitness-bridge export --format json --start-date 2026-09-30 --end-date 2026-10-14 --output private_raw.json
python health_demo.py --input private_raw.json --start 2026-10-01 --end 2026-10-14 --out real_analysis
```

脚本只从已有导出生成分析包，不会自动把数据发给 ChatGPT。首次对照 App 至少检查三天的睡眠起止、总时长、评分、步数与心率来源。

## 每周处理脚本

`run_weekly.ps1` 使用北京时间，处理截至昨天的七天。传入上游虚拟环境的 Python 路径：

```powershell
.\run_weekly.ps1 -PythonExe D:\mi_fitness_data_bridge\.venv\Scripts\python.exe
```

默认只导出本地缓存。你已经在本机授权且确认同步可用后，加 `-Sync` 可先调用上游同步三个数据集。凭证始终交给上游 keyring 管理。原始导出保存在 `private_runs`，不要分享该目录，只选择 analysis 中的数据包。

在 Windows 任务计划程序中建立每周任务，程序填 `powershell.exe`，参数示例：

```
-NoProfile -File "D:\mi-health-example\run_weekly.ps1" -PythonExe "D:\mi_fitness_data_bridge\.venv\Scripts\python.exe" -Sync
```

需在拥有凭证的同一 Windows 用户下运行；先手动执行并确认脚本策略允许运行。电脑需开机联网。当前会话没有在你的电脑创建任务，也没有进行真实同步。上游可能返回部分成功或空数据；不能仅凭退出码断言同步完整，务必查看报告的覆盖情况和上游同步输出。当前版本未自动解析上游部分成功状态。

## 统计口径和局限

- 固定 UTC+08:00；带偏移的时间戳才接受，不擅自猜测无时区时间。
- 睡眠按醒来日期。同日多个非午睡候选选最长一条并计数，避免简单相加造成多设备重复；分段夜间睡眠可能低估，必须核对。午睡单列，但尚未合并重叠午睡。
- 完全相同记录去重；相互冲突的同日活动记录留空并标记。不同版本睡眠保留为候选，不偷偷合并。
- 未知/缺失值不填零。无效行计数；心率样本数零表示没有可用样本，均值仍为空。
- 心率是样本算术均值，不是按时间加权的全天均值。resting 字段也只是上游明确标注 resting 的样本均值。
- 睡眠阶段暂不统计：上游可能已经把未知编码归为浅睡，下游不能恢复原始语义。
- 不估算睡眠分、不诊断疾病、不推断因果；不在未验证样本上做“健康评分”。
- 输出使用字段白名单，不传递账号、设备 ID、GPS、未知文本和凭证；日期和测量值仍是敏感健康信息，不能称为完全匿名。
- 首版没有长期数据库合并、跨设备融合、自动上传、模型调用或真实账号适配验证；历史存储由上游 SQLite 承担。

## 验证与继续开发

```powershell
python -m unittest -v
```

测试覆盖缺失值、重复记录、醒来日期与时区、活动冲突、多个睡眠候选、无效行、多账号拒绝、提交包脱敏和输出保护。

电脑端 Codex 可在此目录继续：先运行测试；核实上游版本及凭证路径；用最近七天真实数据做 App 对照；再改进未知阶段和多段睡眠、同步失败提示。不要把 `private_raw.json`、数据库或凭证提交到 Git。

上游参考（2026-10-19 检查）：
- https://github.com/shkyyy18/mi_fitness_data_bridge/blob/main/src/mi_fitness_mcp/export.py
- https://github.com/shkyyy18/mi_fitness_data_bridge/blob/main/src/mi_fitness_mcp/models/__init__.py

本包独立编写，不分发上游源码。Windows 批处理和 PowerShell 脚本仅静态检查，尚未在 Windows 主机实测。
