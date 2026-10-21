# 界面约定

主窗口固定为 453×520，禁用最大化，保留最小化和关闭。集中显示输入、输出、质量、格式、转换和底部状态。路径栏分别提供文件、文件夹入口，不设置二级选择菜单。长路径裁切，悬停显示完整内容。

质量分为五挡，当前档位使用更大的滑块与加粗文字。输出格式显示名称和扩展名；自动模式显示图片与视频的目标类型。转换按钮保持 160×48。

太阳 / 月亮切换主题，i 显示版权与开源信息，齿轮打开设置，所有图标提供悬停提示。工具栏使用 Lucide SVG，滑块圆圈使用独立 SVG，均按显示尺寸渲染并缓存，不缩放预制的小位图。Windows 原生标题栏跟随主题设置。

关于窗口仅显示软件名称、版本、版权和 MIT 标识。底部“开源组件”按钮打开组件列表和第三方许可原文，每个组件一行，多种许可放在同一组件下。本应用的完整 MIT 文本保留在软件目录的 LICENSE 文件中，不列入第三方组件。使用方法和格式限制放在设置提示与使用文档中。

设置页保留常用开关，文件筛选、视频编码器和帧率放在高级设置中。设置支持保存和取消；首次语言依据系统界面语言确定，手动选择后保留。

运行期间禁用会改变任务输入的操作，底部显示真实事件驱动的进度。状态行可以打开逐个文件的结果；错误使用红色，完成使用绿色，处理状态使用主题强调色。长消息在一行内截断，完整消息可悬停或打开详情查看。

原有完整参数界面可用 `--classic` 打开，默认入口为轻量界面。

参考：

- [Windows：按钮文字与状态](https://learn.microsoft.com/en-us/windows/apps/develop/ui/controls/buttons)
- [Windows：界面文案](https://learn.microsoft.com/en-us/windows/apps/design/style/writing-style)
- [Windows：原生窗口深浅主题](https://learn.microsoft.com/en-us/windows/apps/desktop/modernize/apply-windows-themes)
- [HandBrake：队列](https://handbrake.fr/docs/en/latest/advanced/queue.html)
- [ImageOptim：文件列表与设置](https://imageoptim.com/en/)
- [GNOME：关于窗口的内容与许可信息](https://gnome.pages.gitlab.gnome.org/libadwaita/doc/main/class.AboutDialog.html)
- [GIMP：关于窗口与许可证入口](https://docs.gimp.org/3.0/en/gimp-about-dialog.html)
