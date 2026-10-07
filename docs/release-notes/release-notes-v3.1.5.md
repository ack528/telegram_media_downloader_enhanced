## 更新内容

- 在机器人实时下载进度通知中新增 `Clash 下载速度`。
- 在机器人实时下载进度通知中新增 `软件总下载速度`。
- Clash 速度通过外部控制器 `/traffic` 接口读取，并带短缓存，避免频繁请求影响机器人状态更新。
- 当 Clash 未启用、未配置或接口不可用时，状态消息显示 `不可用`。

## 使用说明

- Clash 速度需要启用 Clash 外部控制器，并在 `config.yaml` 的 `clash.controller` 和 `clash.secret` 中配置正确。
- 更新软件时只替换 `tdl.exe`，保留 `config.yaml`、`data.yaml`、`sessions`、`temp`、`log` 文件夹。
