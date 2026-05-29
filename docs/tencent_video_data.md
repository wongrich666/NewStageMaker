# 腾讯视频平台数据反馈模块使用说明

本文档说明如何导入腾讯视频创作后台数据，并在最终审核报告中查看平台反馈分析。

## 准备原始 Excel

请先从腾讯视频创作后台下载以下 Excel 文件：

- `账号趋势数据-*.xlsx`
- `专辑趋势数据-*.xlsx`
- `剧集趋势数据-*.xlsx`
- `视频趋势数据-*.xlsx`

将下载后的原始 Excel 文件放到：

```text
data/tencent_video_exports/
```

## 运行导入命令

在项目根目录执行：

```bash
python scripts/import_tencent_video_data.py --input data/tencent_video_exports --output data/tencent_video_normalized
```

## 导入输出

导入完成后，会在 `data/tencent_video_normalized/` 下生成以下文件：

- `data/tencent_video_normalized/account_daily_stats.csv`
- `data/tencent_video_normalized/album_daily_stats.csv`
- `data/tencent_video_normalized/episode_stats.csv`
- `data/tencent_video_normalized/video_daily_stats.csv`
- `data/tencent_video_normalized/market_feedback_summary.json`

如果 `market_feedback_summary.json` 存在，最终审核报告会增加：

```text
腾讯视频平台反馈分析
```

## 解读原则

平台数据只作为剧本复盘的辅助依据，不代表严格因果结论。

报告和人工复盘时，应使用“数据提示”“建议复盘”“可能需要关注”等谨慎措辞。不要写成“证明某集一定有问题”“平台数据直接证明剧情缺陷”等绝对因果判断。

建议结合以下信息一起判断：

- 本集标题、封面与实际剧情是否一致
- 前 30 秒是否承接上一集钩子
- 本集核心冲突是否足够明确
- 高互动或高分享集数是否存在可复用的情绪点、反转点、话题点

## 不要提交到 Git

以下目录和文件通常包含平台导出数据、标准化结果或授权信息，不要提交到 Git：

- `data/tencent_video_exports/`
- `data/tencent_video_normalized/`
- `data/tencent_video_auth/`
- `*.xlsx`
