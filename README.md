# aitopschool-downloader

> 「真术相成」([ai.aitopschool.com](https://ai.aitopschool.com/)) 在线课程视频 CLI 批量/单集下载器。

纯 Python 标准库编写，**零外部依赖**（无需 `pip install`），开箱即用。跨平台支持 Linux、macOS 与 Windows。

---

## ✨ 特性

- 🚀 **零依赖开箱即用**：全套采用 Python 3 标准库（`urllib`、`argparse`、`pathlib` 等），克隆即用，无需安装第三方扩展。
- 🔑 **一步式全自动认证**：读取 `.env` 账号密码自动换取 JWT 登录凭据，并在本地缓存 Token（有效期内无需重复发起登录）。
- 📂 **智能目录管理**：
  - 默认自动保存至系统「下载」目录（跨平台兼容 Windows / Linux / macOS）。
  - 自动以课程标题作为分类子文件夹，视频文件按序号排列整齐。
- 📦 **批量与单集自如切换**：
  - 默认下载目标页面的**全部视频分集**。
  - 支持通过 `-e / --episode` 参数指定仅下载某单一集。
- ⚡ **断点续传与实时进度**：支持 HTTP Range 范围请求，中断后可自动断点续传；终端实时展示进度条、百分比、下载速率与剩余预估时间。
- 🛡️ **安全脱敏**：敏感凭据保存在本地 `.env`，已通过 `.gitignore` 排除，防止个人信息泄露。

---

## 🛠️ 环境准备

- Python 3.7 或更高版本

---

## 🚀 快速上手

### 1. 配置账号信息

复制环境变量模板文件 `.env.example` 并重命名为 `.env`：

```bash
cp .env.example .env
```

编辑 `.env` 文件，填入你的平台账号（手机号）与密码：

```env
AITOP_USERNAME=15500000000
AITOP_PASSWORD=your_password_here
```

> **提示**：`.env` 已在 `.gitignore` 中配置，请勿将其提交到公共版本库。

---

### 2. 下载课程视频

#### ① 默认下载指定页面的全部视频（保存至系统 Downloads 目录）
你可以直接提供页面的完整 URL 或仅提供课程 ID：

```bash
# 完整 URL
python3 aitop_downloader.py https://ai.aitopschool.com/21667

# 或仅输入课程 ID
python3 aitop_downloader.py 21667
```

#### ② 仅下载指定分集（例如第 1 集）
使用 `-e` 或 `--episode` 参数指定集数（从 1 开始）：

```bash
python3 aitop_downloader.py https://ai.aitopschool.com/21599 -e 1
```

#### ③ 自定义保存目录
使用 `-d` 或 `--download-directory` 参数指定文件存储路径：

```bash
# Linux / macOS
python3 aitop_downloader.py 21667 -d ./my_videos

# Windows CMD / PowerShell
python aitop_downloader.py 21667 -d "D:\Courses"
```

---

## 📖 命令行参数详解

运行 `python3 aitop_downloader.py -h` 可查看完整帮助信息：

```text
usage: aitop_downloader.py [-h] [-d DOWNLOAD_DIRECTORY] [-e EPISODE]
                           [--env-file ENV_FILE] [--no-cache]
                           url

真术相成 (ai.aitopschool.com) 视频批量/单集下载工具

positional arguments:
  url                   课程播放页面的 URL 链接或课程 post_id (例如: https://ai.aitopschool.com/21667 或 21667)

options:
  -h, --help            显示帮助信息并退出
  -d, --download-directory DOWNLOAD_DIRECTORY
                        视频下载保存的目标根目录 (默认: 系统的 Downloads 目录)
  -e, --episode EPISODE
                        仅下载指定分集编号 (从 1 开始)。若不提供此参数，默认下载当前页面的全部视频
  --env-file ENV_FILE   指定 .env 配置文件路径 (默认查找当前目录下的 .env)
  --no-cache            强制重新请求登录接口获取 Token，不使用本地已缓存的凭据
```

---

## ❓ 常见问题

1. **出现 `权限不足: 当前账号对页面 xxxxx 没有观看权限`？**
   - 该提示表示当前账号的 VIP 身份或班级权限未覆盖该课程，请确认你的账号是否已在网页端获得对应课程的观看权限。
2. **下载中断后如何继续？**
   - 重新执行相同的下载命令即可。程序会自动检测未下载完成的 `.part` 临时文件，并自动进行断点续传。已完整下载的文件会自动跳过。
3. **如何切换其他账号？**
   - 修改 `.env` 文件中的账号密码后，使用 `--no-cache` 参数运行一次即可刷新登录凭据：
     ```bash
     python3 aitop_downloader.py 21599 --no-cache
     ```

---

## 📄 开源许可

本项目遵循 [Apache 2.0 License](LICENSE)。仅供个人学习与离线复习使用，请勿用于商业传播。
