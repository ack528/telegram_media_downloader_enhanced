# v3.2.2

本次更新修复 `v3.2.1` 双击启动时报错的问题，并清理上一版 Web 控制台实验方案。

## 修复内容

- 修复 GUI 无控制台模式下启动报错：
  `AttributeError: 'NoneType' object has no attribute 'write'`。
- 原因是 PLY 在构建过滤器 parser 时尝试写入 debug 输出；GUI 打包模式下标准错误流可能为空。
- 现在 parser 构建时禁用 debug/table 输出并使用空日志器，适配无控制台 exe。
- 增加回归测试，模拟 `sys.stderr=None` 的 GUI 环境。

## UI 调整

- 保留 Tkinter/ttk 原生桌面 UI：双击 `tdl.exe` 直接打开窗口。
- UI 会显示启动准备过程、实时文件下载、机器人任务、运行日志和常用 config 配置。
- 清理 `v3.2.0` 的现代 Web dashboard 实验方案，恢复原始备用 Web 页面，避免两套 UI 逻辑混杂。

## 打包说明

- exe 仍为无控制台窗口模式。
- 已重新打包并上传 Release 资产。
