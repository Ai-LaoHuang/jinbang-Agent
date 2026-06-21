# 金榜Agent — AI 高考志愿工作台

> 由 Ai老黄 制作 | GitHub: https://github.com/Ai-LaoHuang/jinbang-Agent

## 项目概述

AI 高考志愿填报工具。内置 14 省官方录取数据库（24.8 万条记录），融合张雪峰思维框架（社会筛子论、就业倒推法、阶层现实主义），三栏冲稳保分析。

## 技术架构

- **主程序**: `server.py` — 单文件，含 HTTP 服务端 + 完整 HTML 前端 + 内嵌 JS
- **数据库**: `admission_clean.db.gz`（压缩 29MB → 解压 143MB），SQLite，首次运行自动解压
- **桌面启动器**: `launcher.pyw` — tkinter GUI 窗口，含自动更新逻辑
- **安装程序**: `setup.py` — tkinter 安装向导
- **自动更新**: 通过 GitHub Raw URL 检查 `app_version.json` 和 `db_version.json`
- **Python 依赖**: 纯标准库，无需 pip install

## 关键文件

| 文件 | 说明 |
|------|------|
| `server.py` | 主程序（HTTP 服务器 + 前端 UI + JS） |
| `admission_clean.db.gz` | 录取数据库（14 省 24.8 万条） |
| `app_version.json` | 应用版本号（用于自更新） |
| `db_version.json` | 数据库版本号（用于数据更新） |
| `launcher.pyw` | Windows GUI 启动器（tkinter） |
| `setup.py` | Windows 安装程序（tkinter） |
| `打开我.html` | 浏览器入口页 |
| `启动.bat` | 命令行启动脚本 |

## 打包命令

```bash
# 主程序 EXE
pyinstaller --onefile --windowed --add-data "admission_clean.db.gz;." --add-data "db_version.json;." --name "金榜Agent" launcher.pyw

# 安装程序 EXE
pyinstaller --onefile --windowed --add-data "dist/金榜Agent.exe;." --add-data "打开我.html;." --name "金榜Agent-安装程序" setup.py
```

## 发布新版本

1. 修改 `app_version.json` 版本号和描述
2. 修改 `db_version.json` 版本号（如果数据有更新）
3. 替换 `admission_clean.db.gz`（如果数据有更新）
4. Git commit + push
5. 在 GitHub Releases 上传新版 `金榜Agent.exe`
6. 用户启动时自动检测并提示更新

## 数据库覆盖

上海、内蒙古、北京、安徽、山东、广东、江苏、河北、浙江、海南、湖北、湖南、重庆、黑龙江

## 注意事项

- 桌面 EXE 含自更新代码，旧版 EXE（无自更新）需手动替换一次
- GitHub 上的 `admission_clean.db.gz` 可能因 git LFS 无法直接 clone，需从 Releases 下载
- `app_version.json` 必须在 GitHub 存在才能触发自更新
