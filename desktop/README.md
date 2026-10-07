# TDL Desktop

Telegram Media Downloader Enhanced 的 Tauri 2 桌面客户端。界面参考 EcoPaste 的偏好设置风格，
把原来的 `tdl.exe` 作为 sidecar 引擎托管起来，提供可视化配置、任务管理和下载数据看板。

## 功能

| 页面 | 内容 |
| --- | --- |
| 仪表盘 · 实时 | 当前速度与 15 分钟速度曲线、进行中下载、队列、本次运行结果、Clash 切换记录 |
| 仪表盘 · 统计 | 今天 / 7 / 30 / 90 天的每日下载量、频道排行、媒体类型、活跃时段、结果分布、下载记录 |
| 任务 | 进行中任务（可停止）、新建下载任务（等同机器人 `/download`，含过滤表达式检查）、待恢复、已结束 |
| 下载 / 频道 / 网络 / 上传 | config.yaml 的全部常用参数；频道列表编辑；Clash 节点测速与手动切换；登录会话管理 |
| 日志 | 引擎实时输出（级别过滤、搜索、向引擎发送输入）与 `log/tdl.log` 文件查看 |
| 设置 | 主题、托盘、开机自启、通知、按时间段下载、磁盘空间保护、工作目录、引擎路径、存储清理、配置备份与恢复、config.yaml 源码编辑 |

其他：全局“搜索配置项”、首次运行向导、Telegram 登录弹窗（手机号 / 验证码 / 两步验证）、
系统托盘（启动/停止/暂停/继续）、任务完成与引擎异常通知、单实例、关闭时优雅停止引擎。

## 架构

```
desktop/
  src/                React 19 + TypeScript 前端（无 UI 框架，自绘 EcoPaste 风格组件与 SVG 图表）
    lib/schema.ts     设置项注册表：驱动设置页面与全局搜索
    lib/mock.ts       浏览器预览用的模拟后端（npm run dev 时自动启用）
  src-tauri/src/
    engine.rs         启动/停止 tdl.exe、捕获日志、识别登录提示、轮询引擎 API、自动暂停
    config.rs         config.yaml 三方合并保存、备份与恢复
    stats.rs          下载历史统计、存储占用、待恢复任务、日志文件
    clash.rs          Clash / mihomo 控制器
    tray.rs, job.rs   托盘；Windows Job Object（桌面端崩溃时连带结束引擎）
```

引擎侧（仓库根目录）为桌面模式增加了：

- `TDL_BASE_PATH`：指定工作目录（config.yaml、sessions、temp、log 所在目录）。
- `TDL_DESKTOP=1` + `TDL_DESKTOP_TOKEN`：在现有 Flask 服务上注册受令牌保护的 `/api/desktop/*`
  （状态、暂停/继续、新建/停止任务、过滤表达式检查、优雅退出），并在所有频道完成后保持运行。
- 每个完成的文件追加到 `stats/history-YYYY-MM.jsonl`，供统计页使用。

保存配置时只写入用户改动过的顶层键，并保留引擎运行期间推进的 `last_read_message_id`；
引擎运行中保存会自动“停止 → 写入 → 启动”，下载从断点续传。

## 开发

需要 Node 20+、Rust（MSVC 工具链）和 VS C++ 生成工具。

```powershell
cd desktop
npm install
npm run dev          # 仅前端，浏览器打开 http://localhost:1420，使用模拟数据
npx tauri dev        # 完整桌面应用
cd src-tauri; cargo test
```

开发时可在「设置 → 引擎 → 引擎程序」中指定 `media_downloader.py`，直接运行源码版引擎。

## 构建绿色版

```powershell
powershell -ExecutionPolicy Bypass -File desktop\scripts\build.ps1
```

脚本先用 PyInstaller 构建引擎并放到 `src-tauri/binaries/tdl-x86_64-pc-windows-msvc.exe`，
再执行 `tauri build --no-bundle`，最后在 `desktop/release/` 生成文件夹和 zip：

```
TDL-Desktop-v1.0.0-portable-x64/
  TDL Desktop.exe
  tdl.exe          下载引擎
  portable.txt     绿色模式标记
```

`portable.txt` 存在时，工作目录就是程序所在文件夹，桌面端设置与 WebView2 缓存保存在
`desktop-data/`，不写入 AppData（仅在需要显示系统通知时于 `HKCU\Software\Classes\AppUserModelId`
登记应用名称，这是 Windows 显示通知的要求）。

需要安装包时加 `-Installer` 参数，生成 NSIS 安装程序。
