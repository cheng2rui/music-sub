# Island Theme Notes

Music Sub 的 `island` 主题是一套本地研究/个人使用的 Animal Island 风格界面。

## 资源来源

当前静态资源整理在：

- `frontend/public/animal-island/`

主要参考/来源仓库：

- `yanstu/animal-island-ui-vue` — Vue 3 / Vite 的 Animal Island 风格组件库与 demo 资源。

## 资源清单

- `animal_icon.svg`
- `content_bg_pc.jpg`
- `guide-bg-line.webp`
- `home_bg.svg`
- `menu_bg.svg`
- `components/cursor-icon.png`
- `components/divider_line.png`
- `nook-phone/AppIcons.svg`
- `nook-phone/Property-Camera.svg`
- `nook-phone/Property-Chat.svg`
- `nook-phone/Property-Helicopter.svg`
- `nook-phone/Property-Recipes.svg`
- `nook-phone/Property-Shopping.svg`
- `nook-phone/nook1.svg`
- `nook-phone/nook2.svg`

## 代码入口

- `frontend/src/utils/animalIsland.js` 统一管理图标/资源路径。
- `frontend/src/styles/variables.css` 负责 island 主题的整体视觉与移动端调优。
- `scripts/smoke_test.py` 会检查关键 `/animal-island/...` 静态资源和前端 CSS/JS 引用。

## 验收清单

发布前至少检查：

1. `npm --prefix frontend run build`
2. `docker build -t music-sub:<version> .`
3. `./scripts/smoke_test.py --expect-version <version> --container music-sub`
4. 浏览器切到「岛屿」主题，快速走查：登录页、发现、曲库、专辑、在线、订阅、助手、设置、播放器、移动端底部导航。

## 注意

- 非 island 主题的 emoji 图标是兼容展示，不应为了 island 主题全局删除。
- Vue 文件里新增 island 图标时，优先使用 `animalIslandIcons`，避免重新硬编码 `/animal-island/...`。
- CSS 背景和 cursor 可以保留静态路径，因为它们属于主题样式本身。
