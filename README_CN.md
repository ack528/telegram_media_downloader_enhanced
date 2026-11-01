# 中文说明

项目主页现已统一使用中文，请阅读 [README.md](README.md)。
# 下载体积和视频分辨率范围

在运行目录的 `config.yaml` 中添加以下配置，重启后生效：

```yaml
download_limits:
  min_size_mb: 100       # 最小体积，MiB
  max_size_mb: 2048      # 最大体积，MiB
  min_video_resolution: 720   # 视频短边最小像素
  max_video_resolution: 1080  # 视频短边最大像素
```

每项设为 0 或省略表示不限制；范围包含边界。体积限制适用于所有媒体，分辨率限制适用于视频和视频消息，竖屏与横屏均按短边判断。启用限制时，缺少对应元数据的媒体会跳过。上限不得小于非零下限。范围筛选在下载前执行，也适用于恢复任务。
