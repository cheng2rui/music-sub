# Music Sub 后续重开发路线（MoviePilot + mtw/music-tag-web 借鉴）

> 目标版本基线：Music Sub v0.7.12+  
> 参考资料：`/tmp/MoviePilot-Frontend`、`tmp/moviepilot-mobile-ui-audit-report.md`、`tmp/mtw-scrape-audit-report.md`  
> 取舍原则：优先补「产品感 + 稳定性 + 可观测性」，不追求照搬 MoviePilot 的 Vuetify/插件体系，也不把 mtw 的全量标签编辑一次性搬完。

## 0. 当前判断

Music Sub 现在已经吃掉了一批最关键的低垂果实：

- MoviePilot 方向：底部导航已收口为「发现 / 搜索 / 曲库 / 任务 / 更多」，设置页已有分组 tabs，移动端播放器和卡片化已明显改善。
- mtw/music-lib 方向：`MusicMeta` 已补 `album_id / duration / quality / provider_extra` 等字段，`matcher.py` 已有 duration/track/year 维度，`ScrapeContext` 已做 job 内 scraper 复用、search cache 和失败 backoff，`break_hardlink_before_tag` 已默认开启。
- 曲库方向：已有健康检查、批量重刮削 job、封面/歌词/专辑艺人冲突/CUE 候选等入口。

所以下一阶段不建议继续做“零散 UI 美化”，而应该进入三条主线：

1. **Dashboard / 任务 / 日志 / 通知联动**：让用户一打开就知道系统是否健康、今天做了什么、哪里卡住。
2. **刮削匹配可解释 + 专辑一致性**：把“为什么匹配错/为什么没歌词/为什么这张专辑漂了”显示出来，并能批量修。
3. **移动端沉浸式治理体验**：曲库、健康检查、任务、日志、设置都用同一套浮层/快捷操作/卡片流，减少桌面表格思维。

---

## 1. MoviePilot 还值得抄什么

### 1.1 Dashboard：从“发现页”升级为“系统驾驶舱”

MoviePilot 的 `dashboard.vue` 值得抄的不是拖拽本身，而是：

- dashboard item 化：存储、调度器、速度、统计、最近入库、正在播放等模块独立开关。
- 每个模块有自己的刷新策略，而不是整页重新加载。
- 配置入口通过动态按钮打开，主界面保持沉浸。
- 用户可以决定首页看到什么。

Music Sub 建议做一个轻量版 dashboard，放在 `/discover` 顶部或新增 `/dashboard`：

- **系统状态卡**：qB 连接、启用站点数、最近调度成功/失败、Telegram 通知状态。
- **下载/整理卡**：下载中、已完成待整理、刮削失败、qB 未关联任务数。
- **曲库健康卡**：缺封面、缺歌词、未刮削、专辑艺人冲突、CUE 候选。
- **最近入库卡**：最近 5 张专辑，直接进入专辑页。
- **快捷操作卡**：检查任务、扫描曲库、批量重刮削当前健康项、打开日志。

第一版不要做拖拽，先做固定顺序 + 可折叠即可。

### 1.2 设置 / 插件市场：Music Sub 不该做插件市场，但该做“工具中心”

MoviePilot 的插件市场很成熟，但 Music Sub 目前体量不适合立刻做插件系统。更适合借鉴两个形态：

- 插件卡片市场的「能力目录」表达：功能是什么、风险等级、状态、入口。
- 插件配置异步加载/按需打开：不要把所有高级工具塞进曲库页。

Music Sub 可把现有 `LibraryToolsModal` 演进成 `/tools` 或“更多 → 工具中心”：

- 标签治理：繁简转换、乱码修复、重命名、专辑艺人修复。
- 媒体治理：CUE 拆分、重复文件、删除候选。
- 元数据治理：批量补封面、批量补歌词、批量重刮削。
- 每个工具卡片显示：风险等级、是否会改文件、支持预览、最近执行结果。

这比“插件市场”更落地，也更符合 Music Sub 的音乐治理定位。

### 1.3 任务 / 日志：从列表升级为“可解释时间线”

MoviePilot 的任务和日志有强烈的运维产品感：状态、进度、动作、日志能互相跳转。

Music Sub 当前已有任务页、日志页、`scrape_jobs.py`，但用户仍很难回答：

- 这个专辑到底卡在哪一步？
- 哪个源超时了？
- 某首歌为什么匹配成 Live/Remix？
- 批量任务失败了哪些文件？

建议引入 **Operation Timeline** 概念：

- 任务详情页/抽屉展示：下载 → hardlink/copy-on-write → 专辑聚类 → 每首刮削 → 写 tag → 保存 sidecar → 通知。
- 每个 step 记录 `status / message / source / candidate_score / duration_ms`。
- 日志页支持按 `task_id / job_id / album / source` 过滤。
- job 完成后保留简短 summary，不需要一开始就持久化全量日志。

### 1.4 通知：通知不是只发 Telegram，而是产品状态流

MoviePilot 的通知中心值得抄“统一状态入口”的思想。Music Sub 可分两步：

- v0.7.15：站内通知中心，只存最近 50 条事件：下载添加、完成、刮削失败、健康扫描发现、配置测试失败。
- v0.7.16：Telegram 通知复用同一事件模型，可按事件类型开关。

这样设置页里的 Telegram 配置不会只是孤岛，任务/日志/dashboard 都能共用一套 event feed。

### 1.5 全局快捷操作：抄动态按钮，不抄全局复杂注入

MoviePilot 的 `useDynamicButton` + footer floating action 很适合移动端。Music Sub 可做极简版：

- 顶层提供 `pageActions` store。
- 每个页面注册 1 个主操作 + 最多 4 个二级操作。
- 移动端右下角/底部 dock 旁显示 FAB；桌面端显示在 topbar 右侧。

可注册动作示例：

- 曲库：扫描 / 健康检查 / 工具箱。
- 任务：检查完成 / 清理候选。
- 日志：刷新 / 只看错误 / 清空。
- 设置：保存 / 测试当前分组。

### 1.6 移动端沉浸式：重点是“底部 sheet + 安全区 + 少跳页”

MoviePilot 的移动端强在浮层体系：bottom sheet、shared dialog、footer dock、安全区统一。

Music Sub 后续应统一：

- 专辑详情、曲目编辑、健康项处理、任务详情、日志详情都优先用 bottom sheet / modal，不要频繁跳完整页面。
- 所有 fixed 元素遵循同一套 token：`--mobile-tab-height / --mobile-player-height / --mobile-safe-bottom / --mobile-content-bottom`。
- 页面主列表保持滚动位置，操作完成后局部刷新。

---

## 2. mtw/music-tag-web 还值得抄什么

### 2.1 刮削匹配：从“智能选择”升级为“可解释候选”

Music Sub 的 scoring 已不弱，但缺 UI 和记录。mtw/music-lib 给我们的启发是：标签治理产品必须让用户看到候选差异。

建议新增 `ScrapeDecision` 结构（可先不落 DB，job 内返回即可）：

- query：title_hint / artist_hint / album_hint / duration_hint / track_hint。
- candidates：source / title / artist / album / duration / track / score / reasons。
- selected：最终采用项。
- fallback：本地 tag / filename / sidecar 是否参与。
- warnings：duration mismatch、album mismatch、no lyrics、cover download failed。

前端在曲目编辑/重刮削 job 里显示“候选解释”，解决用户不信任黑盒的问题。

### 2.2 歌词/封面/标签编辑：补“单曲编辑器”和“专辑批量编辑器”

mtw 强项是标签编辑入口明确。Music Sub 目前曲目 modal 有基础编辑，但还不够像治理工具。

建议能力分层：

- 单曲编辑：title、artist、album_artist、album、track、disc、year、genre、lyrics、cover。
- 专辑编辑：album、album_artist、year、genre、cover，一次应用到整张专辑。
- 批量模板：`${track} - ${title}`、artist 分隔符规范化、繁简转换。
- 预览优先：写文件前展示将修改的字段和文件名。

第一阶段可先只改 DB + sidecar，写入音频 tag 放到“应用到文件”按钮里，降低风险。

### 2.3 批量治理：从健康检查升级为治理工作台

现有健康检查是好的起点，但后续应把它做成治理工作台：

- 左侧/顶部是问题类型：缺封面、缺歌词、未刮削、专辑艺人冲突、CUE、重复文件、疑似错误匹配。
- 中间是 album/file 卡片列表。
- 右侧/底部是批量动作：预览、应用、跳过、标记已处理。
- 每个问题项要显示“为什么被判定为问题”。

新增两个问题类型很值得做：

- **疑似错误匹配**：duration 偏差 > 10s、title score 高但 album score 低、被 variant_penalty 命中。
- **专辑不一致**：同一 album 文件夹下 album_artist/year/track_count/source album_id 不一致。

### 2.4 专辑一致性：下一阶段最值得重投入

Music Sub 是“音乐订阅 + 自动整理”，整专辑正确比单曲正确更重要。mtw/music-lib 的 album 视角可以继续抄：

- 增加 scraper album API：`search_album()`、`get_album_tracks()`。
- 专辑重刮削先锁定 album candidate，再按 tracklist 对齐本地文件。
- 保存 album-level metadata：album_id、source、track_count、release_date、cover。
- 前端给用户一个“专辑对齐预览”：本地 01-12 对应在线 01-12，缺失/多余/时长异常一眼看出。

这应该是 v0.7.17 的重头戏。

---

## 3. 版本路线建议

## v0.7.15：产品感与可观测性补齐版

### 版本目标

让用户打开首页/任务/日志时能立刻知道系统健康、最近动作、失败原因。优先做“看得见、点得到、能追踪”。

### 功能范围

1. **轻量 Dashboard / 状态首页**
   - `/discover` 顶部新增系统状态卡组，或新增 `/dashboard` 并把发现内容下移。
   - 卡片：曲库统计、健康问题、任务状态、调度器状态、最近入库、快捷操作。

2. **任务详情抽屉 / job 历史入口**
   - 任务页展示最近 scrape jobs。
   - 点击 job 展开 steps：queued/running/ok/failed/message。
   - 批量重刮削完成后可回看结果。

3. **日志页增强**
   - 快捷过滤：错误 / 警告 / scraper / qB / task。
   - 支持从 job/task 带 query 跳转日志页。

4. **站内事件流 MVP**
   - 后端先做 in-memory ring buffer 即可。
   - 事件类型：download_added、download_complete、scrape_complete、scrape_failed、health_warning、settings_test。
   - Dashboard 和 Telegram 通知后续共用。

### 文件范围

- 前端：
  - `frontend/src/views/DiscoverView.vue` 或新增 `frontend/src/views/DashboardView.vue`
  - `frontend/src/views/TasksView.vue`
  - `frontend/src/views/LogsView.vue`
  - `frontend/src/api/index.js`
  - 可新增 `frontend/src/components/StatusCard.vue`
  - 可新增 `frontend/src/components/JobTimeline.vue`
- 后端：
  - `app/api/library.py`（job list/detail 已有，可补 summary 字段）
  - `app/services/scrape_jobs.py`
  - `app/api/logs.py`
  - 可新增 `app/services/events.py`
  - 可新增 `app/api/events.py`
  - `app/main.py` 注册 router

### 风险

- 如果 dashboard 一次拉太多 API，手机端首屏会慢。建议分卡片 lazy load。
- in-memory event/job 重启丢失是可接受的，但 UI 需要标注“最近运行记录”。
- 日志过滤如果直接扫文件，注意 limit 和 tail，避免大日志卡死。

