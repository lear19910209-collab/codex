# 开源依赖和源码

商品图批量整理器使用以下开源组件，允许按各自许可商业分发。本项目代码采用 MIT 许可。

| 组件 | 版本 | 许可 | 上游 |
| --- | --- | --- | --- |
| Python | 3.12 | PSF 及 Python 随附第三方许可 | https://www.python.org/ |
| PySide6-Essentials / Shiboken6 | 6.8.3 | 本发行版选择 LGPLv3 | https://github.com/qtproject/pyside-pyside-setup/tree/v6.8.3 |
| Qt Core / Gui / Widgets 等 QtBase 模块 | 6.8.3 | 本发行版选择 LGPLv3；第三方代码遵循各自许可 | https://github.com/qt/qtbase/tree/v6.8.3 |
| Qt SVG / 图像插件（若由打包器带入） | 6.8.3 | LGPLv3；第三方代码遵循各自许可 | https://github.com/qt/qtsvg/tree/v6.8.3 和 https://github.com/qt/qtimageformats/tree/v6.8.3 |
| Pillow（包括随附图像编解码库） | 11.3.0 | HPND 和 Pillow 随附第三方许可 | https://github.com/python-pillow/Pillow/tree/11.3.0 |
| PyInstaller 启动器 | 6.16.0 | GPLv2+，带允许分发商业应用的启动器例外 | https://github.com/pyinstaller/pyinstaller/tree/v6.16.0 |
| Inno Setup（仅构建安装包） | 6.x | Inno Setup License | https://jrsoftware.org/isinfo.php |
| pytest（仅开发测试） | 8.4.2 | MIT | https://github.com/pytest-dev/pytest |

发行包的 `_internal/开源许可` 包含完整许可、版权和上游第三方声明。Qt、PySide、Shiboken 未作修改，其对应版本源码归档位于 `_internal/开源源码`，`sources.json` 记录上游地址和 SHA-256。Python 和 Pillow 也可从上游取得对应源码。

软件采用目录式动态库打包。用户可以在遵循 LGPL 的情况下替换 `_internal` 下的 Qt / PySide / Shiboken 动态库、为调试这些库的修改进行必要的逆向工程；软件许可不限制这些权利。替换时需保持对应 ABI 和模块目录，备份原文件后再操作。

如果发布者另加销售条款，请保留上述权利、许可文本、版权声明和源码归档。不要删掉 `_internal`、开源许可或开源源码目录后再销售。构建中下载依赖只发生在开发阶段，软件运行和整理图片无需联网。
