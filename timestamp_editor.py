"""Windows file/folder timestamp editor. Requires Python 3.10+ on Windows."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import os
import random
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    DND_AVAILABLE = True
except ImportError:
    DND_AVAILABLE = False

APP_TITLE = "文件时间属性修改工具"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
WINDOWS_EPOCH_SECONDS = 11_644_473_600
INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value
GENERIC_READ, GENERIC_WRITE = 0x80000000, 0x40000000
FILE_SHARE_READ, FILE_SHARE_WRITE, FILE_SHARE_DELETE = 1, 2, 4
OPEN_EXISTING, FILE_FLAG_BACKUP_SEMANTICS = 3, 0x02000000


class FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]


@dataclass(frozen=True)
class FileTimes:
    created: datetime
    accessed: datetime
    modified: datetime


def _api():
    if os.name != "nt":
        raise OSError("此程序只能在 Windows 上运行。")
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                      wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.GetFileTime.argtypes = [wintypes.HANDLE, ctypes.POINTER(FILETIME), ctypes.POINTER(FILETIME), ctypes.POINTER(FILETIME)]
    kernel32.GetFileTime.restype = wintypes.BOOL
    kernel32.SetFileTime.argtypes = [wintypes.HANDLE, ctypes.POINTER(FILETIME), ctypes.POINTER(FILETIME), ctypes.POINTER(FILETIME)]
    kernel32.SetFileTime.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes, kernel32.CloseHandle.restype = [wintypes.HANDLE], wintypes.BOOL
    return kernel32


def _raise_last_error(action: str, path: Path) -> None:
    error = ctypes.get_last_error()
    raise OSError(error, f"{action}失败: {path} ({ctypes.FormatError(error).strip()})")


def _to_datetime(value: FILETIME) -> datetime:
    ticks = (value.dwHighDateTime << 32) | value.dwLowDateTime
    return datetime.fromtimestamp(ticks / 10_000_000 - WINDOWS_EPOCH_SECONDS, tz=timezone.utc).astimezone()


def _to_filetime(value: datetime) -> FILETIME:
    ticks = round((value.astimezone(timezone.utc).timestamp() + WINDOWS_EPOCH_SECONDS) * 10_000_000)
    return FILETIME(ticks & 0xFFFFFFFF, ticks >> 32)


def _open(path: Path):
    kernel32 = _api()
    handle = kernel32.CreateFileW(str(path), GENERIC_READ | GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
                                  None, OPEN_EXISTING, FILE_FLAG_BACKUP_SEMANTICS if path.is_dir() else 0, None)
    if handle == INVALID_HANDLE_VALUE:
        _raise_last_error("打开文件", path)
    return kernel32, handle


def read_file_times(path: Path) -> FileTimes:
    kernel32, handle = _open(path)
    try:
        created, accessed, modified = FILETIME(), FILETIME(), FILETIME()
        if not kernel32.GetFileTime(handle, ctypes.byref(created), ctypes.byref(accessed), ctypes.byref(modified)):
            _raise_last_error("读取时间", path)
        return FileTimes(_to_datetime(created), _to_datetime(accessed), _to_datetime(modified))
    finally:
        kernel32.CloseHandle(handle)


def set_file_times(path: Path, created: datetime | None, accessed: datetime | None, modified: datetime | None) -> None:
    """Updates only non-None values; neither contents nor other timestamps are changed."""
    kernel32, handle = _open(path)
    try:
        native = [_to_filetime(value) if value else None for value in (created, accessed, modified)]
        pointers = [ctypes.byref(value) if value else None for value in native]
        if not kernel32.SetFileTime(handle, *pointers):
            _raise_last_error("修改时间", path)
    finally:
        kernel32.CloseHandle(handle)


def format_time(value: datetime) -> str:
    return value.strftime(DATE_FORMAT)


class TimestampEditor(ttk.Frame):
    def __init__(self, master: tk.Tk):
        super().__init__(master, padding=12)
        master.title(APP_TITLE)
        master.minsize(1080, 670)
        self.paths: dict[str, Path] = {}
        self.enabled = {name: tk.BooleanVar(value=False) for name in ("创建时间", "访问时间", "修改时间")}
        self.include_subfiles = tk.BooleanVar(value=False)
        self.mode = tk.StringVar(value="fixed")
        now = format_time(datetime.now().replace(microsecond=0))
        self.fixed_value, self.start_value, self.end_value = tk.StringVar(value=now), tk.StringVar(value=now), tk.StringVar(value=now)
        self._build()
        self.pack(fill="both", expand=True)

    def _build(self) -> None:
        toolbar = ttk.Frame(self)
        toolbar.pack(fill="x", pady=(0, 8))
        ttk.Button(toolbar, text="添加文件…", command=self.add_files).pack(side="left")
        ttk.Button(toolbar, text="添加文件夹…", command=self.add_folder).pack(side="left", padx=(6, 0))
        ttk.Checkbutton(toolbar, text="同时导入所有层级子文件", variable=self.include_subfiles).pack(side="left", padx=(12, 0))
        ttk.Button(toolbar, text="移除选中", command=self.remove_selected).pack(side="right")
        ttk.Button(toolbar, text="清空列表", command=self.clear).pack(side="right", padx=6)

        text = "可将文件或文件夹拖到窗口任意位置添加（含下方列表，可一次拖入多项）" if DND_AVAILABLE else "拖放功能需要安装 tkinterdnd2；可先使用“添加文件/文件夹”"
        self.drop_zone = ttk.Label(self, text=text, anchor="center", relief="groove", padding=7)
        self.drop_zone.pack(fill="x", pady=(0, 8))

        columns = ("type", "created", "accessed", "modified", "planned", "status")
        self.tree = ttk.Treeview(self, columns=columns, show="tree headings", selectmode="extended")
        self.tree.heading("#0", text="路径")
        self.tree.column("#0", width=330, minwidth=220)
        headings = {"type": "类型", "created": "当前创建", "accessed": "当前访问", "modified": "当前修改", "planned": "计划修改", "status": "结果"}
        widths = {"type": 65, "created": 145, "accessed": 145, "modified": 145, "planned": 145, "status": 180}
        for column in columns:
            self.tree.heading(column, text=headings[column])
            self.tree.column(column, width=widths[column], minwidth=60)
        self.tree.pack(fill="both", expand=True)
        if DND_AVAILABLE:
            # 整个窗口（含文件列表）均接受拖放，拖入文件或文件夹即添加
            for target in (self.winfo_toplevel(), self.drop_zone, self.tree):
                target.drop_target_register(DND_FILES)
                target.dnd_bind("<<Drop>>", self.drop_paths)
                target.dnd_bind("<<DropEnter>>", lambda *_args: self._set_drop_hint(True))
                target.dnd_bind("<<DropLeave>>", lambda *_args: self._set_drop_hint(False))

        options = ttk.LabelFrame(self, text="修改选项（未勾选的时间保持原样）", padding=10)
        options.pack(fill="x", pady=10)
        for index, name in enumerate(self.enabled):
            ttk.Checkbutton(options, text=name, variable=self.enabled[name], command=self.update_preview).grid(row=0, column=index, sticky="w", padx=(0, 18))
        ttk.Radiobutton(options, text="固定时间", variable=self.mode, value="fixed", command=self.update_preview).grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(options, textvariable=self.fixed_value, width=21).grid(row=1, column=1, sticky="w", pady=(8, 0))
        ttk.Radiobutton(options, text="随机时间段", variable=self.mode, value="random", command=self.update_preview).grid(row=2, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(options, textvariable=self.start_value, width=21).grid(row=2, column=1, sticky="w", pady=(6, 0))
        ttk.Label(options, text="至").grid(row=2, column=2, padx=6, pady=(6, 0))
        ttk.Entry(options, textvariable=self.end_value, width=21).grid(row=2, column=3, sticky="w", pady=(6, 0))
        ttk.Label(options, text=f"格式：{DATE_FORMAT}（本地时间；随机模式为每个项目生成一个时间）").grid(row=3, column=0, columnspan=5, sticky="w", pady=(8, 0))
        for variable in (self.fixed_value, self.start_value, self.end_value):
            variable.trace_add("write", lambda *_args: self.update_preview())

        actions = ttk.Frame(self)
        actions.pack(fill="x")
        ttk.Button(actions, text="刷新当前值", command=self.refresh).pack(side="left")
        ttk.Button(actions, text="验证并预览", command=self.validate_and_preview).pack(side="left", padx=6)
        ttk.Button(actions, text="执行修改", command=self.apply_changes).pack(side="right")
        self.summary = ttk.Label(actions, text="请添加文件或文件夹。")
        self.summary.pack(side="right", padx=12)

    def add_files(self) -> None:
        self.add_paths(Path(value) for value in filedialog.askopenfilenames(title="选择文件"))

    def add_folder(self) -> None:
        value = filedialog.askdirectory(title="选择文件夹")
        if value:
            self.add_paths((Path(value),))

    def drop_paths(self, event) -> str:
        self.add_paths(Path(value) for value in self.winfo_toplevel().tk.splitlist(event.data))
        return "break"

    def _set_drop_hint(self, active: bool) -> None:
        self.drop_zone.configure(relief="sunken" if active else "groove")

    def add_paths(self, paths) -> None:
        added, failures, folders = 0, 0, 0
        for path in paths:
            added += self.add_path(path)
            if path.is_dir():
                folders += 1
                if self.include_subfiles.get():
                    try:
                        for child in path.rglob("*"):
                            if child.is_file():
                                added += self.add_path(child)
                    except OSError:
                        failures += 1
        self.update_preview()
        if failures:
            self.summary.configure(text=f"已添加 {added} 项；部分子文件无法读取。")
        elif folders and not self.include_subfiles.get():
            self.summary.configure(text=f"已添加 {added} 项（含 {folders} 个文件夹）；如需连子文件一起导入，请先勾选“同时导入所有层级子文件”再拖入")

    def add_path(self, path: Path) -> int:
        try:
            path = path.resolve()
        except OSError:
            path = path.absolute()
        if path in self.paths.values():  # 按路径去重（self.paths 的键是树控件 ID）
            return 0
        try:
            times = read_file_times(path)
        except OSError as error:
            self.summary.configure(text=f"无法添加：{path.name}（{error.strerror or error}）")
            return 0
        item = self.tree.insert("", "end", text=str(path), values=("文件夹" if path.is_dir() else "文件", format_time(times.created), format_time(times.accessed), format_time(times.modified), "保持原样", "待处理"))
        self.paths[item] = path
        return 1

    def remove_selected(self) -> None:
        for item in self.tree.selection():
            self.tree.delete(item)
            self.paths.pop(item, None)
        self.update_preview()

    def clear(self) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.paths.clear()
        self.update_preview()

    def _requested_times(self, show_errors: bool = True) -> tuple[dict[str, datetime | None], str] | None:
        if not any(enabled.get() for enabled in self.enabled.values()):
            if show_errors:
                messagebox.showwarning(APP_TITLE, "请至少勾选一个要修改的时间。")
            return None
        try:
            if self.mode.get() == "fixed":
                value = datetime.strptime(self.fixed_value.get().strip(), DATE_FORMAT).astimezone()
                return ({name: value if enabled.get() else None for name, enabled in self.enabled.items()}, "固定时间")
            start = datetime.strptime(self.start_value.get().strip(), DATE_FORMAT).astimezone()
            end = datetime.strptime(self.end_value.get().strip(), DATE_FORMAT).astimezone()
            if end < start:
                raise ValueError("结束时间必须晚于或等于开始时间。")
            return ({name: start if enabled.get() else None for name, enabled in self.enabled.items()}, "随机时间段")
        except ValueError as error:
            if show_errors:
                messagebox.showerror(APP_TITLE, f"时间输入无效：{error}\n格式：{DATE_FORMAT}")
            return None

    def _times_for_target(self, requested: dict[str, datetime | None]) -> dict[str, datetime | None]:
        if self.mode.get() == "fixed":
            return requested
        start = datetime.strptime(self.start_value.get().strip(), DATE_FORMAT).astimezone()
        end = datetime.strptime(self.end_value.get().strip(), DATE_FORMAT).astimezone()
        random_time = datetime.fromtimestamp(random.randint(int(start.timestamp()), int(end.timestamp()))).astimezone()
        return {name: random_time if value else None for name, value in requested.items()}

    def update_preview(self) -> None:
        configuration = self._requested_times(show_errors=False)
        planned = "输入无效" if configuration is None else ("将随机修改" if self.mode.get() == "random" else "将修改")
        for item in self.tree.get_children():
            values = list(self.tree.item(item, "values"))
            values[4] = planned
            self.tree.item(item, values=values)
        self.summary.configure(text=f"已添加 {len(self.paths)} 项；{planned}")

    def validate_and_preview(self) -> None:
        configuration = self._requested_times()
        if configuration:
            _, label = configuration
            self.summary.configure(text=f"验证通过：{label}；将处理 {len(self.paths)} 项。")
            self.update_preview()

    def refresh(self) -> None:
        for item, path in list(self.paths.items()):
            try:
                times = read_file_times(path)
                values = list(self.tree.item(item, "values"))
                values[1:4] = [format_time(times.created), format_time(times.accessed), format_time(times.modified)]
                values[5] = "已刷新"
                self.tree.item(item, values=values)
            except OSError as error:
                self._set_status(item, f"错误：{error.strerror or error}")
        self.update_preview()

    def _set_status(self, item: str, status: str) -> None:
        values = list(self.tree.item(item, "values"))
        values[5] = status
        self.tree.item(item, values=values)

    def apply_changes(self) -> None:
        configuration = self._requested_times()
        if configuration is None:
            return
        if not self.paths:
            messagebox.showwarning(APP_TITLE, "请先添加文件或文件夹。")
            return
        requested, label = configuration
        targets = self.tree.selection() or tuple(self.paths)
        if not messagebox.askyesno(APP_TITLE, f"将以{label}修改 {len(targets)} 项。文件内容不会被修改。是否继续？"):
            return
        successes, failures = 0, 0
        for item in targets:
            try:
                times_to_apply = self._times_for_target(requested)
                set_file_times(self.paths[item], times_to_apply["创建时间"], times_to_apply["访问时间"], times_to_apply["修改时间"])
                times = read_file_times(self.paths[item])
                values = list(self.tree.item(item, "values"))
                values[1:4] = [format_time(times.created), format_time(times.accessed), format_time(times.modified)]
                values[4], values[5] = "已应用", "成功"
                self.tree.item(item, values=values)
                successes += 1
            except OSError as error:
                self._set_status(item, f"失败：{error.strerror or error}")
                failures += 1
        self.summary.configure(text=f"完成：成功 {successes} 项，失败 {failures} 项")
        messagebox.showinfo(APP_TITLE, f"处理完成。\n成功：{successes}\n失败：{failures}")


def main() -> None:
    root = TkinterDnD.Tk() if DND_AVAILABLE else tk.Tk()
    if not DND_AVAILABLE:
        messagebox.showwarning(APP_TITLE, "未检测到 tkinterdnd2，拖放功能不可用。\n请执行：py -m pip install -r requirements.txt")
    try:
        ttk.Style().theme_use("vista")
    except tk.TclError:
        pass
    TimestampEditor(root)
    root.mainloop()


if __name__ == "__main__":
    main()
