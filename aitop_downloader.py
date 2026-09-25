#!/usr/bin/env python3
"""
真术相成 (ai.aitopschool.com) 视频 CLI 下载器
纯 Python 标准库编写，零外部依赖，支持 Linux/macOS/Windows。
"""

import argparse
import json
import os
from pathlib import Path
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE_URL = "https://ai.aitopschool.com"
LOGIN_API = f"{BASE_URL}/wp-json/jwt-auth/v1/token"
POST_VIDEOS_API = f"{BASE_URL}/wp-json/b2/v1/getPostVideos"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def load_env(env_path: Path) -> dict:
    """加载 .env 配置文件（支持注释、引号与行尾空白）"""
    config = {}
    if not env_path.is_file():
        return config

    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, val = line.split("=", 1)
                key = key.strip()
                val = val.strip()
                if (val.startswith('"') and val.endswith('"')) or (
                    val.startswith("'") and val.endswith("'")
                ):
                    val = val[1:-1]
                config[key] = val
    return config


def get_default_download_dir() -> Path:
    """获取系统默认的下载目录（兼容 Linux / macOS / Windows）"""
    user_home = Path.home()
    downloads = user_home / "Downloads"
    return downloads


def sanitize_filename(name: str) -> str:
    """清理文件名中跨平台非法字符"""
    name = re.sub(r'[\\/*?:"<>|]', "_", name)
    name = name.strip().strip(".")
    return name or "unnamed"


def format_bytes(size: float) -> str:
    """格式化字节大小显示"""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024.0:
            return f"{size:.1f}{unit}"
        size /= 1024.0
    return f"{size:.1f}PB"


def parse_post_id(url_or_id: str) -> str:
    """从 URL 或纯数字中提取 post_id"""
    s = str(url_or_id).strip()
    match = re.search(r"(\d+)", s)
    if not match:
        raise ValueError(f"无法从输入提取课程 ID: {url_or_id}")
    return match.group(1)


def encode_media_url(raw_url: str) -> str:
    """对包含中文/特殊字符的媒体 URL 路径进行编码"""
    parts = urllib.parse.urlsplit(raw_url)
    quoted_path = urllib.parse.quote(parts.path)
    return urllib.parse.urlunsplit(
        (parts.scheme, parts.netloc, quoted_path, parts.query, parts.fragment)
    )


class AitopClient:
    def __init__(self, username: str, password: str, token_cache_file: Path):
        self.username = username
        self.password = password
        self.token_cache_file = token_cache_file
        self.token = None

    def get_token(self, force_refresh: bool = False) -> str:
        """获取或刷新 JWT 认证凭据"""
        if not force_refresh and self.token_cache_file.is_file():
            try:
                with open(self.token_cache_file, "r", encoding="utf-8") as f:
                    cache = json.load(f)
                    token = cache.get("token")
                    exp = cache.get("exp", 0)
                    user = cache.get("name", "")
                    if token and (time.time() < exp - 300):
                        print(f"[*] 使用本地缓存的认证 Token（用户: {user or self.username}）")
                        self.token = token
                        return token
            except Exception:
                pass

        if not self.username or not self.password:
            raise ValueError(
                "未在 .env 中找到账号密码，请设置 AITOP_USERNAME 和 AITOP_PASSWORD"
            )

        print(f"[*] 正在登录账号 {self.username} 获取认证凭据...")
        data = urllib.parse.urlencode({
            "nickname": "",
            "username": self.username,
            "password": self.password,
            "code": "",
            "img_code": "",
            "invitation_code": "",
            "token": "",
            "smsToken": "",
            "luoToken": "",
            "confirmPassword": "",
            "loginType": "",
        }).encode("utf-8")

        req = urllib.request.Request(
            LOGIN_API,
            data=data,
            headers={
                "User-Agent": DEFAULT_USER_AGENT,
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": BASE_URL,
            },
        )

        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                result = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            err_msg = e.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"登录失败 (HTTP {e.code}): {err_msg}")
        except Exception as e:
            raise RuntimeError(f"登录网络异常: {e}")

        token = result.get("token")
        if not token:
            msg = result.get("message") or str(result)
            raise RuntimeError(f"登录失败，未返回 Token: {msg}")

        user_name = result.get("name", self.username)
        exp = result.get("exp", int(time.time() + 86400 * 14))
        print(f"[+] 登录成功！欢迎用户: {user_name}")

        try:
            with open(self.token_cache_file, "w", encoding="utf-8") as f:
                json.dump({"token": token, "exp": exp, "name": user_name}, f, ensure_ascii=False)
        except Exception as e:
            print(f"[!] 警告: 保存 Token 缓存失败: {e}", file=sys.stderr)

        self.token = token
        return token

    def fetch_post_videos(self, post_id: str) -> dict:
        """获取目标页面的视频与权限信息"""
        token = self.get_token()
        data = urllib.parse.urlencode({"post_id": post_id}).encode("utf-8")
        req = urllib.request.Request(
            POST_VIDEOS_API,
            data=data,
            headers={
                "User-Agent": DEFAULT_USER_AGENT,
                "Authorization": f"Bearer {token}",
                "Referer": BASE_URL,
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )

        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                result = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 401 or e.code == 403:
                # Token 可能失效，重试一次刷新登录
                print("[!] Token 已失效，正在重新登录...")
                token = self.get_token(force_refresh=True)
                req.headers["Authorization"] = f"Bearer {token}"
                with urllib.request.urlopen(req, timeout=15) as resp:
                    result = json.loads(resp.read().decode("utf-8"))
            else:
                err_msg = e.read().decode("utf-8", errors="ignore")
                raise RuntimeError(f"获取视频信息失败 (HTTP {e.code}): {err_msg}")

        user_info = result.get("user") or {}
        allow = user_info.get("allow", False)
        if not allow:
            role_info = user_info.get("role", {})
            raise PermissionError(
                f"当前账号对页面 {post_id} 没有观看权限 (角色限制: {role_info})"
            )

        return result


def download_file(url: str, dest_path: Path, title: str):
    """
    单文件断点续传流式下载，附带终端动态进度条显示
    """
    encoded_url = encode_media_url(url)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = dest_path.with_suffix(dest_path.suffix + ".part")

    headers = {
        "User-Agent": DEFAULT_USER_AGENT,
        "Referer": BASE_URL,
    }

    # 检查远程文件大小 (HEAD 或 Range: bytes=0-0)
    total_size = 0
    head_req = urllib.request.Request(
        encoded_url, headers=dict(headers, Range="bytes=0-0")
    )
    try:
        with urllib.request.urlopen(head_req, timeout=15) as resp:
            content_range = resp.headers.get("Content-Range")
            if content_range and "/" in content_range:
                total_size = int(content_range.split("/")[-1])
            else:
                cl = resp.headers.get("Content-Length")
                if cl:
                    total_size = int(cl)
    except Exception:
        pass

    # 检查已下载的完整文件
    if dest_path.exists() and total_size > 0:
        if dest_path.stat().st_size == total_size:
            print(f"  [√] 文件已存在且完整，跳过: {dest_path.name} ({format_bytes(total_size)})")
            return
        elif dest_path.stat().st_size > total_size:
            dest_path.unlink()

    downloaded = 0
    if temp_path.exists():
        downloaded = temp_path.stat().st_size
        if total_size > 0 and downloaded > total_size:
            temp_path.unlink()
            downloaded = 0

    if downloaded > 0:
        headers["Range"] = f"bytes={downloaded}-"
        mode = "ab"
        print(f"  [*] 发现未完成分片，断点续传: {format_bytes(downloaded)} / {format_bytes(total_size)}")
    else:
        mode = "wb"

    req = urllib.request.Request(encoded_url, headers=headers)
    chunk_size = 128 * 1024  # 128KB 缓冲区
    start_time = time.time()
    last_print = 0.0

    print(f"  [-] 开始下载: {dest_path.name}")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp, open(temp_path, mode) as out_f:
            if downloaded == 0 and total_size == 0:
                cl = resp.headers.get("Content-Length")
                if cl:
                    total_size = int(cl)

            while True:
                chunk = resp.read(chunk_size)
                if not chunk:
                    break
                out_f.write(chunk)
                downloaded += len(chunk)

                now = time.time()
                if now - last_print >= 0.2:
                    elapsed = max(now - start_time, 0.001)
                    speed = (downloaded - (temp_path.stat().st_size if mode == 'ab' else 0)) / elapsed if mode != 'ab' else downloaded / elapsed
                    # 简化平均速率
                    speed = downloaded / elapsed

                    if total_size > 0:
                        pct = (downloaded / total_size) * 100.0
                        eta = (total_size - downloaded) / max(speed, 1.0)
                        eta_str = time.strftime("%H:%M:%S", time.gmtime(eta))
                        bar_len = 25
                        filled = int(bar_len * downloaded // total_size)
                        bar = "=" * filled + (">" if filled < bar_len else "") + " " * (bar_len - filled - 1)
                        progress_text = (
                            f"\r  [{bar}] {pct:5.1f}% | "
                            f"{format_bytes(downloaded)}/{format_bytes(total_size)} | "
                            f"{format_bytes(speed)}/s | ETA: {eta_str}"
                        )
                    else:
                        progress_text = (
                            f"\r  [下载中] {format_bytes(downloaded)} | {format_bytes(speed)}/s"
                        )

                    sys.stdout.write(progress_text)
                    sys.stdout.flush()
                    last_print = now

        # 完成后重命名
        if temp_path.exists():
            temp_path.replace(dest_path)

        total_elapsed = max(time.time() - start_time, 0.001)
        avg_speed = downloaded / total_elapsed
        sys.stdout.write(
            f"\r  [√] 完成: {dest_path.name} | 共 {format_bytes(downloaded)} | 耗时 {total_elapsed:.1f}s ({format_bytes(avg_speed)}/s)\n"
        )
        sys.stdout.flush()

    except Exception as e:
        sys.stdout.write("\n")
        raise RuntimeError(f"下载中断: {dest_path.name}: {e}")


def main():
    parser = argparse.ArgumentParser(
        description="真术相成 (ai.aitopschool.com) 视频批量/单集下载工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 下载指定课程页面的全部视频到默认系统下载目录:
  python3 aitop_downloader.py https://ai.aitopschool.com/21667

  # 指定自定义下载保存目录:
  python3 aitop_downloader.py 21667 -d /path/to/my_videos

  # 仅下载该页面的第 1 集视频:
  python3 aitop_downloader.py 21599 -e 1
        """,
    )

    parser.add_argument(
        "url",
        help="课程播放页面的 URL 链接或课程 post_id (例如: https://ai.aitopschool.com/21667 或 21667)",
    )
    parser.add_argument(
        "-d",
        "--download-directory",
        default=str(get_default_download_dir()),
        help=f"视频下载保存的目标根目录 (默认: 系统的 Downloads 目录, 当前为: {get_default_download_dir()})",
    )
    parser.add_argument(
        "-e",
        "--episode",
        type=int,
        default=None,
        help="仅下载指定分集编号 (从 1 开始)。若不提供此参数，则默认下载当前页面的全部视频",
    )
    parser.add_argument(
        "--env-file",
        default=".env",
        help="指定 .env 配置文件路径 (默认查找当前目录下的 .env)",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="强制刷新登录凭据，不使用本地已缓存的 Token",
    )

    args = parser.parse_args()

    # 1. 解析目标课程 post_id
    try:
        post_id = parse_post_id(args.url)
    except Exception as e:
        print(f"[!] 错误: {e}", file=sys.stderr)
        sys.exit(1)

    # 2. 定位并读取 .env 配置
    env_file = Path(args.env_file).resolve()
    if not env_file.is_file():
        script_env = Path(__file__).parent / ".env"
        if script_env.is_file():
            env_file = script_env

    env_config = load_env(env_file)
    username = env_config.get("AITOP_USERNAME") or os.environ.get("AITOP_USERNAME")
    password = env_config.get("AITOP_PASSWORD") or os.environ.get("AITOP_PASSWORD")

    if not username or not password:
        print(
            f"[!] 错误: 未找到登录账号与密码！\n"
            f"    请在当前目录的 .env 文件中配置:\n"
            f"    AITOP_USERNAME=你的手机号\n"
            f"    AITOP_PASSWORD=你的密码\n"
            f"    (参考 .env.example 模板文件)",
            file=sys.stderr,
        )
        sys.exit(1)

    # 3. 初始化客户端并获取课程信息
    token_cache = Path(__file__).parent / ".aitop_token.json"
    client = AitopClient(username, password, token_cache)

    try:
        if args.no_cache:
            client.get_token(force_refresh=True)
        print(f"[*] 正在获取课程页面 {post_id} 的视频信息...")
        post_data = client.fetch_post_videos(post_id)
    except PermissionError as e:
        print(f"[!] 权限不足: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"[!] 获取课程信息失败: {e}", file=sys.stderr)
        sys.exit(1)

    course_title = sanitize_filename(post_data.get("title") or f"course_{post_id}")
    videos = post_data.get("videos") or []

    if not videos:
        print(f"[!] 提示: 该页面未包含可下载的视频列表。", file=sys.stderr)
        sys.exit(0)

    print(f"\n==================================================")
    print(f"课程名称: {course_title}")
    print(f"课程 ID : {post_id}")
    print(f"分集数量: 共 {len(videos)} 节")
    print(f"保存目录: {Path(args.download_directory) / course_title}")
    print(f"==================================================")

    # 4. 筛选分集
    target_items = []
    if args.episode is not None:
        if args.episode < 1 or args.episode > len(videos):
            print(
                f"[!] 错误: 指定的分集 {args.episode} 超出有效范围 (1 ~ {len(videos)})",
                file=sys.stderr,
            )
            sys.exit(1)
        target_items = [(args.episode, videos[args.episode - 1])]
    else:
        target_items = [(idx + 1, item) for idx, item in enumerate(videos)]

    # 5. 执行下载循环
    dest_dir = Path(args.download_directory) / course_title
    dest_dir.mkdir(parents=True, exist_ok=True)

    success_count = 0
    fail_count = 0

    for ep_num, item in target_items:
        raw_title = item.get("title") or f"episode_{ep_num}"
        sanitized_sub = sanitize_filename(raw_title)

        # 若原标题未包含数字前缀，添加序号以保持排序整齐
        if re.match(r"^\d+", sanitized_sub):
            filename = f"{sanitized_sub}.mp4"
        else:
            filename = f"{ep_num:02d}_{sanitized_sub}.mp4"

        video_url = item.get("url")
        if not video_url:
            print(f"\n[!] 第 {ep_num} 节 [{raw_title}] 未找到视频下载链接，跳过。")
            fail_count += 1
            continue

        target_file = dest_dir / filename
        print(f"\n[{ep_num}/{len(videos)}] 正在处理: {raw_title}")
        try:
            download_file(video_url, target_file, raw_title)
            success_count += 1
        except KeyboardInterrupt:
            print("\n[!] 用户中断下载。")
            sys.exit(130)
        except Exception as e:
            print(f"  [x] 下载失败: {e}", file=sys.stderr)
            fail_count += 1

    print(f"\n==================================================")
    print(f"下载任务完成！成功: {success_count} 个，失败: {fail_count} 个")
    print(f"文件保存于: {dest_dir.resolve()}")
    print(f"==================================================")


if __name__ == "__main__":
    main()
