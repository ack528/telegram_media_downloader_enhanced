## 更新内容

- 修复 GitHub Release 中文说明乱码问题，发布脚本改为从 UTF-8 文件读取说明并用 UTF-8 JSON 上传。
- Python 控制台默认只显示下载成功、警告和错误信息。
- 降低高频诊断日志级别，任务入队、worker 接单、跳过已存在文件等细节默认不再刷屏。
- 修复新版发布脚本创建 Release 时的 JSON 请求体问题。
- 如需深度排查，可在 `config.yaml` 中设置 `log_level: DEBUG` 查看完整诊断日志。

## 使用说明

- 更新软件时只替换 `tdl.exe`。
- 继续保留 `config.yaml`、`data.yaml`、`sessions`、`temp`、`log` 文件夹。
