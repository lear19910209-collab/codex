# 商品图批量整理器

Windows 本地桌面软件：商品图片批量改名、统一尺寸、压缩、格式转换和重复检测。

**完全离线处理。原图始终保留，所有结果写入新的文件夹。**

![软件首页](product-image-organizer/docs/screenshot-home.png)

- [完整使用说明与源码文件位置](product-image-organizer/README.md)
- [下载已验证的 Windows 安装包和免安装版](https://github.com/lear19910209-collab/codex/actions/runs/37602687463/artifacts/11473706374)
- [Windows 安装包构建 / 下载页面](https://github.com/lear19910209-collab/codex/actions/workflows/product-image-windows.yml)
- [测试与交付说明](product-image-organizer/docs/TEST_REPORT.md)

构建显示绿色勾后，进入运行页面，在下方 Artifacts 下载 `Windows-商品图批量整理器-1.0.0` 并解压。

**给买家发 `ProductImageOrganizer-1.0.0-Setup.exe`。买家无需安装 Python，也不需要注册或联网。**

软件源码位于 `product-image-organizer/`。这个项目是 Windows 桌面软件，GitHub Pages 网址不能直接运行桌面 exe。

1.0.0 已在 Windows 构建通过：69 项测试、实际 exe 图像转换、原图保护、窗口启动退出、安装和卸载。构建产物保留至 2027-01-05；之后可在上方构建页面重新运行生成。
