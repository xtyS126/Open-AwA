# Open-AwA 品牌静态资产

本目录保存“软晶单元”品牌标记的独立设计交付，不会自动替换网页、Android 或桌面端正在使用的资源。几何构形延续已确认的非对称三层软晶路径，不表达字母、表情、人物或设备。

## 资产清单

### 可编辑矢量资产

- `brand/icon-master.svg`：1024 × 1024 圆角底板母版，主体约占画布宽度的 68%。
- `brand/icon-circle.svg`：圆形底板版本。
- `brand/icon-mark.svg`：透明底板标记，使用低对比轮廓保证浅色背景可辨识。
- `brand/icon-construction.svg`：1024 网格、安全区、底板和主体构造说明图。
- `brand/favicon.svg`：省略暖桃切口的简化网页图标，适合 16px 与 32px。
- `brand/android-adaptive-foreground.svg`：Android 自适应图标前景参考，主体保持在中央安全区内。
- `brand/android-adaptive-background.svg`：Android 自适应图标极简渐变背景参考。
- `brand/android-adaptive-monochrome.svg`：Android 主题图标单色轮廓参考。

所有 SVG 均为独立文件，不使用外链图片、外部字体、脚本或滤镜。

### 栅格与桌面资产

- `brand/icon-1024.png`
- `brand/icon-512.png`
- `brand/icon-256.png`
- `brand/icon-128.png`
- `brand/icon-64.png`
- `brand/icon-48.png`，供 Windows ICO 标准帧使用。
- `brand/icon-32.png`
- `brand/icon-16.png`
- `brand/favicon-32.png`
- `brand/favicon-16.png`
- `brand/open-awa.ico`，包含 256、128、64、48、32、16px 六个尺寸。

PNG 统一输出为 sRGB RGBA，圆角底板外侧保留透明像素。`favicon-16.png` 与 `favicon-32.png` 来自简化 favicon 母版；通用 `icon-16.png` 则来自完整应用图标母版。

## 可复现生成

在项目根目录执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\assets\design\open-awa-brand-refresh\sources\generate-brand-assets.ps1
```

脚本要求本机可调用 ImageMagick 7 的 `magick` 命令。脚本只重建本目录 `brand/` 下由本资产包声明的 PNG 和 ICO，不修改 `DESIGN_SPEC.md` 或产品资源，并在生成后自动运行验证。

如只需重新验证现有文件：

```powershell
powershell -ExecutionPolicy Bypass -File .\assets\design\open-awa-brand-refresh\sources\validate-brand-assets.ps1
```

验证内容包括 SVG XML 解析、禁止依赖扫描、PNG 尺寸、RGBA 通道、透明与不透明像素共存，以及 ICO 多尺寸帧。

## 构造说明

- 母版画布为 1024 × 1024。
- 橙桃色虚线框表示四周 14% 安全区，边界坐标为 143.36 至 880.64。
- 紫罗兰底板位于 `(32, 32)`，尺寸为 `960 × 960`，圆角半径为 `246`。
- 软晶主体由奶油白至浅桃色外层、紫罗兰内层与暖桃色切口组成，使用与前端 BrandMark 相同的非对称路径比例。
- Android 前景的外部软晶边界约位于 108 × 108 视口的 `x=22.4..85.6`、`y=21.2..87.2`，不接触自适应图标安全区边缘。

## 使用边界

这些文件是供审查和后续选择性接入的设计资产。接入产品时应另行执行网页构建与浏览器检查、Android 构建与模拟器检查、桌面打包与窗口检查。
