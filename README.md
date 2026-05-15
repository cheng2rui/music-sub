# 🎵 Music Sub

PT 站音乐订阅 + qBittorrent 下载 + 硬链接整理 + 自动刮削，一站式自托管。

> 自动追踪 PT 站新种 → 推送到 qBittorrent → 完成后硬链接到音乐库 → 调用 QQ 音乐 / 网易云 / MusicBrainz 写标签 / 歌词 / 封面 / NFO。

## ✨ 功能

- **多 PT 站搜索 / 订阅**：M-Team（API）、Open.CD、PTClub、Dis.Music
- **智能订阅**：按艺人/歌曲/专辑/关键词分类搜索 + 品质过滤（FLAC/MP3）
- **下载器集成**：qBittorrent Web API（添加 / 监控 / 打 tag）
- **硬链接整理**：按 `{artist}/{album}` 模板组织音乐库，节省磁盘
- **元数据刮削链**：QQ 音乐 → 网易云 → MusicBrainz，逐级回退
- **音频标签写入**：title / artist / album / year / 封面 / 歌词
- **专辑级 NFO**：Kodi / Jellyfin 兼容，含每条 track
- **手动标签编辑**：刮削结果不对时可手动修正
- **批量重新刮削**：专辑级/单曲/未完成批量三种模式
- **Web UI**：Vue3 SPA（Spotify 风格）—— 发现 / 订阅 / 搜索 / 任务 / 音乐库 / 设置 / 日志
- **主题系统**：暗色 / 亮色 / 暗色透明 / 亮色透明（毛玻璃效果 + 专辑封面背景）
- **音乐库浏览**：专辑封面网格 + 曲目详情弹窗 + 模糊搜索
- **通知推送**：Telegram Bot（下载/刮削/错误事件）
- **定时任务可视化**：状态/下次运行/上次结果 + 手动触发
- **登录认证**：JWT + 设置页改密码
- **日志系统**：实时查看 + 级别过滤 + 清空

## 🚀 快速开始

### Docker Compose（推荐）

```bash
git clone https://github.com/cheng2rui/music-sub.git
cd music-sub

# 复制配置模板并填写
cp config/config.yaml.example config/config.yaml
vim config/config.yaml

# 启动
docker compose up -d

# 打开 Web UI
open http://localhost:8400
```

默认账号：`888` / 密码：`888`（登录后在设置页修改）

### docker-compose.yml

```yaml
version: "3.8"

services:
  music-sub:
    image: ghcr.io/cheng2rui/music-sub:latest
    # 或本地构建：
    # build: .
    container_name: music-sub
    ports:
      - "8400:8400"
    volumes:
      - ./config:/app/config
      - ./data:/app/data
      - ./logs:/app/logs
      - /downloads/music:/downloads/music
      - /music:/music
    environment:
      - MUSIC_SUB_CONFIG=/app/config/config.yaml
      - MUSIC_SUB_DB=/app/data/music_sub.db
    restart: unless-stopped
```

### 本地构建

```bash
# 构建镜像（多阶段：Node build前端 + Python运行时）
docker compose build
docker compose up -d
```

数据持久化：

| 路径              | 用途                       |
| ----------------- | -------------------------- |
| `./config/`       | 配置文件                   |
| `./data/`         | SQLite DB                  |
| `/downloads/music`| qBittorrent 下载目录       |
| `/music`          | 音乐库目标目录（硬链接源）|

> ⚠️ 硬链接要求 `/downloads/music` 和 `/music` 在同一文件系统。跨设备时会自动 fallback 为 copy。

## 🎯 关键工作流

```
PT 订阅
  ↓ 定时搜索（默认 30 分钟）
  ↓ 命中 → 下载 .torrent 文件
  ↓ 添加到 qBittorrent
  ↓ APScheduler 监控完成（默认 5 分钟轮询）
  ↓ 硬链接到 /music/{artist}/{album}/
  ↓ 调用刮削器拿元数据
  ↓ 写标签 + cover.jpg + .lrc + album.nfo
  ↓ 入库 music_files
```

## ⚙️ 配置说明

完整字段见 `config/config.yaml.example`。重点：

### 站点认证

| 站点      | 认证方式                          |
| --------- | --------------------------------- |
| M-Team    | API Key（站点 → 设置 → 安全）     |
| Open.CD   | 浏览器 Cookie（F12 复制）         |
| PTClub    | 浏览器 Cookie                     |
| Dis.Music | 浏览器 Cookie                     |

### qBittorrent

```yaml
qbittorrent:
  host: "http://localhost:8080"
  username: "admin"
  password: "your-pass"
  category: "music"      # 自动归类到此分类
  tag: "music-sub"       # 自动打 tag，方便筛选
  save_path: "/downloads/music"
```

### 刮削行为

```yaml
scraper:
  sources: [qqmusic, netease, musicbrainz]   # 按顺序尝试
  embed_cover: true       # 写到音频标签
  save_cover_file: true   # 同时写 cover.jpg
  cover_max_size: 0       # 0 = 原图; >0 = 压缩到该宽度
  save_lyrics_to_tag: true
  save_lyrics_file: true
  save_nfo: false         # Kodi/Jellyfin 用户开
  rename_file: false      # 按 rename_template 重命名
  rename_template: "${track} - ${title}"
  overwrite_tag: false    # true 强制覆盖已有标签
```

### 通知（待接入事件）

```yaml
notify:
  telegram:
    enabled: false
    bot_token: "123456:ABC..."
    chat_id: "-100..."     # 群组用 -100 开头；私聊用 user id
    on_download_complete: true
    on_scrape_complete: true
    on_error: true
```

> 当前可在 Web UI 设置页点 "📨 发送测试" 验证渠道，事件触发后的实际推送暂未接入。

## 🔌 API 端点

| 路径                                | 说明                       |
| ----------------------------------- | -------------------------- |
| `GET  /api/health`                  | 健康检查                   |
| `GET  /api/discover/recommend`      | 新歌推荐                   |
| `GET  /api/discover/playlists`      | 推荐歌单                   |
| `GET  /api/discover/toplist`        | 排行榜                     |
| `GET  /api/subscriptions/`          | 订阅列表                   |
| `POST /api/subscriptions/`          | 创建订阅                   |
| `POST /api/search/`                 | 跨站搜索                   |
| `POST /api/search/download`         | 下载指定种子               |
| `GET  /api/tasks/`                  | 下载任务列表               |
| `POST /api/tasks/check`             | 手动触发完成检查           |
| `GET  /api/library/stats`           | 库统计                     |
| `GET  /api/library/`                | 最近添加文件               |
| `GET  /api/library/albums`          | 专辑分组（含封面/进度）    |
| `GET  /api/library/album-tracks`    | 某专辑曲目                 |
| `GET  /api/library/album-cover`     | 专辑封面图                 |
| `GET  /api/settings/`               | 当前配置（敏感字段已掩码） |
| `PUT  /api/settings/`               | 保存配置                   |
| `POST /api/settings/test_qb`        | 测试 qBittorrent 连接      |
| `POST /api/settings/test_telegram`  | 发送 Telegram 测试消息     |

## 🛠 技术栈

- **后端**：Python 3.12 + FastAPI + SQLAlchemy + APScheduler
- **存储**：SQLite + 硬链接文件系统
- **下载器**：qbittorrent-api
- **音频标签**：music_tag
- **前端**：Vue 3（CDN）单文件 SPA
- **部署**：Docker / docker-compose

## 📁 项目结构

```
app/
├── api/              # FastAPI 路由
│   ├── discover.py
│   ├── library.py
│   ├── search.py
│   ├── settings.py
│   ├── subscriptions.py
│   └── tasks.py
├── sites/            # PT 站适配器
├── scrapers/         # 元数据刮削（QQ/网易/MusicBrainz）
├── downloader/       # qBittorrent 客户端 + 完成监控
├── organizer/        # 硬链接 + 命名规则
├── services/         # pipeline + searcher + subscription
├── config.py
├── db.py
├── models.py
├── scheduler.py
└── main.py
config/               # config.yaml（gitignore）+ 模板
web/index.html        # Vue3 SPA
data/                 # SQLite（gitignore）
```

## 📋 开发命令

```bash
# 本地构建并部署
docker build -t music-sub:latest .
docker compose up -d

# 增量更新代码（不重 build）
docker cp app/api/library.py music-sub:/app/app/api/library.py
docker restart music-sub

# 查看日志
docker logs -f music-sub
```

## 🗺️ Roadmap

- [x] 版本号统一 / NFO 输出 / 文件重命名
- [x] 音乐库专辑卡片视图
- [x] Telegram 通知渠道配置
- [ ] Telegram 事件触发推送（下载/刮削/错误）
- [ ] 订阅高级规则（FLAC only / 大小过滤）
- [ ] PT 站 cookie 过期检测
- [ ] 音乐库批量重新刮削
- [ ] 日志页面 / 运行仪表盘
- [ ] 单元测试

## 📝 License

MIT
