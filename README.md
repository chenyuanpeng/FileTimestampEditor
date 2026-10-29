# 文件时间属性修改工具

一个仅使用 Windows API 的桌面工具，可批量修改文件和文件夹的：

- 创建时间、修改时间、访问时间
- 鼠标拖放文件或文件夹到窗口（可一次拖入多项）
- 可选递归导入文件夹的所有层级子文件
- 固定时间，或为每个文件在指定起止时间内随机生成时间

它不会读取、写入或更改文件内容。未勾选的时间字段会保持不变。

## 运行

1. 在 Windows 安装 Python 3.10 或更高版本（安装时勾选 **Add Python to PATH**）。
2. 在此文件夹打开命令提示符并首次安装拖放组件：

   ```bat
   py -m pip install -r requirements.txt
   ```

3. 双击 `timestamp_editor.py`，或在此文件夹运行：

   ```bat
   py timestamp_editor.py
   ```

4. 点击“添加文件/文件夹”，或直接拖放到窗口；勾选“同时导入所有层级子文件”后添加/拖入文件夹即可递归导入。
5. 勾选要修改的时间类型，再选择“固定时间”或“随机时间段”。随机模式会给每个项目生成一个时间，并应用到该项目勾选的时间字段。
6. 时间按 `YYYY-MM-DD HH:MM:SS` 输入本地时间。点击“验证并预览”；确认无误后点击“执行修改”。

默认处理全部列表项；若在列表中选择了若干行，则只处理选中项。

## 权限与限制

- 对没有写入权限的路径、正在被其他程序独占锁定的项目，工具会在“结果”列报告具体错误并继续处理其他项目。
- 文件系统、云同步工具或安全策略可能会调整访问时间；操作完成后工具会重新读取实际值。
- 网络共享或 FAT/exFAT 等文件系统对时间精度和可修改字段的支持可能不同。
- 程序专为 Windows 设计，使用 `CreateFileW`、`GetFileTime` 和 `SetFileTime`，能够修改创建时间（`os.utime` 本身不能做到这一点）。

## 打包为 EXE

双击 `build_exe.bat`。首次运行会安装 PyInstaller，然后可执行文件位于：

`dist\FileTimestampEditor\FileTimestampEditor.exe`

也可以手动执行：

```bat
py -m pip install pyinstaller -r requirements.txt
py -m PyInstaller --noconfirm --clean --windowed --collect-all tkinterdnd2 --name FileTimestampEditor timestamp_editor.py
```

打包后的文件夹可整体复制到其他 Windows 电脑使用；单文件版本可把命令中的 `--windowed` 改为 `--windowed --onefile`。
