# AI Pose Gallery · 中英日三语本地版

原站：<https://ai-pose-gallery.pages.dev/>  
原始快照与三语版本日期：2026-10-29

完整保存 288 个姿势、1,439 张原尺寸 PNG 和 1,439 张 JPEG 缩略图。保留原站图片、日文图库和使用说明，移除推广区域，并提供完整简体中文、英文和日文界面。当前视觉采用 Brclio Design System；原站基础样式源码仍完整保留。运行时无需联网，也无需安装第三方依赖。

## 启动

```sh
python3 scripts/serve.py
```

打开 <http://127.0.0.1:4173/>。也可双击 macOS 的 `启动本地网站.command`，或执行 `npm start` / `npm run dev`。服务仅监听本机，按 Ctrl+C 停止。需要 Python 3.9 或更新版本。

若端口被占用：`python3 scripts/serve.py --port 4174`。

## 三语功能

顶部与图片预览窗均提供 **中文 / English / 日本語** 按钮。首次默认中文，随后记住手动选择的语言；浏览器不允许本地存储时仍可正常切换。

翻译覆盖全部 288 个姿势名称、4 个系列、26 个分类、5 个角度，以及搜索、计数、提示、使用说明、注意事项、下载按钮与辅助阅读标签。原始日文数据保持不变。

切换语言保留搜索、系列、分类、角度、浏览模式及当前预览图片。搜索可直接使用任意一种语言的姿势名称或分类，也支持原始图片 ID 和姿势编号。

可用 `?lang=zh`、`?lang=en`、`?lang=ja` 指定初始语言。显式 URL 优先于已保存的语言选择；点击切换按钮后 URL 中的语言也会同步更新。

## 图库操作

- 按姿势或逐张图片浏览；按系列、分类、角度联合筛选。
- 悬停或聚焦角度缩略图预览，点击主图打开当前预览角度。
- 大图预览中：左右方向键切换角度，上下方向键切换姿势，Esc 关闭。
- Tab 焦点限制在大图弹窗内，关闭后返回原卡片或按钮；触摸左右滑动切换角度。
- 下载按钮保存原尺寸 PNG，文件名与源站 ID 一致。
- 手机端通过“筛选 / Filters / 絞り込み”展开筛选条件。

图片共 691,586,721 字节（659.55 MiB），未重新压缩或转码。原站 `full_sexy/P018` 本就只有 4 个角度，缺“下から”，保持原样。

页首及页尾的推广文案、社群按钮和作者按钮已移除。原始网页快照仍完整保存在 `localization/original.html`，原站使用条件完整保留在“注意事项 / Usage notes / 注意点”中。图库无自动外网请求；Cloudflare Analytics 已移除，CSP 禁止外部连接。

## 修改与构建

视觉层基于 [Brclio Design System](https://github.com/Brclio/brclio-design-system) 的 App 模板与组件适配：暖奶油背景、品牌蓝操作控件、黄色选中提示、衬线标题及无衬线正文。仅覆盖样式，页面内容、业务脚本、三语字典及图片保持不变。字体使用本地系统字体栈，无在线字体请求。

样式适配署名：© 2026 Brclio，采用 [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/)；该声明仅适用于 Brclio 设计系统及其样式适配，图库素材仍遵循原站使用说明。

`index.html` 是已生成的独立运行入口。修改源文件或译文后执行：

```sh
python3 scripts/build.py
python3 scripts/verify.py
```

也可使用 `npm run build` 和 `npm run verify`。构建把所有样式、脚本、数据与译文内嵌到 HTML，运行不加载额外 JS、JSON 或字体文件。

| 路径 | 用途 |
| --- | --- |
| `src/template.html` | 页面结构与内嵌资源占位符 |
| `src/original.css` | 原站基础样式，逐字保留 |
| `src/brclio.css` | Brclio 品牌样式覆盖层，构建时内嵌 |
| `src/app.js` | 语言切换、搜索、筛选、图片预览交互 |
| `localization/ui.i18n.json` | 三语界面、分类、角度及说明 |
| `localization/poses-full.i18n.json` | 两个全身系列的中英文姿势名 |
| `localization/poses-upper-pair.i18n.json` | 半身和双人系列的中英文姿势名 |
| `localization/original.html` | 原始 HTML 快照及日文图库数据；非运行入口 |
| `localization/source.json` | 来源、变更范围、HTML SHA-256 |
| `localization/asset-manifest.json` | 每张图片的来源、字节数及 SHA-256 |
| `localization/i18n-verification.md` | 三语版本审核及浏览器验证记录 |
| `localization/brclio-verification.md` | Brclio 样式检查及功能回归记录 |
| `localization/verification-output.txt` | 当前版本完整校验结果 |
| `localization/{zh,en,ja}-{desktop,mobile}.jpg` | 三语界面截图 |

## 完整性校验与资源恢复

`python3 scripts/verify.py` 检查构建可复现、原始 CSS/图库数据一致、三语翻译完整、日文使用条件原样、推广区域及外链已移除，以及全部 2,878 个图片文件的格式首尾、大小及 SHA-256。失败返回非零状态。

需要恢复丢失或损坏的图片时执行 `python3 scripts/sync-assets.py`（需要 curl 和网络），再运行完整校验。恢复工具保留旧 SHA，不会静默接受源站后来改动的图片。

自动浏览器验证采用 localhost；未验证 `file://` 打开方式。`localization/verification.md` 和 original/local 对照截图记录的是添加三语之前的首次本地化检查。
