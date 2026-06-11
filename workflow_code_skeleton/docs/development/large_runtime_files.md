# Large Runtime Files

`runtime_data/` 存放运行时快照、导出成品、用户缓存和认证数据库。这里的内容主要服务于业务运行，不适合作为代码审计的主阅读区。

`runtime_archive/` 用于存放已经迁移出去的历史大文件，包括：

- 历史项目快照 JSON
- 历史导出 TXT / DOCX / ZIP / 侧车 JSON
- 拆分后的大型文档目录
- 调试 dump 和日志

开发时请遵循以下约定：

- 代码不要再直接硬编码 `runtime_data/projects/...` 或 `runtime_data/exports/...`。
- 读取历史快照或导出时，优先通过 `app/services/runtime_paths.py` 解析真实文件位置。
- `runtime_archive/` 只做归档，不参与正常 git 提交。
- 如需批量迁移历史运行时文件，使用 `scripts/archive_runtime_artifacts.py`。
- 如需检查当前活跃运行时目录里是否还残留大文件，使用 `scripts/check_large_docs.py`。

对 Codex 或其他代码审计工具来说，建议默认跳过：

- `runtime_data/projects/`
- `runtime_data/exports/`
- `runtime_data/logs/`
- `runtime_data/debug/`
- `runtime_archive/`
- `debug/`
