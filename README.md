# 🎵 Music Sub

自托管音乐订阅、下载、整理和刮削系统。  
面向 PT 音乐站、qBittorrent、NAS / Docker 场景，把“找资源 → 下载 → 入库 → 元数据治理 → 通知/助手”串成一条自动化流水线。

> 当前版本：**v0.8.0**

## 核心能力

- **PT 搜索与订阅**：支持 M-Team、Open.CD、PTClub、Dis.Music；支持艺人 / 专辑 / 歌曲 / 关键词订阅。
- **统一搜索候选**：PT 与在线音乐源合并候选，按质量、相关性、来源展示下载决策。
- **qBittorrent 集成**：添加任务、监控完成、暂停/恢复/删除、外部 qB 任务接管。
- **手动标签导入**：在 qB 给任务打 `music-sub` 标签，完成后自动整理入库；处理后打 `已整理`，兼容旧 `music-sub-done`。
- **音乐库整理**：硬链接优先，跨盘自动复制；按 `{artist}/{album}` 结构组织。
- **元数据刮削**：QQ 音乐、网易云、MusicBrainz 多源回退；写入标签、歌词、封面、NFO。
- **音乐库治理**：缺封面、缺歌词、CUE 候选、专辑分裂、专辑艺人冲突等健康检查与批量处理。
- **智能助手**：Web / Telegram / QQBot / 企业微信 / 微信 Claw 入站；可查询曲库、搜索资源、诊断日志、准备下载动作。
- **通知系统**：Telegram / 企业微信 / QQBot / 微信 Claw；下载完成与刮削完成支持延迟聚合、专辑图和歌曲清单。
- **移动端 PWA**：移动端底部导航、图标、可复制文本和适配优化。
- **Dashboard 发现页**：本地推荐、系统状态、曲库健康、最近任务/入库/事件；卡片可拖动排序，自适应瀑布流排版。

## v0.8.0 亮点

### 1. 通知聚合

下载完成、刮削完成都支持延迟聚合推送，避免专辑多曲目时刷屏。

通知内容包含：

- 专辑封面图（Telegram 支持 `sendPhoto`）
- 专辑名
- 歌曲名
- 格式（FLAC / MP3 / M4A 等）
- 文件大小
- 总曲目数与总大小

可在设置页调整：

- `notify.download_complete_batch_delay_seconds`
- `notify.scrape_complete_batch_delay_seconds`

设为 `0` 表示立即聚合推送。

### 2. qB 手动标签监听

适合你已经在 qB 里手动下载好音乐的场景：

1. 在 qBittorrent 中给任务添加标签：`music-sub`
2. Music Sub 定时扫描完成任务
3. 自动硬链接 / 刮削 / 入库
4. 完成后给任务打上：`已整理`

默认跨分类监听，只看标签，不强制要求 qB 分类为 `music`。

### 3. 智能助手稳定性优化

- Telegram 入站走后台队列，避免长任务阻塞 polling。
- 拦截模型泄露的内部工具格式，如 `[工具结果]`、`</think>`、`minimax:tool_call`。
- 查询“某艺人的专辑还有哪些没入库”时走确定性本地库 + PT 对比流程。
- 搜索结果动作后端派生，前端不再回传大 JSON。

### 4. 发现页体验优化

- 卡片可拖动排序，顺序保存在浏览器本地。
- 自适应瀑布流排版，减少左右列高度不一致造成的大空白。
- 今日推荐加入随机 seed，“换一批”会真正变化。

## 快速开始

### Docker Compose 推荐部署

```bash
git clone https://github.com/cheng2rui/music-sub.git
cd music-sub

cp config/config.yaml.example config/config.yaml
vim config/config.yaml

docker compose up -d
```

打开：<http://localhost:8400>

默认账号 / 密码：`888` / `888`  
首次登录后建议立刻到设置页修改密码。

### 默认 docker-compose

项目内置 `docker-compose.yml` 默认只启动：

- `music-sub`：Web/API 服务，端口 `8400`

如果你的 Docker / NAS 里已经有 qBittorrent，不需要再安装 `music-sub-qb`。只要在 `config/config.yaml` 里把 `qbittorrent.host` 指向现有 qB 即可，例如：

```yaml
qbittorrent:
  host: "http://你的-qb-容器名或IP:8080"
```

如果你没有现成 qB，项目也提供可选内置 qB 服务：

```bash
docker compose --profile bundled-qb up -d
```

这会额外启动：

- `music-sub-qb`：qBittorrent，WebUI 端口 `8401`

默认数据目录：

| 路径 | 用途 |
| --- | --- |
| `./config` | 配置文件 |
| `./data/music_sub.db` | SQLite 数据库 |
| `./data/downloads` | qB 下载目录 |
| `./data/library` | 音乐库目录 |
| `./logs` | 日志 |

> 硬链接要求下载目录和音乐库目录在同一文件系统。跨设备时会自动 fallback 为复制。

### docker-compose.yml 模板

如果你不想使用仓库内置 compose，可以直接复制下面这份精简版：

```yaml
services:
  music-sub:
    image: ghcr.io/cheng2rui/music-sub:0.8.0
    container_name: music-sub
    ports:
      - "8400:8400"
    volumes:
      - ./config:/app/config
      - ./data:/app/data
      - ./logs:/app/logs
      - ./data/downloads:/downloads/music
      - ./data/library:/music
    environment:
      - MUSIC_SUB_CONFIG=/app/config/config.yaml
      - MUSIC_SUB_DB=/app/data/music_sub.db
    restart: unless-stopped

  # 如果没有现成 qBittorrent，可取消下面整段注释，然后执行：
  # docker compose --profile bundled-qb up -d
  # qbittorrent:
  #   profiles: ["bundled-qb"]
  #   image: lscr.io/linuxserver/qbittorrent:latest
  #   container_name: music-sub-qb
  #   ports:
  #     - "8401:8080"
  #     - "57881:57881"
  #     - "57881:57881/udp"
  #   volumes:
  #     - ./data/qb-config:/config
  #     - ./data/downloads:/downloads/music
  #   environment:
  #     - PUID=1000
  #     - PGID=1000
  #     - TZ=Asia/Shanghai
  #     - WEBUI_PORT=8080
  #     - TORRENTING_PORT=57881
  #   restart: unless-stopped
```

如果使用内置 qB，Music Sub 配置里 qB 地址建议写：

```yaml
qbittorrent:
  host: "http://qbittorrent:8080"
  username: "admin"
  password: ""
  category: "music"
  save_path: "/downloads/music"
  tag: "music-sub"
  monitor_tagged_torrents: true
```

如果使用已有 qB，把 `host` 改成你的实际地址，例如 `http://192.168.1.10:8080` 或同一 Docker 网络下的容器名。

## 关键工作流

```text
订阅 / 搜索 / 手动 qB 标签
  ↓
qBittorrent 下载
  ↓
完成监听（默认每 5 分钟）
  ↓
硬链接或复制到音乐库
  ↓
刮削元数据、歌词、封面、NFO
  ↓
写入 SQLite music_files
  ↓
下载完成 / 刮削完成聚合通知
```

## 主要配置

完整示例见：`config/config.yaml.example`

### qBittorrent

```yaml
qbittorrent:
  host: "http://qbittorrent:8080"
  username: "admin"
  password: ""
  category: "music"
  save_path: "/downloads/music"
  tag: "music-sub"
  monitor_tagged_torrents: true
```

说明：

- `tag`：Music Sub 自动任务和手动导入任务都使用这个标签。
- `monitor_tagged_torrents`：开启后，任何 qB 任务只要带 `music-sub` 标签，完成后都会被自动接管。
- 处理完成后会打 `已整理`，旧版 `music-sub-done` 也会被识别为已处理。

### 刮削

```yaml
scraper:
  sources: [qqmusic, netease, musicbrainz]
  embed_cover: true
  save_cover_file: true
  save_lyrics_to_tag: true
  save_lyrics_file: true
  save_nfo: true
  rename_file: false
  rename_template: "${track} - ${title}"
  tag_write_mode: "fill_missing"   # skip_existing / fill_missing / overwrite
  break_hardlink_before_tag: true
```

### 通知

```yaml
notify:
  download_complete_batch_delay_seconds: 20
  scrape_complete_batch_delay_seconds: 20
  telegram:
    enabled: false
    bot_token: ""
    chat_id: ""
    enable_polling: true
    assistant_chat: true
    on_download_added: false
    on_download_complete: true
    on_scrape_complete: true
    on_error: true
    on_cleanup_candidates: true
```

支持通道：

- Telegram Bot
- 企业微信应用
- QQBot
- 微信 Claw / iLink

Telegram 推荐使用 **polling**，NAS / 内网部署无需公网 HTTPS。

### Assistant

```yaml
assistant:
  enabled: false
  global_chat: true
  max_history_messages: 20
  max_iterations: 4
  tool_timeout_seconds: 120
  incoming_queue_idle_timeout_seconds: 300
  allow_online_search_candidates: true
  allow_online_download: false
  allow_library_write: true
  provider:
    provider: openai_compatible
    runtime: openai_compatible
    base_url: ""
    api_key: ""
    model: ""
```

## API 概览

| 路径 | 说明 |
| --- | --- |
| `GET /api/health` | 健康检查 |
| `GET /api/discover/personalized` | 本地今日推荐 |
| `GET /api/library/stats` | 曲库统计 |
| `GET /api/library/albums` | 专辑列表 |
| `GET /api/library/album-tracks` | 专辑曲目 |
| `GET /api/library/health` | 曲库健康检查 |
| `POST /api/search/` | PT 搜索 |
| `GET /api/search/candidates` | PT + 在线统一候选 |
| `POST /api/online/search` | 在线音乐搜索 |
| `POST /api/online/download` | 在线音乐下载入库 |
| `GET /api/tasks/page` | 任务分页/筛选 |
| `POST /api/tasks/check` | 手动触发完成检查 |
| `GET /api/settings/` | 当前设置 |
| `PUT /api/settings/` | 保存设置 |
| `POST /api/assistant/chat` | 智能助手对话 |
| `GET /api/notify/status` | 通知状态 |
| `GET /api/notify/events` | 通知事件流 |

## 开发命令

```bash
# 后端基础语法检查
python3 -m py_compile app/**/*.py

# 前端构建
cd frontend && npm run build

# Docker 构建
docker build -t music-sub:0.8.0 -t music-sub:latest .

# 启动 / 重启
docker compose up -d
docker restart music-sub

# 查看日志
docker logs -f music-sub
```

## 技术栈

- Backend：Python 3.12 + FastAPI + SQLAlchemy + APScheduler
- Frontend：Vue 3 + Vite + Pinia
- DB：SQLite
- Downloader：qBittorrent Web API
- Metadata：QQ 音乐 / 网易云 / MusicBrainz + `music_tag`
- Deploy：Docker / Docker Compose

## 项目结构

```text
app/
  api/                  FastAPI 路由
  downloader/           qBittorrent 客户端与完成监听
  organizer/            硬链接 / 复制 / 命名规则
  scrapers/             元数据、歌词、封面、标签写入
  services/             pipeline、通知、Assistant、搜索候选
  sites/                PT 站点适配器
config/                 配置模板
frontend/               Vue 前端源码
web/dist/               前端构建产物
data/                   SQLite、下载和音乐库数据（默认 compose）
logs/                   应用日志
```

## License

MIT
