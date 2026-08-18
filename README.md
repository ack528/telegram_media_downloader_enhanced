# Telegram Media Downloader Enhanced

面向 Windows 长时间运行场景的 Telegram 媒体下载增强版。项目重点解决大批量任务中的断点恢复、机器人任务管理、临时文件堆积、断网保护和单文件 EXE 部署问题。

[![最新版本](https://img.shields.io/github/v/release/ack528/telegram_media_downloader_enhanced?display_name=tag&label=release)](https://github.com/ack528/telegram_media_downloader_enhanced/releases/latest)
[![测试](https://github.com/ack528/telegram_media_downloader_enhanced/actions/workflows/unittest.yml/badge.svg)](https://github.com/ack528/telegram_media_downloader_enhanced/actions)
[![许可证](https://img.shields.io/github/license/ack528/telegram_media_downloader_enhanced)](LICENSE)
![平台](https://img.shields.io/badge/platform-Windows-0078D4)

## 项目说明

本项目基于 [tangyoha/telegram_media_downloader](https://github.com/tangyoha/telegram_media_downloader) 继续开发，其上游源自 [Dineshkarthik/telegram_media_downloader](https://github.com/Dineshkarthik/telegram_media_downloader)。感谢原作者和贡献者提供的基础实现；本项目保留 MIT 许可证要求的原始版权声明，以下内容主要介绍增强版的改进。

## 相较原项目的主要提升

### 更可靠的下载与断点恢复

- 下载中断后保留可续传的 `.temp` 文件，并持久化待处理消息 ID。
- 恢复任务时同时校验聊天、范围和扫描状态，避免软件重启后恢复成另一个历史任务。
- 状态文件采用原子写入，降低异常退出或断电造成 YAML 损坏的概率。
- 增加下载停滞检测、指数退避、消息重新获取及协议异常重试。
- Windows 长路径场景预留临时文件后缀空间，减少大文件下载到后期才因路径过长失败的问题。

### 断网保护与失败跳过互不冲突

- 先判断是否真正断网；断网时等待网络恢复，不消耗单个视频的失败重试次数，也不删除可续传临时文件。
- 网络正常但同一媒体持续失败时，达到重试上限后清理对应临时文件、记录跳过并继续下一个媒体。
- 停止任务时可以立即打断断网等待，不会因为网络检测而导致 `/stop` 失效。
- Telegram 协议解析错误与真实网络中断分开处理，避免错误分类造成无限等待。
- 可选 Clash 控制器联动：持续低速时切换节点，并设置检测周期和冷却时间。

### 机器人任务恢复与控制

- 持久化原始 `/download` 命令的消息 ID、文本、链接和下载范围。
- 软件重启后，恢复通知继续引用最初发送的下载命令；原消息已删除时提供可读的备用说明。
- 恢复中的任务会重新注册到任务列表，因此可以在 `/stop` 菜单中看到并停止。
- 已停止任务会从恢复状态中清除，不会在下次启动时再次自动恢复。
- 同一聊天内阻止互相冲突的并发任务，避免状态相互覆盖。
- 机器人状态通知只展示最近 5 个仍在活跃下载的视频；已完成、中断或跳过的条目会及时移除。
- Telegram 消息长度按 UTF-16 安全限制，避免进度通知过长而发送失败。

### 临时目录和长期运行治理

- 正常完成、明确跳过、永久失败和人工停止分别执行对应的状态清理。
- 永久失败的视频不会无限留在队列和 `temp` 目录中。
- 活跃下载、失败状态、Web 历史记录均有边界，避免运行时间越长占用越多内存。
- 心跳和进度状态只保留当前有效任务，避免机器人通知不断堆积旧视频。

### 转发、上传和 Web 管理修复

- 修复媒体组、无效转发过滤器、上传缓存和上传完成后的删除顺序。
- rclone 改为可检查退出状态的子进程执行；只有确认上传成功后才删除本地文件。
- 修复 Aligo 在线程执行器中的调用问题。
- Web 状态使用线程安全快照和标准 JSON 输出，处理零大小文件等边界情况。
- Web 会话密钥不再使用固定默认值，降低默认部署的安全风险。

### Windows 单文件版本

- 提供可直接运行的单文件 EXE，运行目录、配置、日志、会话和临时文件路径在 PyInstaller 环境下保持一致。
- 修复 Windows 非法文件名、保留名称、末尾空格/句点和控制台快速编辑导致的暂停问题。
- 升级时只需替换 EXE，可继续保留 `config.yaml`、`data.yaml`、会话、日志和未完成的临时文件。

## 核心功能

- 按频道、群组或消息范围批量下载 Telegram 媒体。
- 支持音频、文档、图片、视频、语音和视频消息。
- 支持机器人下发下载任务、查看状态、停止任务和重启恢复。
- 支持过滤器、自定义目录结构、文件名模板、转发和上传到网盘。
- 支持 Web 状态页面、Clash 低速切换和断点续传。

## Windows 快速开始

1. 从 [最新 Release](https://github.com/ack528/telegram_media_downloader_enhanced/releases/latest) 下载 `tdl-v3.1.18-fixed.exe`。
2. 将 EXE 放到一个固定目录，并在同一目录准备 `config.yaml`。
3. 首次运行后按提示完成 Telegram 登录；`*.session` 文件会保存在程序目录。
4. 后续升级只替换 EXE，不要删除 `config.yaml`、`data.yaml`、`sessions`、`temp` 和下载目录。

最小配置示例：

```yaml
api_id: your_api_id
api_hash: your_api_hash
bot_token: your_bot_token
language: ZH

chat:
  - chat_id: telegram_chat_id
    last_read_message_id: 0

media_types:
  - audio
  - photo
  - video
  - document
  - voice
  - video_note

file_formats:
  audio: [all]
  document: [all]
  video: [all]

save_path: D:\TelegramDownloads
file_path_prefix:
  - chat_title
  - media_datetime

allowed_user_ids:
  - me

download_stall_timeout: 90
history_fetch_timeout: 60
history_fetch_retries: 3
scan_prefetch_limit: 5

clash:
  enabled: false
  controller: http://127.0.0.1:9097
  secret: ""
  selector: ""
  low_speed_kb: 100
  low_speed_seconds: 60
  switch_cooldown_seconds: 300
  timeout_ms: 5000
  test_url: https://www.gstatic.com/generate_204
```

`api_id` 和 `api_hash` 可在 [Telegram API](https://my.telegram.org/apps) 获取。请勿把真实的 `api_hash`、机器人 Token、会话文件或含私人频道信息的配置提交到公开仓库。

## 机器人常用命令

- `/download`：查看下载用法或创建下载任务。
- `/stop`：列出当前任务并停止指定任务。
- `/get_info`：获取聊天或消息信息。
- `/forward`：创建转发任务。
- `/listen_forward`：监听并转发新消息。
- `/help`：查看机器人帮助。

下载范围示例：

```text
/download https://t.me/example_channel 1000 2000
```

任务恢复时会保存并引用这条原始命令。机器人消息被删除时，恢复通知会显示保存下来的原始命令文本。

## 失败处理规则

处理顺序固定为：

1. 检测是否断网。
2. 断网时保留临时文件并等待恢复。
3. 网络在线时执行媒体级重试和退避。
4. 达到永久失败上限后清理该媒体的临时状态，标记跳过并继续下一个。
5. 收到 `/stop` 时，无论正在下载、重试还是等待网络，都停止并清除恢复标记。

这样可以避免断网期间误删可续传文件，也能防止单个损坏或不可访问的视频无限阻塞整个队列。

## 从源码运行与构建

建议使用 Python 3.11：

```powershell
git clone https://github.com/ack528/telegram_media_downloader_enhanced.git
cd telegram_media_downloader_enhanced
python -m pip install -r requirements.txt
python media_downloader.py
```

运行测试：

```powershell
python -m pytest -q
```

构建 Windows 单文件：

```powershell
python -m pip install pyinstaller
python -m PyInstaller --clean --noconfirm media_downloader.spec
```

生成文件位于 `dist\tdl.exe`。

## 问题反馈

提交问题前，请准备：

- 软件版本和运行方式（源码或 EXE）。
- 已脱敏的相关日志。
- 任务链接类型和下载范围。
- 问题发生时是否断网、切换代理或重启软件。
- `temp` 和任务状态的现象说明。

请通过 [Issues](https://github.com/ack528/telegram_media_downloader_enhanced/issues) 反馈问题，讨论和建议可发布到 [Discussions](https://github.com/ack528/telegram_media_downloader_enhanced/discussions)。

## 许可证与致谢

本项目使用 [MIT License](LICENSE)。增强版代码由 Telegram Media Downloader Enhanced 项目维护；原项目及更早上游的版权声明继续按许可证保留。
