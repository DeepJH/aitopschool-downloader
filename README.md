# aitopschool-downloader

> 「真术相成」([ai.aitopschool.com](https://ai.aitopschool.com/)) 在线课程视频 CLI 批量/单集下载器。

纯 Python 标准库编写，**零外部依赖**（无需 `pip install`），开箱即用。跨平台支持 Linux、macOS 与 Windows。

---

## ✨ 特性

- 🚀 **多线程并行极速下载**：支持 `-j / --jobs`（默认 **8 线程**），单课多集、整期课程与全量批量均支持多任务并发提速。
- 🔍 **全站期数权限智能探针**：提供 `--check-perms` 命令，一键自动化并发检测账号对全站 30+ 个期数/分类课程的真实下载权限。
- 🗂️ **整期与全量批量归档**：支持按期数（`-t / --term`）或一键全量下载（`--all`），自动按 `<期数>/<课程标题>/<序号_分集标题>.mp4` 规范层级归档。
- 🩺 **媒体流完整性自动校验**：深度集成系统 `ffprobe` 流时长与结构校验（若无 ffprobe 自动平滑回退至 MP4 头部特征校验），损坏文件自动重下，已完整下载的文件自动校验并跳过。
- ⚡ **智能断点续传**：基于 HTTP Range 协议，支持 `.part` 临时文件断点续传；网络偶发波动自动静默重试，告别前功尽弃。
- 📦 **零依赖开箱即用**：全套采用 Python 3 标准库编写，无需 `pip install` 任何第三方包，跨平台兼容 Linux、macOS 与 Windows。
- 🔑 **全自动静默认证**：读取 `.env` 账号密码自动换取 JWT 登录凭据，本地智能缓存并自动续期。
- 🛡️ **敏感信息脱敏**：敏感账号凭据仅存放于本地 `.env`，已由 `.gitignore` 强制排除，杜绝泄露风险。

---

## 🛠️ 环境准备

本项目需要 **Python 3.7+** 环境。若你的系统尚未安装 Python，请参考以下方式快速安装：

### 1. Windows 系统

- **官方下载**：[Python 3.8.6 64-bit 安装包](https://www.python.org/ftp/python/3.8.6/python-3.8.6.exe)
- **国内加速**：[阿里云 Python 镜像源](https://mirrors.aliyun.com/python-release/windows/python-3.8.6.exe)

> **安装教程**：
> 1. 下载 `.exe` 安装程序并运行。
> 2. **务必勾选安装界面底部的「Add Python 3.8 to PATH」**（将 Python 添加到系统环境变量）。
> 3. 点击「Install Now」等待安装完成即可。

### 2. Linux 系统

根据你的发行版选择对应包管理命令安装：

- **Ubuntu / Debian 系（apt）**：
  ```bash
  sudo apt update && sudo apt install -y python3
  ```

- **Arch Linux / Manjaro 系（pacman）**：
  ```bash
  sudo pacman -Syu --needed python
  ```

### 3. 验证安装

打开终端或命令行（cmd / PowerShell），运行以下命令确认输出版本号即安装成功：

```bash
# Windows
python --version

# Linux / macOS
python3 --version
```

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

## ⚡ 进阶教程：期数批量下载与多线程并行

### 1. 自动检测账号对各个期数的下载权限 (`--check-perms`)
无需手动在浏览器翻页尝试，下载器会自动扫描站点全部课程分类并抽检课程，准确判定账号对哪些期数有实际下载权限：

```bash
python3 aitop_downloader.py --check-perms
```

输出示例：
```text
[*] 发现 38 个课程分类，正在以 8 线程并发检测账号权限...

================================================================================================
期数 / 分类名称                 分类ID  课程数  抽检PostID  权限状态      备注
------------------------------------------------------------------------------------------------
预习课程                        6       78      8702        [√] 有权限    正常有权
44期                            49      82      20195       [√] 有权限    正常有权
45期                            50      99      21667       [√] 有权限    正常有权
46期                            53      87      22445       [-] 无权限    需要: 46期学员
------------------------------------------------------------------------------------------------
检测完成: 共扫描 38 个课程分类，其中 3 个分类有权下载:
  * 预习课程 (分类ID: 6, 共 78 篇课程)
  * 44期 (分类ID: 49, 共 82 篇课程)
  * 45期 (分类ID: 50, 共 99 篇课程)
================================================================================================
```

---

### 2. 批量下载整期课程 (`-t / --term`)
使用 `-t` 或 `--term` 参数即可下载指定期数或分类下的**所有课程文章与全部视频分集**。支持输入期数数字、期数名称或期数页面链接：

```bash
# 方式 A: 输入纯期数数字
python3 aitop_downloader.py -t 45

# 方式 B: 输入期数中文全称
python3 aitop_downloader.py -t 45期

# 方式 C: 输入预习课程等非数字期数分类
python3 aitop_downloader.py -t 预习课程

# 方式 D: 直接粘贴期数的分类页面网址
python3 aitop_downloader.py -t https://ai.aitopschool.com/xsz/45qi
```

> **自动归档规范**：整期下载将自动按照两层目录归档，绝不会出现同名文件冲突：
> `~/Downloads/45期/20260730-技术面试/01-简历讲解.mp4`

---

### 3. 一键检测并下载全部有权限期数 (`--all`)
如果希望将当前账号拥有的所有期数一次性全部下载归档，使用 `--all` 参数即可自动先探针后下载：

```bash
python3 aitop_downloader.py --all
```

---

### 4. 调整多线程并发下载数 (`-j / --jobs`)
下载器**默认开启 8 线程并发下载**，无论是单课多集下载、整期批量下载还是 `--all` 全量下载，均支持并发加速。可通过 `-j` 或 `--jobs` 自定义线程数：

```bash
# 设置为 16 线程全力并发极速下载:
python3 aitop_downloader.py -t 45 -j 16

# 若在带宽较低或网络不稳定环境下，可适当调低并发:
python3 aitop_downloader.py -t 45 -j 4

# 设置为 1 线程时，将切换为单任务交互式平滑动态进度条:
python3 aitop_downloader.py 21599 -j 1
```

---

### 5. 磁盘空间保护与小批量试跑 (`--limit`)
当一期包含近百篇课程、体积极大且你的本地磁盘空间有限时，可通过 `--limit` 限制仅处理该期前 N 篇课程：

```bash
# 仅下载 45 期中的前 2 篇课程（用于快速验证或小批量同步）:
python3 aitop_downloader.py -t 45 --limit 2
```

---

### 6. 断点续传与媒体完整性双重校验机制
下载器内置全生命周期完整性校验保护：
1. **下载前比对**：若目标文件已存在，自动通过 `ffprobe` 快速校验流时长有效性及文件大小。校验通过则秒级跳过；若发现本地文件损坏或残缺，自动重下修复。
2. **下载中续传**：未完成的文件统一存放在 `.part` 临时缓存中，支持根据已下载字节数发起 HTTP Range 请求续传。
3. **下载后校验**：下载完成后重命名为 `.mp4`，并立刻进行完整性校验（有 `ffprobe` 时校验媒体编码有效性，若无则校验 MP4 头部特征），确保离线存储的文件绝对可用。

## 📖 命令行参数详解

运行 `python3 aitop_downloader.py -h` 可查看完整帮助信息：

```text
usage: aitop_downloader.py [-h] [--check-perms] [-t TERM] [--all] [-j JOBS]
                           [--limit LIMIT] [-d DOWNLOAD_DIRECTORY]
                           [-e EPISODE] [--env-file ENV_FILE] [--no-cache]
                           [url]

真术相成 (ai.aitopschool.com) 视频批量/单集下载工具

positional arguments:
  url                   课程播放页面的 URL 链接或课程 post_id (例如:
                        https://ai.aitopschool.com/21667 或 21667)

options:
  -h, --help            显示帮助信息并退出
  --check-perms         自动检测账号对各个期数/分类课程的下载权限并打印列表
  -t, --term TERM       下载指定期数/分类下的全部课程 (例如: 45, 45期, 预习课程 或 期数分类网址)
  --all                 自动检测账号有权限的全部期数，并批量下载所有课程
  -j, --jobs JOBS       并发下载/检测线程数 (默认: 8)
  --limit LIMIT         限制处理的课程数量 (用于小批量试跑测试，避免硬盘空间不足)
  -d, --download-directory DOWNLOAD_DIRECTORY
                        视频下载保存的目标根目录 (默认: 系统的 Downloads 目录)
  -e, --episode EPISODE
                        仅下载指定分集编号 (从 1 开始)。若不提供此参数，默认下载当前页面的全部视频
  --env-file ENV_FILE   指定 .env 配置文件路径 (默认查找当前目录下的 .env)
  --no-cache            强制刷新登录凭据，不使用本地已缓存的 Token
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
