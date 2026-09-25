#!/usr/bin/env python3
"""
真术相成 (ai.aitopschool.com) 视频批量/单集 CLI 下载器
纯 Python 标准库编写，零外部依赖，支持 Linux/macOS/Windows。
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

BASE_URL = "https://ai.aitopschool.com"
LOGIN_API = f"{BASE_URL}/wp-json/jwt-auth/v1/token"
POST_VIDEOS_API = f"{BASE_URL}/wp-json/b2/v1/getPostVideos"
CATEGORIES_API = f"{BASE_URL}/wp-json/wp/v2/categories"
POSTS_API = f"{BASE_URL}/wp-json/wp/v2/posts"
EXCLUDED_CATEGORY_SLUGS = {
    "news", "zsnews", "hydt", "blog", "dating", "ukraine-1500", "gh", "paper"
}
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

PRINT_LOCK = threading.Lock()


def safe_log(msg: str, is_err: bool = False):
    """线程安全的控制台日志输出，包含时间戳 (并发方案 A)"""
    now_str = time.strftime("%H:%M:%S")
    with PRINT_LOCK:
        f = sys.stderr if is_err else sys.stdout
        print(f"[{now_str}] {msg}", file=f, flush=True)


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


def display_width(s: str) -> int:
    """计算字符串在终端中的显示宽度（中文字符占2列）"""
    return sum(2 if unicodedata.east_asian_width(ch) in ("F", "W") else 1 for ch in s)


def pad_string(s: str, target_width: int) -> str:
    """用空格填充字符串至指定终端显示宽度"""
    w = display_width(s)
    if w < target_width:
        return s + " " * (target_width - w)
    return s


def sanitize_filename(name: str) -> str:
    """清理文件名中跨平台非法字符"""
    name = re.sub(r'[\/*?:"<>|]', "_", name)
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


def verify_mp4_file(file_path: Path, expected_size: int = 0) -> tuple:
    """
    校验 MP4 文件完整性：
    1. 若提供了 expected_size，检查文件大小与 Content-Length 是否完全匹配；
    2. 优先调用系统 ffprobe 探测媒体流与时长有效性；
    3. 若无 ffprobe，则校验 MP4 头部 ftyp 魔数与文件完整性。
    """
    if not file_path.is_file():
        return False, "文件不存在"

    actual_size = file_path.stat().st_size
    if actual_size == 0:
        return False, "文件为空 (0 字节)"

    if expected_size > 0 and actual_size != expected_size:
        return False, f"文件大小不符 (期望: {expected_size} 字节, 实际: {actual_size} 字节)"

    ffprobe_bin = shutil.which("ffprobe")
    if ffprobe_bin:
        try:
            cmd = [
                ffprobe_bin,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(file_path),
            ]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if res.returncode == 0:
                duration_str = res.stdout.strip()
                if duration_str:
                    try:
                        dur = float(duration_str)
                        if dur > 0:
                            return True, f"ffprobe 校验通过 (时长: {dur:.1f}s)"
                    except ValueError:
                        pass
            err_msg = res.stderr.strip() or f"ffprobe 返回码 {res.returncode}"
            return False, f"视频流损坏: {err_msg}"
        except Exception:
            pass

    try:
        with open(file_path, "rb") as f:
            header = f.read(12)
            if len(header) >= 8 and header[4:8] == b"ftyp":
                return True, "MP4 文件头校验通过"
            return False, "非有效 MP4 格式 (缺少 ftyp 魔数)"
    except Exception as e:
        return False, f"读取文件异常: {e}"


class AitopClient:
    def __init__(self, username: str, password: str, token_cache_file: Path):
        self.username = username
        self.password = password
        self.token_cache_file = token_cache_file
        self.token = None

    def get_token(self, force_refresh: bool = False) -> str:
        """获取或刷新 JWT 认证凭据"""
        if not force_refresh and self.token:
            return self.token
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
        videos = result.get("videos") or []
        has_playable = any(bool(v.get("url")) for v in videos)

        # 表面显示无权但实际能下载时，也判定为有权
        if not allow and not has_playable:
            role_info = user_info.get("role", {})
            raise PermissionError(
                f"当前账号对页面 {post_id} 没有观看权限 (角色限制: {role_info})"
            )

        return result

    def fetch_course_categories(self) -> list:
        """获取站点所有包含文章的课程相关分类"""
        categories = []
        page = 1
        while True:
            url = f"{CATEGORIES_API}?per_page=100&page={page}"
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": DEFAULT_USER_AGENT,
                    "Referer": BASE_URL,
                },
            )
            try:
                with urllib.request.urlopen(req, timeout=15) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    if not data:
                        break
                    categories.extend(data)
                    total_pages = int(resp.headers.get("X-WP-TotalPages", 1))
                    if page >= total_pages:
                        break
                    page += 1
            except Exception:
                break

        course_cats = [
            c for c in categories
            if c.get("slug") not in EXCLUDED_CATEGORY_SLUGS and c.get("count", 0) > 0
        ]
        return sorted(course_cats, key=lambda x: x["id"])

    def fetch_category_posts(self, category_id: int) -> list:
        """获取指定分类/期数下的所有课程文章列表（自动分页）"""
        posts = []
        page = 1
        while True:
            url = f"{POSTS_API}?categories={category_id}&per_page=100&page={page}"
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": DEFAULT_USER_AGENT,
                    "Referer": BASE_URL,
                },
            )
            try:
                with urllib.request.urlopen(req, timeout=15) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    if not data:
                        break
                    posts.extend(data)
                    total_pages = int(resp.headers.get("X-WP-TotalPages", 1))
                    if page >= total_pages:
                        break
                    page += 1
            except urllib.error.HTTPError:
                break
            except Exception as e:
                print(f"[!] 获取分类 {category_id} 文章列表异常: {e}", file=sys.stderr)
                break
        return posts

    def find_category(self, query: str) -> dict:
        """根据用户输入的名称、期数、ID 或链接匹配分类"""
        categories = self.fetch_course_categories()
        q_str = str(query).strip().rstrip("/")

        if "aitopschool.com" in q_str:
            for c in categories:
                if c.get("link", "").rstrip("/") == q_str:
                    return c
            slug = q_str.split("/")[-1]
            for c in categories:
                if c.get("slug") == slug or urllib.parse.unquote(c.get("slug", "")) == urllib.parse.unquote(slug):
                    return c

        if q_str.isdigit():
            num = int(q_str)
            for c in categories:
                name = c.get("name", "")
                if name == f"{num}期" or name == f"{num}期课程":
                    return c
            for c in categories:
                if c.get("id") == num:
                    return c

        for c in categories:
            if q_str == c.get("name", ""):
                return c

        for c in categories:
            if q_str in c.get("name", ""):
                return c

        return None

    def check_category_permission(self, category: dict) -> dict:
        """
        抽检分类下的第一篇课程，检查是否有权下载。
        如果表面显示无权实际有权（能拿到视频直链），也判定为有权。
        """
        cat_id = category["id"]
        url = f"{POSTS_API}?categories={cat_id}&per_page=1"
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": DEFAULT_USER_AGENT,
                "Referer": BASE_URL,
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                posts = json.loads(resp.read().decode("utf-8"))
            if not posts:
                return {
                    "category": category,
                    "has_perm": False,
                    "sample_post_id": None,
                    "reason": "分类下无文章",
                }
            sample_post_id = posts[0]["id"]
            sample_title = posts[0].get("title", {}).get("rendered", "")
            try:
                post_data = self.fetch_post_videos(str(sample_post_id))
                videos = post_data.get("videos") or []
                has_playable = any(bool(v.get("url")) for v in videos)
                user_allow = post_data.get("user", {}).get("allow", False)
                if user_allow or has_playable:
                    reason = "正常有权" if user_allow else "表面受限但直链有效"
                    return {
                        "category": category,
                        "has_perm": True,
                        "sample_post_id": sample_post_id,
                        "sample_post_title": sample_title,
                        "video_count": len(videos),
                        "reason": reason,
                    }
                else:
                    return {
                        "category": category,
                        "has_perm": False,
                        "sample_post_id": sample_post_id,
                        "sample_post_title": sample_title,
                        "video_count": len(videos),
                        "reason": "无权观看 (视频链接为空)",
                    }
            except PermissionError as pe:
                raw_msg = str(pe).split(": ")[-1] if ": " in str(pe) else str(pe)
                clean_msg = re.sub(r"<[^>]+>", "", raw_msg).replace("['", "").replace("']", "").strip()
                return {
                    "category": category,
                    "has_perm": False,
                    "sample_post_id": sample_post_id,
                    "sample_post_title": sample_title,
                    "reason": f"需要: {clean_msg}" if clean_msg else "无权观看",
                }
        except Exception as e:
            return {
                "category": category,
                "has_perm": False,
                "sample_post_id": None,
                "reason": f"请求异常: {e}",
            }

    def check_all_permissions(self, workers: int = 8) -> list:
        """并发检测所有课程分类的下载权限"""
        categories = self.fetch_course_categories()
        self.get_token()
        print(f"[*] 发现 {len(categories)} 个课程分类，正在以 {workers} 线程并发检测账号权限...")
        results = []
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(self.check_category_permission, c) for c in categories]
            for f in futures:
                results.append(f.result())
        results.sort(key=lambda x: x["category"]["id"])
        return results


def download_single_video(
    url: str,
    dest_path: Path,
    title: str,
    index: int = 1,
    total: int = 1,
    quiet: bool = False,
    max_retries: int = 3,
) -> str:
    """
    单文件断点续传流式下载与完整性校验。
    返回状态: 'success' | 'skipped' | 'failed'
    """
    encoded_url = encode_media_url(url)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = dest_path.with_suffix(dest_path.suffix + ".part")

    headers = {
        "User-Agent": DEFAULT_USER_AGENT,
        "Referer": BASE_URL,
    }

    # 1. 探测远程文件大小
    remote_size = 0
    head_req = urllib.request.Request(
        encoded_url, headers=dict(headers, Range="bytes=0-0")
    )
    for _ in range(2):
        try:
            with urllib.request.urlopen(head_req, timeout=15) as resp:
                content_range = resp.headers.get("Content-Range")
                if content_range and "/" in content_range:
                    remote_size = int(content_range.split("/")[-1])
                else:
                    cl = resp.headers.get("Content-Length")
                    if cl:
                        remote_size = int(cl)
            break
        except Exception:
            time.sleep(0.5)

    # 2. 检查已下载的完整文件
    if dest_path.is_file():
        valid, reason = verify_mp4_file(dest_path, expected_size=remote_size)
        if valid:
            safe_log(
                f"[√ 已存在] [{index}/{total}] {dest_path.name} "
                f"({format_bytes(dest_path.stat().st_size)}) 完整性校验通过，跳过下载"
            )
            return "skipped"
        else:
            safe_log(
                f"[!] [{index}/{total}] {dest_path.name} 存在但损坏 ({reason})，将重新下载"
            )
            dest_path.unlink(missing_ok=True)

    # 3. 检查断点续传分片
    downloaded = 0
    if temp_path.exists():
        downloaded = temp_path.stat().st_size
        if remote_size > 0 and downloaded > remote_size:
            temp_path.unlink(missing_ok=True)
            downloaded = 0

    chunk_size = 128 * 1024
    for attempt in range(1, max_retries + 1):
        req_headers = dict(headers)
        if downloaded > 0:
            req_headers["Range"] = f"bytes={downloaded}-"
            mode = "ab"
            resume_msg = f" (续传: {format_bytes(downloaded)} / {format_bytes(remote_size)})"
        else:
            mode = "wb"
            resume_msg = ""

        if quiet:
            safe_log(f"[开始下载] [{index}/{total}] {title} -> {dest_path.name}{resume_msg}")
        else:
            print(f"  [-] 开始下载: {dest_path.name}{resume_msg}")

        start_time = time.time()
        last_print = 0.0
        bytes_in_session = 0

        try:
            req = urllib.request.Request(encoded_url, headers=req_headers)
            with urllib.request.urlopen(req, timeout=25) as resp, open(temp_path, mode) as out_f:
                if downloaded == 0 and remote_size == 0:
                    cl = resp.headers.get("Content-Length")
                    if cl:
                        remote_size = int(cl)

                while True:
                    chunk = resp.read(chunk_size)
                    if not chunk:
                        break
                    out_f.write(chunk)
                    downloaded += len(chunk)
                    bytes_in_session += len(chunk)

                    if not quiet:
                        now = time.time()
                        if now - last_print >= 0.25:
                            elapsed = max(now - start_time, 0.001)
                            speed = bytes_in_session / elapsed
                            if remote_size > 0:
                                pct = (downloaded / remote_size) * 100.0
                                eta = (remote_size - downloaded) / max(speed, 1.0)
                                eta_str = time.strftime("%H:%M:%S", time.gmtime(eta))
                                bar_len = 25
                                filled = int(bar_len * downloaded // remote_size)
                                bar = "=" * filled + (">" if filled < bar_len else "") + " " * (bar_len - filled - 1)
                                sys.stdout.write(
                                    f"\r  [{bar}] {pct:5.1f}% | "
                                    f"{format_bytes(downloaded)}/{format_bytes(remote_size)} | "
                                    f"{format_bytes(speed)}/s | ETA: {eta_str}"
                                )
                            else:
                                sys.stdout.write(
                                    f"\r  [下载中] {format_bytes(downloaded)} | {format_bytes(speed)}/s"
                                )
                            sys.stdout.flush()
                            last_print = now

            if not quiet:
                sys.stdout.write("\n")
                sys.stdout.flush()

            # 下载完成后替换正式文件名
            if temp_path.exists():
                temp_path.replace(dest_path)

            # 4. 执行文件完整性校验
            valid, reason = verify_mp4_file(dest_path, expected_size=remote_size)
            if not valid:
                dest_path.unlink(missing_ok=True)
                raise RuntimeError(f"文件完整性校验不通过: {reason}")

            total_elapsed = max(time.time() - start_time, 0.001)
            avg_speed = (bytes_in_session / total_elapsed) if bytes_in_session else 0
            safe_log(
                f"[√ 校验通过] [{index}/{total}] {dest_path.name} | "
                f"共 {format_bytes(downloaded)} | 耗时 {total_elapsed:.1f}s ({format_bytes(avg_speed)}/s) | {reason}"
            )
            return "success"

        except Exception as e:
            if not quiet:
                sys.stdout.write("\n")
                sys.stdout.flush()
            if attempt < max_retries:
                safe_log(
                    f"[!] [{index}/{total}] {dest_path.name} 网络波动 ({e})，正在第 {attempt}/{max_retries} 次重试..."
                )
                time.sleep(1.5)
                if temp_path.exists():
                    downloaded = temp_path.stat().st_size
            else:
                safe_log(f"[x 失败] [{index}/{total}] {dest_path.name} 下载失败: {e}", is_err=True)
                return "failed"


def run_download_batch(tasks: list, workers: int = 8) -> tuple:
    """
    并发批量下载任务清单。
    返回 (成功数, 跳过数, 失败数)
    """
    total = len(tasks)
    if total == 0:
        print("[!] 没有可下载的视频任务。")
        return 0, 0, 0

    workers = max(1, workers)
    single_bar_mode = (workers == 1 and total == 1)

    completed_lock = threading.Lock()
    stats = {"success": 0, "skipped": 0, "failed": 0}

    def worker_func(idx, task):
        url = task["url"]
        dest = task["dest_path"]
        title = task["title"]

        try:
            status = download_single_video(
                url=url,
                dest_path=dest,
                title=title,
                index=idx,
                total=total,
                quiet=not single_bar_mode,
            )
            with completed_lock:
                if status == "success":
                    stats["success"] += 1
                elif status == "skipped":
                    stats["skipped"] += 1
                else:
                    stats["failed"] += 1
        except Exception as e:
            with completed_lock:
                stats["failed"] += 1
            safe_log(f"[x 异常] [{idx}/{total}] {title}: {e}", is_err=True)

    if workers == 1:
        for idx, task in enumerate(tasks, 1):
            worker_func(idx, task)
    else:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(worker_func, idx, t) for idx, t in enumerate(tasks, 1)]
            for f in futures:
                f.result()

    return stats["success"], stats["skipped"], stats["failed"]


def download_term(
    client: AitopClient,
    term_query: str,
    download_dir: Path,
    workers: int = 8,
    limit: int = None,
) -> tuple:
    """
    下载指定期数/分类下的全部课程视频。
    目录结构: <download_dir>/<期数名称>/<课程标题>/<序号_分集标题>.mp4
    """
    cat = client.find_category(term_query)
    if not cat:
        print(f"[!] 错误: 未找到与 '{term_query}' 匹配的期数或分类！", file=sys.stderr)
        sys.exit(1)

    cat_name = cat.get("name", f"cat_{cat['id']}")
    print(f"\n[*] 正在准备期数/分类: {cat_name} (分类ID: {cat['id']})")

    chk = client.check_category_permission(cat)
    if not chk.get("has_perm"):
        print(
            f"[!] 权限不足: 当前账号无权下载分类 [{cat_name}] ({chk.get('reason')})",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"[*] 正在获取 [{cat_name}] 下的所有课程清单...")
    posts = client.fetch_category_posts(cat["id"])
    if not posts:
        print(f"[!] 分类 [{cat_name}] 下未找到任何课程文章。", file=sys.stderr)
        return 0, 0, 0

    if limit and limit > 0:
        posts = posts[:limit]
        print(f"[*] 已限制仅处理前 {limit} 篇课程 (共 {cat.get('count', len(posts))} 篇)")
    else:
        print(f"[*] 共获取到 {len(posts)} 篇课程文章，正在以 {workers} 线程并发解析视频链接...")

    post_videos_map = {}
    with ThreadPoolExecutor(max_workers=workers) as executor:
        def fetch_pv(p):
            pid = p["id"]
            raw_title = p.get("title", {}).get("rendered", f"course_{pid}")
            for attempt in range(1, 4):
                try:
                    vdata = client.fetch_post_videos(str(pid))
                    return pid, raw_title, vdata.get("videos") or []
                except Exception as e:
                    if attempt == 3:
                        print(f"[!] 解析课程 {pid} 视频信息失败: {e}", file=sys.stderr)
                    time.sleep(1)
            return pid, raw_title, []

        futures = [executor.submit(fetch_pv, p) for p in posts]
        for f in futures:
            pid, raw_title, vids = f.result()
            if vids:
                post_videos_map[pid] = (raw_title, vids)

    tasks = []
    term_dir = download_dir / sanitize_filename(cat_name)

    for pid, (raw_course_title, videos) in post_videos_map.items():
        course_dir = term_dir / sanitize_filename(raw_course_title)
        for ep_idx, item in enumerate(videos, 1):
            video_url = item.get("url")
            if not video_url:
                continue
            raw_ep_title = item.get("title") or f"episode_{ep_idx}"
            sanitized_ep = sanitize_filename(raw_ep_title)
            if re.match(r"^\d+", sanitized_ep):
                filename = f"{sanitized_ep}.mp4"
            else:
                filename = f"{ep_idx:02d}_{sanitized_ep}.mp4"

            tasks.append({
                "url": video_url,
                "dest_path": course_dir / filename,
                "title": f"{raw_course_title} - {raw_ep_title}",
            })

    print(f"[*] 解析完毕: 共提取到 {len(tasks)} 个有效视频下载任务")
    print(f"[*] 文件保存根目录: {term_dir.resolve()}")

    success, skipped, failed = run_download_batch(tasks, workers=workers)

    print("\n" + "=" * 60)
    print(f"期数 [{cat_name}] 处理完毕！")
    print(f"统计: 成功 {success} 个 | 跳过已完成 {skipped} 个 | 失败 {failed} 个")
    print(f"保存目录: {term_dir.resolve()}")
    print("=" * 60 + "\n")
    return success, skipped, failed


def download_all_allowed(
    client: AitopClient,
    download_dir: Path,
    workers: int = 8,
    limit: int = None,
):
    """检测账号所有有权限的期数，并批量下载全部课程"""
    print("\n[*] 正在启动全站期数权限检测...")
    results = client.check_all_permissions(workers=workers)
    allowed_categories = [r["category"] for r in results if r.get("has_perm")]

    if not allowed_categories:
        print("[!] 检测完成，但当前账号没有发现任何有下载权限的课程分类！", file=sys.stderr)
        return

    print(f"\n[+] 权限检测完成！共发现 {len(allowed_categories)} 个有权限的分类:")
    for c in allowed_categories:
        print(f"  * {c.get('name')} (ID: {c.get('id')}, 共 {c.get('count')} 篇课程)")

    print(f"\n[*] 即将开始下载上述所有有权限分类的课程...")
    total_s, total_sk, total_f = 0, 0, 0
    for idx, cat in enumerate(allowed_categories, 1):
        print(f"\n>>> [{idx}/{len(allowed_categories)}] 正在下载期数: {cat.get('name')} <<<")
        s, sk, f = download_term(
            client=client,
            term_query=str(cat["id"]),
            download_dir=download_dir,
            workers=workers,
            limit=limit,
        )
        total_s += s
        total_sk += sk
        total_f += f

    print("\n" + "=" * 60)
    print("[+] 全量下载任务结束！")
    print(f"总计: 成功 {total_s} 个 | 跳过 {total_sk} 个 | 失败 {total_f} 个")
    print(f"保存根目录: {download_dir.resolve()}")
    print("=" * 60 + "\n")


def print_permission_table(results: list) -> list:
    """打印期数/分类权限检测结果表格，并返回所有有权限的分类列表"""
    allowed_list = []
    print("\n" + "=" * 96)
    header = (
        pad_string("期数 / 分类名称", 32)
        + pad_string("分类ID", 8)
        + pad_string("课程数", 8)
        + pad_string("抽检PostID", 12)
        + pad_string("权限状态", 14)
        + "备注"
    )
    print(header)
    print("-" * 96)

    for r in results:
        cat = r["category"]
        name = cat.get("name", "")
        cid = str(cat.get("id", ""))
        count = str(cat.get("count", 0))
        sample_id = str(r.get("sample_post_id") or "-")
        has_perm = r.get("has_perm", False)
        status_str = "[√] 有权限" if has_perm else "[-] 无权限"
        reason = r.get("reason", "")
        if len(reason) > 30:
            reason = reason[:27] + "..."

        if has_perm:
            allowed_list.append(cat)

        line = (
            pad_string(name, 32)
            + pad_string(cid, 8)
            + pad_string(count, 8)
            + pad_string(sample_id, 12)
            + pad_string(status_str, 14)
            + reason
        )
        print(line)

    print("-" * 96)
    print(
        f"检测完成: 共扫描 {len(results)} 个课程分类，其中 {len(allowed_list)} 个分类有权下载:"
    )
    for c in allowed_list:
        print(f"  * {c.get('name')} (分类ID: {c.get('id')}, 共 {c.get('count')} 篇课程)")
    print("=" * 96 + "\n")
    return allowed_list


def main():
    parser = argparse.ArgumentParser(
        description="真术相成 (ai.aitopschool.com) 视频批量/单集下载工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 1. 自动检测账号有哪些期数的课程有权下载:
  python3 aitop_downloader.py --check-perms

  # 2. 下载指定期数/分类下的全部课程 (以 45 期为例，默认 8 线程并发下载):
  python3 aitop_downloader.py -t 45
  python3 aitop_downloader.py -t 45期 -d /path/to/save
  python3 aitop_downloader.py -t https://ai.aitopschool.com/xsz/45qi -j 8

  # 3. 自动检测所有有权限的期数并下载全部:
  python3 aitop_downloader.py --all
  python3 aitop_downloader.py --all -j 8

  # 4. 下载指定单个课程页面的全部视频 (默认并发下载):
  python3 aitop_downloader.py https://ai.aitopschool.com/21667

  # 5. 仅下载单个课程页面的第 1 集视频:
  python3 aitop_downloader.py 21599 -e 1
        """,
    )

    parser.add_argument(
        "url",
        nargs="?",
        default=None,
        help="课程播放页面的 URL 链接或课程 post_id (例如: https://ai.aitopschool.com/21667 或 21667)",
    )
    parser.add_argument(
        "--check-perms",
        action="store_true",
        help="自动检测账号对各个期数/分类课程的下载权限并打印列表",
    )
    parser.add_argument(
        "-t",
        "--term",
        default=None,
        help="下载指定期数/分类下的全部课程 (例如: 45, 45期, 预习课程 或 期数分类网址)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="自动检测账号有权限的全部期数，并批量下载所有课程",
    )
    parser.add_argument(
        "-j",
        "--jobs",
        type=int,
        default=8,
        help="并发下载/检测线程数 (默认: 8)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="限制处理的课程数量 (用于小批量试跑测试，避免硬盘空间不足)",
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

    # 1. 定位并读取 .env 配置
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
            "[!] 错误: 未找到登录账号与密码！\n"
            "    请在当前目录的 .env 文件中配置:\n"
            "    AITOP_USERNAME=你的手机号\n"
            "    AITOP_PASSWORD=你的密码\n"
            "    (参考 .env.example 模板文件)",
            file=sys.stderr,
        )
        sys.exit(1)

    # 2. 初始化客户端
    token_cache = Path(__file__).parent / ".aitop_token.json"
    client = AitopClient(username, password, token_cache)

    if args.no_cache:
        client.get_token(force_refresh=True)

    # 3. 处理权限检测指令
    if args.check_perms:
        results = client.check_all_permissions(workers=max(1, args.jobs))
        print_permission_table(results)
        sys.exit(0)

    # 4. 处理全量有权限期数批量下载
    if args.all:
        download_all_allowed(
            client=client,
            download_dir=Path(args.download_directory),
            workers=max(1, args.jobs),
            limit=args.limit,
        )
        sys.exit(0)

    # 5. 处理单期批量下载
    if args.term:
        download_term(
            client=client,
            term_query=args.term,
            download_dir=Path(args.download_directory),
            workers=max(1, args.jobs),
            limit=args.limit,
        )
        sys.exit(0)

    # 6. 处理单课程下载
    if not args.url:
        parser.print_help()
        sys.exit(0)

    try:
        post_id = parse_post_id(args.url)
    except Exception as e:
        print(f"[!] 错误: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"[*] 正在获取课程页面 {post_id} 的视频信息...")
    try:
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

    dest_dir = Path(args.download_directory) / course_title
    dest_dir.mkdir(parents=True, exist_ok=True)

    tasks = []
    for ep_num, item in target_items:
        raw_title = item.get("title") or f"episode_{ep_num}"
        sanitized_sub = sanitize_filename(raw_title)

        if re.match(r"^\d+", sanitized_sub):
            filename = f"{sanitized_sub}.mp4"
        else:
            filename = f"{ep_num:02d}_{sanitized_sub}.mp4"

        video_url = item.get("url")
        if not video_url:
            print(f"[!] 第 {ep_num} 节 [{raw_title}] 未找到视频下载链接，跳过。")
            continue

        tasks.append({
            "url": video_url,
            "dest_path": dest_dir / filename,
            "title": f"第{ep_num}节 {raw_title}",
        })

    success_count, skipped_count, fail_count = run_download_batch(
        tasks, workers=max(1, args.jobs)
    )

    print(f"\n==================================================")
    print(f"下载任务完成！成功: {success_count} 个，跳过: {skipped_count} 个，失败: {fail_count} 个")
    print(f"文件保存于: {dest_dir.resolve()}")
    print(f"==================================================\n")


if __name__ == "__main__":
    main()
