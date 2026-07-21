# PWA Icons Placeholder

此目录存放 PWA 安装图标。

需要补齐以下文件（建议从 logo.svg 转换）：
- icon-192.png (192x192)
- icon-512.png (512x512)

可使用命令：
```bash
# 需要 ImageMagick 或 sharp
convert public/logo.svg -resize 192x192 public/icons/icon-192.png
convert public/logo.svg -resize 512x512 public/icons/icon-512.png
```
