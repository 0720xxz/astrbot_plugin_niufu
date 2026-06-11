import json
import asyncio
import re
import os
import sys
import tempfile
from pathlib import Path
from datetime import datetime
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Star, Context, register
from astrbot.api import logger
import aiohttp
import astrbot.api.message_components as Comp
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import (
    PLUGIN_DIR, DATA_DIR, DEFAULT_SERVER_DATA,
    TOGGLE_FILE, SERVER_DATA_FILE, BLACKLIST_FILE, GROUP_BINDING_FILE,
    FUZZY_TOGGLE_FILE, GROUP_NOSLASH_FILE, SERVER_HISTORY_FILE,
    SERVER_CACHE_FILE, COMMAND_LOGS_FILE, ERROR_LOGS_FILE,
    RAW_RESPONSES_FILE, PLAYER_LOGS_FILE,
    GLOBAL_DATA,
    load_server_data, save_server_data,
    _get_toggle_key,
    load_toggle_state, save_toggle_state,
    load_blacklist, save_blacklist,
    load_group_bindings, save_group_bindings,
    load_fuzzy_toggle, save_fuzzy_toggle, is_fuzzy_enabled,
    load_group_noslash, save_group_noslash, is_noslash_enabled,
    load_server_history, save_server_history,
    load_server_cache, save_server_cache,
    load_command_logs, save_command_logs,
    load_error_logs, save_error_logs,
    load_raw_responses, save_raw_responses,
    load_player_logs, save_player_logs,
)


API_BASE = "https://api.scplist.kr/api/servers/"
API_CN = "https://public-lobby-api.scpslgame.top/api?key=scpslgame_cn"
API_CN_TTL = 60
API_MH = "https://scp.manghui.net/list/"
API_MH_TTL = 120

@register("astrbot_plugin_niufu", "内战狂热爱好者", "Dynamic Server Framework", "4.1")
class douUniversalServerPlugin(Star):
    _pending_tasks: set = set()

    def __init__(self, context: Context):
        super().__init__(context)
        self._pending_tasks = set()
        self.toggle_state = load_toggle_state()
        self.blacklist = load_blacklist()
        self.group_bindings = load_group_bindings()
        self.fuzzy_toggle = load_fuzzy_toggle()
        self.group_noslash = load_group_noslash()
        self.cache = {}
        self.refresh_task = None
        self.current_interval = GLOBAL_DATA["refresh_interval_min"]
        self.session = None
        self.error_logs: list[dict] = load_error_logs()
        self.error_log_max = GLOBAL_DATA.get("error_log_max", 50)
        self._errlog_dirty = False
        self.command_logs = load_command_logs()
        self._cmdlog_dirty = False
        self.server_history: dict[str, list] = load_server_history()
        self.history_max = GLOBAL_DATA.get("history_max", 240)
        self.history_interval = GLOBAL_DATA.get("history_interval", 120)
        self.history_count = GLOBAL_DATA.get("history_count", 240)
        self.server_cache: dict[str, dict] = load_server_cache()
        self.cache_ttl = GLOBAL_DATA.get("cache_ttl", 60)
        self.last_history_save = datetime.now()
        self.alert_cooldown: dict[str, datetime] = {}
        self.alert_cooldown_min = GLOBAL_DATA.get("alert_cooldown_min", 10)
        self._last_alert_send: datetime | None = None
        self._alert_send_interval = GLOBAL_DATA.get("alert_send_interval", 60)
        self.last_player_counts: dict[str, int] = {}
        self.last_report_time: dict[str, datetime] = {}
        self.alert_drop_pct = GLOBAL_DATA.get("alert_drop_pct", 50)
        self.alert_min_players = GLOBAL_DATA.get("alert_min_players", 20)
        self._was_zero: dict[str, bool] = {}
        self._alerted: dict[str, str] = {}
        self._stable_count: dict[str, int] = {}
        self._adaptive_locked = False
        self._raw_dirty = False
        self._plogs_dirty = False
        self._cache_dirty = False
        self._h_dirty = False
        self._temp_seq = 0
        self.alert_task = None
        self.report_task = None
        self._bot = None
        self.retract_seconds = GLOBAL_DATA.get("retract_seconds", 30)
        self._session_lock = asyncio.Lock()
        self._font_cache = {}
        self._bg_images = self._scan_bg_images()
        self._data_lock = asyncio.Lock()
        self._cn_cache: dict[int, dict] = {}
        self._cn_cache_ts = 0.0
        self._mh_cache: dict[int, dict] = {}
        self._mh_cache_ts = 0.0
        self._active_source = "主源"

    def _scan_bg_images(self):
        import random as _random
        desktop = Path.home() / "Desktop"
        imgs = []
        for ext in ("*.jpg", "*.jpeg", "*.png", "*.bmp"):
            for p in desktop.glob(ext):
                imgs.append(p)
        return imgs

    def _apply_background(self, img: Image.Image) -> Image.Image:
        import random as _random
        if not self._bg_images:
            return img
        try:
            bg_path = _random.choice(self._bg_images)
            bg = Image.open(bg_path).convert("RGB")
            bg = bg.resize(img.size, Image.LANCZOS)
            white = Image.new("RGB", img.size, (255, 255, 255))
            blended = Image.blend(white, bg, 0.3)
            blended.paste(img, (0, 0), img if img.mode == "RGBA" else None)
            return blended
        except Exception:
            return img

    async def _atomic_save(self):
        async with self._data_lock:
            save_server_data(GLOBAL_DATA)

    def _create_tracked_task(self, coro) -> asyncio.Task:
        task = asyncio.create_task(coro)
        if not hasattr(self, '_pending_tasks'):
            self._pending_tasks = set()
        self._pending_tasks.add(task)
        task.add_done_callback(self._pending_tasks.discard)
        return task

    async def _get_session(self):
        if self.session is None or self.session.closed:
            async with self._session_lock:
                if self.session is None or self.session.closed:
                    headers = {
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AstrBot-SCP-Query/4.1",
                        "Accept": "application/json",
                        "Accept-Encoding": "gzip, deflate",
                    }
                    self.session = aiohttp.ClientSession(headers=headers)
        return self.session

    async def _fetch(self, url, sid=None):
        now_ts = datetime.now().timestamp()
        cache_key = sid if sid else url
        if cache_key in self.server_cache:
            entry = self.server_cache[cache_key]
            age = now_ts - entry.get("ts", 0)
            if age < self.cache_ttl:
                cached_data = entry.get("data")
                if cached_data:
                    cp = str(cached_data.get("players", ""))
                    if cp == "0" or cp.startswith("0/"):
                        cached_data = None
                if cached_data is not None:
                    if age > self.cache_ttl * 0.4:
                        try:
                            session = await self._get_session()
                            async with session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                                if resp.status == 200:
                                    data = await resp.json()
                                    self.server_cache[cache_key] = {"ts": now_ts, "data": data}
                                    self._cache_dirty = True
                                    self._store_raw_response(sid, data)
                                    return data
                        except Exception as e:
                            logger.debug(f"non-critical: {e}")
                            pass
                    return cached_data
        try:
            session = await self._get_session()
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    self.server_cache[cache_key] = {"ts": now_ts, "data": data}
                    if len(self.server_cache) > 100:
                        stale = sorted(self.server_cache.keys(), key=lambda k: self.server_cache[k].get("ts", 0))[:-50]
                        for k in stale:
                            self.server_cache.pop(k, None)
                    self._cache_dirty = True
                    self._store_raw_response(sid, data)
                    return data
                else:
                    msg = f"API 返回非 200 状态码: {resp.status} - {url}"
                    logger.warning(f"[服务器框架] {msg}")
                    self._log_error(msg)
        except Exception as e:
            msg = f"获取服务器数据失败: {e} - {url}"
            logger.warning(f"[服务器框架] {msg}")
            self._log_error(msg)
        if sid is not None:
            if self._active_source != "主源":
                preferred = await (self._fetch_cn(sid) if self._active_source == "备份1" else self._fetch_manghui(sid))
                if preferred is not None:
                    self.server_cache[sid] = {"ts": datetime.now().timestamp(), "data": preferred}
                    self._cache_dirty = True
                    return preferred
            for fallback_fn in (self._fetch_cn, self._fetch_manghui):
                fallback = await fallback_fn(sid)
                if fallback is not None:
                    self.server_cache[sid] = {"ts": datetime.now().timestamp(), "data": fallback}
                    self._cache_dirty = True
                    return fallback
        return None

    async def _fetch_cn(self, sid: str):
        import base64
        now_ts = datetime.now().timestamp()
        if not self._cn_cache or (now_ts - self._cn_cache_ts) > API_CN_TTL:
            try:
                session = await self._get_session()
                async with session.get(API_CN, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status == 200:
                        raw = await resp.json()
                        servers = raw.get("data", []) if isinstance(raw, dict) else []
                        new_cache = {}
                        for s in servers:
                            sid_val = s.get("serverId")
                            if sid_val is None:
                                continue
                            players_str = str(s.get("players", "0/0"))
                            p = int(players_str.split("/")[0]) if "/" in players_str else 0
                            m = int(players_str.split("/")[1]) if "/" in players_str else 0
                            info_raw = s.get("info", "")
                            try:
                                info_decoded = base64.b64decode(info_raw).decode("utf-8", errors="replace")
                                info_decoded = re.sub(r"<[^>]+>", "", info_decoded).strip()
                                info_decoded = re.sub(r"\s+", " ", info_decoded)
                            except Exception:
                                info_decoded = ""
                            new_cache[sid_val] = {
                                "ip": s.get("ip", ""),
                                "port": s.get("port", ""),
                                "players": players_str,
                                "max_players": m,
                                "online": True,
                                "info": info_decoded,
                                "version": s.get("version", ""),
                                "modded": s.get("modded", False),
                                "distance": s.get("distance", 0),
                            }
                        self._cn_cache = new_cache
                        self._cn_cache_ts = now_ts
                        logger.info(f"[服务器框架] CN API缓存已刷新: {len(new_cache)}个服务器")
            except Exception as e:
                logger.debug(f"non-critical: _fetch_cn refresh failed: {e}")
                pass
        sid_int = int(sid) if sid else 0
        return self._cn_cache.get(sid_int)

    async def _fetch_manghui(self, sid: str):
        now_ts = datetime.now().timestamp()
        if not self._mh_cache or (now_ts - self._mh_cache_ts) > API_MH_TTL:
            try:
                session = await self._get_session()
                async with session.get(API_MH, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status == 200:
                        html = await resp.text()
                        new_cache = {}
                        row_pattern = re.compile(r'<tr[^>]*>\s*(.*?)\s*</tr>', re.DOTALL)
                        cell_pattern = re.compile(r'<td[^>]*>(.*?)</td>', re.DOTALL)
                        tag_strip = re.compile(r'<[^>]+>')
                        ws_collapse = re.compile(r'\s+')
                        for row_match in row_pattern.finditer(html):
                            cells = cell_pattern.findall(row_match.group(1))
                            if len(cells) < 6:
                                continue
                            sid_str = tag_strip.sub('', cells[0]).strip()
                            ip_port = tag_strip.sub('', cells[1]).strip()
                            desc = tag_strip.sub('', cells[2]).strip()
                            desc = ws_collapse.sub(' ', desc)
                            players_str = tag_strip.sub('', cells[3]).strip()
                            if not sid_str.isdigit():
                                continue
                            sid_val = int(sid_str)
                            ip = ""
                            port = ""
                            if ":" in ip_port:
                                parts = ip_port.rsplit(":", 1)
                                ip = parts[0]
                                port = parts[1]
                            p = 0
                            m = 0
                            if "/" in players_str:
                                pp = players_str.split("/")
                                p = int(pp[0]) if pp[0].isdigit() else 0
                                m = int(pp[1]) if pp[1].isdigit() else 0
                            new_cache[sid_val] = {
                                "ip": ip,
                                "port": port,
                                "players": players_str,
                                "max_players": m,
                                "online": True,
                                "info": desc,
                                "version": "",
                                "modded": "Exiled" in (tag_strip.sub('', cells[5]) if len(cells) > 5 else ""),
                                "distance": 0,
                            }
                        self._mh_cache = new_cache
                        self._mh_cache_ts = now_ts
                        logger.info(f"[服务器框架] MH缓存已刷新: {len(new_cache)}个CN服务器")
            except Exception as e:
                logger.debug(f"non-critical: _fetch_manghui refresh failed: {e}")
                pass
        sid_int = int(sid) if sid else 0
        return self._mh_cache.get(sid_int)

    async def _search_servers(self, keyword: str, max_results: int = 30):
        kw = keyword.lower()
        await asyncio.gather(
            self._fetch_cn("0"), self._fetch_manghui("0"), return_exceptions=True
        )
        seen = set()
        results = []
        for cache in (self._cn_cache, self._mh_cache):
            for sid, srv in cache.items():
                if sid in seen:
                    continue
                info = (srv.get("info") or "").lower()
                ip = (srv.get("ip") or "").lower()
                if kw in info or kw in ip:
                    seen.add(sid)
                    name = info.split(" ")[0][:30] if info else str(sid)
                    for sep in (" ", "】", "]", "|", ">"):
                        if sep in info and len(info.split(sep)[0]) < 30:
                            name = info.split(sep)[0].strip()
                            break
                    results.append({
                        "id": sid,
                        "ip": srv.get("ip", ""),
                        "port": srv.get("port", ""),
                        "name": name,
                        "info": (info[:120] + "...") if len(info) > 120 else info,
                        "version": srv.get("version", ""),
                        "players": srv.get("players", "?/?"),
                        "modded": srv.get("modded", False),
                    })
        results.sort(key=lambda r: r["id"])
        return results[:max_results]

    def _store_raw_response(self, sid, data):
        if not hasattr(self, '_raw_data'):
            self._raw_data = load_raw_responses()
        key = sid or "unknown"
        if key not in self._raw_data:
            self._raw_data[key] = []
        self._raw_data[key].append({"time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "data": data})
        if len(self._raw_data[key]) > 200:
            self._raw_data[key] = self._raw_data[key][-200:]
        self._raw_dirty = True

    def _store_player_log(self, sid, display_name, players):
        if not hasattr(self, '_plog_data'):
            self._plog_data = load_player_logs()
        key = sid or display_name
        if key not in self._plog_data:
            self._plog_data[key] = []
        self._plog_data[key].append({"time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "name": display_name, "players": str(players)})
        if len(self._plog_data[key]) > 500:
            self._plog_data[key] = self._plog_data[key][-500:]
        self._plogs_dirty = True

    def _log_error(self, msg: str):
        self.error_logs.append({"time": datetime.now().strftime("%m-%d %H:%M:%S"), "msg": msg})
        if len(self.error_logs) > self.error_log_max:
            self.error_logs = self.error_logs[-self.error_log_max:]
        self._errlog_dirty = True

    async def _gc_file(self, path: str, delay: int = 60):
        await asyncio.sleep(delay)
        try:
            os.unlink(path)
        except Exception as e:
            logger.debug(f"non-critical: {e}")
            pass

    def _save_history(self, display_name: str, players, max_players):
        now = datetime.now()
        key = display_name
        if key not in self.server_history:
            self.server_history[key] = []
        if self.server_history[key]:
            last = self.server_history[key][-1].get("raw_time", "")
            if last:
                try:
                    prev = datetime.strptime(last, "%Y-%m-%d %H:%M:%S")
                    if (now - prev).total_seconds() < self.history_interval:
                        return
                except Exception as e:
                    logger.debug(f"non-critical: {e}")
                    pass
        p = int(str(players).split("/")[0]) if players else 0
        m = max_players if max_players is not None else (int(str(players).split("/")[1]) if players and "/" in str(players) else 0)
        self.server_history[key].append({
            "time": now.strftime("%m-%d %H:%M"),
            "raw_time": now.strftime("%Y-%m-%d %H:%M:%S"),
            "players": p,
            "max": m
        })
        if len(self.server_history[key]) > self.history_max:
            self.server_history[key] = self.server_history[key][-self.history_max:]
        self._h_dirty = True
        self._store_player_log(key, key, players)

    def _log_command(self, event: AstrMessageEvent, cmd: str):
        entry = {
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "cmd": cmd,
            "sender": str(event.get_sender_id()),
            "group": str(event.message_obj.group_id) if not event.is_private_chat() else "private",
        }
        self.command_logs.append(entry)
        if len(self.command_logs) > 2000:
            self.command_logs = self.command_logs[-2000:]
        self._cmdlog_dirty = True

    def _build_history_chart_image(self, groups_to_show: list, name_filter: str = None) -> str:
        colors = ["#4A90D9", "#E85D47", "#50B86C", "#F5A623", "#8B5CF6", "#EC4899",
                   "#06B6D4", "#84CC16", "#F97316", "#6366F1"]
        server_data = []
        shown = set()
        ci = 0
        for g in groups_to_show:
            servers = [s for s in GLOBAL_DATA["servers"] if s["group"] == g
                       and self.toggle_state.get(_get_toggle_key(s["group"], s["default_name"]), True)]
            for s in servers:
                name = s["display_name"]
                if name_filter:
                    if name_filter not in name and name_filter not in s.get("default_name", ""):
                        continue
                if name in shown:
                    continue
                shown.add(name)
                entries = self.server_history.get(name, [])
                recent = entries[-self.history_count:] if len(entries) > self.history_count else entries
                if recent and len(recent) >= 1:
                    server_data.append((name, recent, colors[ci % len(colors)]))
                    ci += 1

        if not server_data:
            return ""

        global_max = max((e["players"] for _, entries, _ in server_data for e in entries), default=1)
        global_min = min((e["players"] for _, entries, _ in server_data for e in entries), default=0)
        y_range = global_max - global_min
        if y_range == 0:
            y_range = 1
        y_floor = max(0, global_min - int(y_range * 0.15))
        if y_floor < 0:
            y_floor = 0
        y_ceil = global_max + max(int(y_range * 0.3), 1)
        if y_ceil <= y_floor:
            y_ceil = y_floor + 1
        span = y_ceil - y_floor
        if span <= 4:
            y_ceil = y_floor + 4
            span = 4

        max_len = max(len(entries) for _, entries, _ in server_data)
        step_count = max_len

        title = groups_to_show[0] if groups_to_show else "全部组别"

        f_title = self._load_font(22, bold=True)
        f_sub = self._load_font(13)
        f_name = self._load_font(14, bold=True)
        f_cur = self._load_font(15, bold=True)
        f_peak = self._load_font(12)
        f_axis = self._load_font(11)

        row_h = 155
        title_h = 55
        num_rows = len(server_data)
        per_point_w = max(22, min(28, int(720 / max(1, max_len))))
        chart_w = max(380, per_point_w * step_count + 50)
        name_w = 110
        cur_w = 70
        peak_w = 50
        gap = 10
        img_w = name_w + gap + chart_w + cur_w + peak_w + 25
        img_h = title_h + num_rows * row_h + 10
        bg = (255, 255, 255)
        img = Image.new("RGB", (img_w, img_h), bg)
        img = self._apply_background(img)
        draw = ImageDraw.Draw(img)

        draw.text((20, 12), f"{title} 在线人数趋势", fill=(34, 34, 34), font=f_title)
        draw.text((20, 38), f"Y轴 {y_floor}-{y_ceil}人  共{max_len}轮  自动缩放", fill=(170, 170, 170), font=f_sub)

        chart_h = 150
        pad_t, pad_b = 8, 28
        pad_l, pad_r = 35, 5
        plot_w = chart_w - pad_l - pad_r
        plot_h = chart_h - pad_t - pad_b
        chart_x = name_w + gap

        for ri, (name, entries, color) in enumerate(server_data):
            row_y = title_h + ri * row_h
            tx = chart_x + pad_l
            ty = row_y + pad_t

            r, g, b = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)
            text_rgb = (r, g, b)

            tw = draw.textbbox((0, 0), name, font=f_name)[2]
            draw.text((chart_x - gap - tw, row_y + chart_h // 2 - 10), name, fill=(51, 51, 51), font=f_name)

            for i in range(5):
                y = ty + i * plot_h / 4
                draw.line([(tx, y), (tx + plot_w, y)], fill=(230, 230, 230), width=1)
            for i in range(5):
                v = y_floor + (4 - i) * span / 4
                y = ty + i * plot_h / 4
                label = str(int(v))
                lw = draw.textbbox((0, 0), label, font=f_axis)[2]
                draw.text((tx - lw - 4, y - 7), label, fill=(153, 153, 153), font=f_axis)

            values = [e["players"] for e in entries]
            n = len(values)
            if n == 1:
                xs = [tx + plot_w / 2]
            else:
                xs = [tx + i * plot_w / (n - 1) for i in range(n)]

            def y_pos(v):
                ratio = (v - y_floor) / span if span > 0 else 0.5
                return ty + plot_h - ratio * plot_h

            pts = [(x, y_pos(v)) for x, v in zip(xs, values)]
            for i in range(len(pts) - 1):
                draw.line([pts[i], pts[i + 1]], fill=text_rgb, width=2)

            for x, v in zip(xs, values):
                draw.ellipse([x - 3, y_pos(v) - 3, x + 3, y_pos(v) + 3], fill=text_rgb)

            times = [e["time"] for e in entries]
            step = max(1, n // 7)
            for i in range(0, n, step):
                x = xs[i]
                draw.text((x, ty + plot_h + 5), times[i], fill=(153, 153, 153), font=f_axis, anchor="mt")

            latest = entries[-1]
            cur = f"{latest['players']}/{latest['max']}" if latest['max'] > 0 else str(latest['players'])
            peak = max(values)
            cx = img_w - cur_w - peak_w - gap
            draw.text((cx, row_y + chart_h // 2 - 10), cur, fill=text_rgb, font=f_cur)
            px = cx + cur_w
            draw.text((px, row_y + chart_h // 2 - 8), f"峰值{peak}", fill=(170, 170, 170), font=f_peak)

            if ri > 0:
                line_y = row_y - 3
                draw.line([(chart_x, line_y), (img_w - 15, line_y)], fill=(240, 240, 240), width=1)

        self._temp_seq += 1
        path = os.path.join(tempfile.gettempdir(), f"astrbot_niufu_history_{self._temp_seq}.png")
        img.save(path, "PNG")
        return path

    def _trigger_active_refresh(self):
        self.current_interval = GLOBAL_DATA["refresh_interval_min"]
        if self.refresh_task is None or self.refresh_task.done():
            self.refresh_task = asyncio.create_task(self._refresh_loop())

    async def _is_admin(self, event: AstrMessageEvent) -> bool:
        try:
            sender_id = str(event.get_sender_id())
            config_path = Path.cwd() / "data" / "cmd_config.json"
            if not config_path.exists():
                return False
            with open(config_path, "r", encoding="utf-8-sig") as f:
                config = json.load(f)
            admins_id = config.get("admins_id", [])
            return sender_id in [str(uid) for uid in admins_id]
        except Exception as e:
            logger.error(f"[服务器框架] 读取管理员列表失败: {e}")
            return False

    def _is_blacklisted(self, event: AstrMessageEvent) -> bool:
        if not event.is_private_chat():
            group_id = str(event.message_obj.group_id)
            if group_id in self.blacklist.get("groups", []):
                return True
        sender_id = str(event.get_sender_id())
        if sender_id in self.blacklist.get("users", []):
            return True
        return False

    @staticmethod
    def _extract_number(name: str) -> int:
        match = re.search(r'(\d+)', name)
        if match:
            return int(match.group(1))
        chinese_num_map = {
            '一': 1, '二': 2, '三': 3, '四': 4, '五': 5,
            '六': 6, '七': 7, '八': 8, '九': 9, '十': 10,
            '百': 100, '千': 1000, '万': 10000
        }
        for ch in reversed(name):
            if ch in chinese_num_map:
                return chinese_num_map[ch]
        return 9999

    def _load_font(self, size: int, bold: bool = False):
        cache_key = (size, bold)
        if cache_key in self._font_cache:
            return self._font_cache[cache_key]
        font_paths = []
        if bold:
            font_paths = [
                "C:/Windows/Fonts/msyhbd.ttc",
                "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
                "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
                "/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc",
            ]
        else:
            font_paths = [
                "C:/Windows/Fonts/msyh.ttc",
                "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
                "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
                "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
            ]
        for fp in font_paths:
            try:
                font = ImageFont.truetype(fp, size)
                self._font_cache[cache_key] = font
                return font
            except Exception:
                continue
        font = ImageFont.load_default()
        self._font_cache[cache_key] = font
        return font

    async def _build_group_info(self, target_group):
        headers_map = GLOBAL_DATA.get("group_headers", {})
        default_headers = [f"--- {target_group} 状态 ---", "=============="]
        headers = headers_map.get(target_group, default_headers)
        lines = headers.copy()
        servers = [s for s in GLOBAL_DATA["servers"] if s["group"] == target_group and self.toggle_state.get(_get_toggle_key(s["group"], s["default_name"]), True)]
        servers.sort(key=lambda x: self._extract_number(x["display_name"]))
        if not servers:
            lines.append("该组暂无启用的服务器")
            lines.append("==============")
            return lines
        urls = [f"{API_BASE}{s['id']}" for s in servers]
        results = await asyncio.gather(*(self._fetch(url, sid=s["id"]) for url in urls))
        for s, data in zip(servers, results):
            if data:
                online = data.get("online", True)
                players = data.get("players", 0)
                max_players = data.get("max_players")
                self._save_history(s["display_name"], players, max_players)
                if not online:
                    status_str = f"{s['display_name']} 离线"
                else:
                    status_str = f"{s['display_name']} {players}/{max_players}" if max_players is not None else f"{s['display_name']} {players}"
                lines.append(status_str)
            else:
                lines.append(f"{s['display_name']} 离线")
        lines.append("==============")
        return lines

    async def _build_aggregated_info(self, groups: list):
        if not groups:
            return ["暂无可用组别", "=============="]
        headers_map = GLOBAL_DATA.get("group_headers", {})
        main_group = groups[0]
        header = headers_map.get(main_group, [f"--- {main_group} 状态 ---", "=============="])
        header_lines = header[:-1] if len(header) > 1 and header[-1].startswith("=") else header
        lines = header_lines.copy()
        lines.append("==============")

        all_servers = []
        for g in groups:
            servers = [s for s in GLOBAL_DATA["servers"] if s["group"] == g
                       and self.toggle_state.get(_get_toggle_key(s["group"], s["default_name"]), True)]
            all_servers.extend(servers)

        if not all_servers:
            lines.append("该组暂无启用的服务器")
            lines.append("==============")
            return lines

        if len(groups) == 1:
            def _name_prefix(name: str) -> str:
                return re.sub(r'#?\d+$', '', name).strip()

            buckets = {}
            bucket_order = []
            for s in all_servers:
                pf = _name_prefix(s["display_name"])
                if pf not in buckets:
                    buckets[pf] = []
                    bucket_order.append(pf)
                buckets[pf].append(s)
            merged = []
            for pf in bucket_order:
                servers_in_bucket = buckets[pf]
                if len(servers_in_bucket) <= 1 and merged:
                    merged[-1].extend(servers_in_bucket)
                else:
                    merged.append(servers_in_bucket)
            sub_groups = merged
        else:
            sub_groups = [[s for s in all_servers if s["group"] == g] for g in groups]
            sub_groups = [sg for sg in sub_groups if sg]

        for sg in sub_groups:
            sg.sort(key=lambda x: self._extract_number(x["display_name"]))
        flat_servers = [(s, f"{API_BASE}{s['id']}") for sg in sub_groups for s in sg]
        flat_results = await asyncio.gather(*(self._fetch(url, sid=s["id"]) for s, url in flat_servers))
        result_map = {s["id"]: data for (s, _), data in zip(flat_servers, flat_results)}
        for sg in sub_groups:
            for s in sg:
                data = result_map.get(s["id"])
                if data:
                    online = data.get("online", True)
                    players = data.get("players", 0)
                    max_players = data.get("max_players")
                    self._save_history(s["display_name"], players, max_players)
                    if not online:
                        status_str = f"{s['display_name']} 离线"
                    else:
                        status_str = f"{s['display_name']} {players}/{max_players}" if max_players is not None else f"{s['display_name']} {players}"
                    lines.append(status_str)
                else:
                    lines.append(f"{s['display_name']} 离线")
            lines.append("==============")

        if not flat_servers:
            lines.append("该组暂无启用的服务器")
            lines.append("==============")
        return lines

    async def _build_ip_info(self, target_group=None):
        lines = [" 服务器端口与IP映射", "=============="]
        servers = GLOBAL_DATA["servers"]
        if target_group:
            servers = [s for s in servers if s["group"] == target_group]
        active_servers = [s for s in servers if self.toggle_state.get(_get_toggle_key(s["group"], s["default_name"]), True)]
        active_servers.sort(key=lambda x: self._extract_number(x["display_name"]))
        if not active_servers:
            lines.append("暂无启用的服务器")
            lines.append("==============")
            return lines
        results = await asyncio.gather(*(self._fetch(f"{API_BASE}{srv['id']}", sid=srv["id"]) for srv in active_servers))
        for s, data in zip(active_servers, results):
            if data:
                ip, port = data.get("ip", ""), data.get("port", "")
                if ip and port:
                    lines.insert(-1, f"[{s['group']}] {s['display_name']} > {ip}:{port}")
                else:
                    lines.insert(-1, f"[{s['group']}] {s['display_name']} > 端口信息异常")
            else:
                lines.insert(-1, f"[{s['group']}] {s['display_name']} > 离线")
        return lines

    async def _refresh_loop(self):
        while True:
            groups = set(s["group"] for s in GLOBAL_DATA["servers"])
            new_cache = {}
            for g in groups:
                try:
                    new_cache[g] = await asyncio.wait_for(self._build_group_info(g), timeout=30)
                except Exception as e:
                    logger.debug(f"non-critical: {e}")
                    pass
            if new_cache:
                self.cache.update(new_cache)
            await asyncio.sleep(self.current_interval)
            self.current_interval = min(
                GLOBAL_DATA["refresh_interval_max"],
                self.current_interval + GLOBAL_DATA["refresh_decay_step"]
            )

    async def _force_refresh_all(self):
        try:
            groups = set(s["group"] for s in GLOBAL_DATA["servers"])
            for g in groups:
                self.cache[g] = await self._build_group_info(g)
        except Exception as e:
            logger.debug(f"non-critical: {e}")
            pass

    def start_background_tasks(self):
        if self.alert_task is None or self.alert_task.done():
            self.alert_task = asyncio.create_task(self._alert_loop())
        if self.report_task is None or self.report_task.done():
            self.report_task = asyncio.create_task(self._report_loop())
        self.start_tg_polling()

    async def _alert_loop(self):
        await asyncio.sleep(60)
        while True:
            try:
                await self._check_alerts()
            except Exception as e:
                logger.debug(f"non-critical: {e}")
                pass
            if self._raw_dirty and hasattr(self, '_raw_data'):
                save_raw_responses(self._raw_data)
                self._raw_dirty = False
            if self._plogs_dirty and hasattr(self, '_plog_data'):
                save_player_logs(self._plog_data)
                self._plogs_dirty = False
            if self._cache_dirty:
                save_server_cache(self.server_cache)
                self._cache_dirty = False
            if self._h_dirty:
                save_server_history(self.server_history)
                self._h_dirty = False
            if self._errlog_dirty:
                save_error_logs(self.error_logs)
                self._errlog_dirty = False
            if self._cmdlog_dirty:
                save_command_logs(self.command_logs)
                self._cmdlog_dirty = False
            await asyncio.sleep(60)

    async def _check_alerts(self):
        servers = GLOBAL_DATA["servers"]
        active = [s for s in servers if self.toggle_state.get(_get_toggle_key(s["group"], s["default_name"]), True)]
        if not active:
            return
        results = await asyncio.gather(*(self._check_single_alert(s) for s in active), return_exceptions=True)
        for result in results:
            if isinstance(result, Exception):
                logger.debug(f"non-critical: _check_single_alert error: {result}")
        self._update_adaptive_interval()

    async def _check_single_alert(self, s: dict):
        name = s["display_name"]
        grp = s["group"]
        url = f"{API_BASE}{s['id']}"
        cache_key = s["id"]
        cached_entry = self.server_cache.get(cache_key)
        cached_data = cached_entry.get("data") if cached_entry else None
        self.server_cache.pop(cache_key, None)
        data = None
        for _ in range(3):
            data = await self._fetch(url, sid=s["id"])
            if data is not None:
                break
            await asyncio.sleep(3)
        if data is not None:
            if cached_data is None or str(cached_data.get("players", "")) != str(data.get("players", "")) or cached_data.get("online") != data.get("online"):
                self.server_cache[cache_key] = {"ts": datetime.now().timestamp(), "data": data}
                self._cache_dirty = True
        if data is None:
            await asyncio.sleep(2)
            self.server_cache.pop(cache_key, None)
            data2 = await self._fetch(url, sid=s["id"])
            if data2 is None and name not in self._alerted:
                self._push_alert(grp, name, "离线", "服务器多次请求失败，确认已离线")
                self._alerted[name] = "离线"
                self._stable_count.pop(name, None)
            elif data2 is not None and name in self._alerted:
                cnt = self._stable_count.get(name, 0) + 1
                self._stable_count[name] = cnt
                if cnt >= 3:
                    self._alerted.pop(name, None)
                    self._stable_count.pop(name, None)
            return
        players_str = str(data.get("players", "0"))
        p = int(players_str.split("/")[0]) if "/" in players_str else int(players_str) if players_str.isdigit() else 0
        max_p = data.get("max_players")
        if max_p is None:
            max_p = int(players_str.split("/")[1]) if "/" in players_str else 0
        prev_entry = self.last_player_counts.get(name)
        prev = prev_entry.get("p", p) if prev_entry else p
        prev_max = prev_entry.get("m", max_p) if prev_entry else max_p
        drop_pct = self.alert_drop_pct / 100.0
        min_p = self.alert_min_players
        was_zero = self._was_zero.get(name, False)
        anomaly = None
        is_override = False
        if name not in self._alerted and prev > min_p and p < prev * (1 - drop_pct):
            if p == 0 and not was_zero:
                anomaly = ("正在重启", f"人数从 {prev}(满{prev_max}) 骤降至 0/{max_p}")
            elif p > 0:
                anomaly = ("人数骤降", f"人数从 {prev} 降至 {p}/{max_p}，跌幅超过{drop_pct*100:.0f}%")
        elif name in self._alerted and self._alerted[name] == "人数骤降" and p == 0 and not was_zero:
            anomaly = ("正在重启", f"人数从 {prev}(满{prev_max}) 骤降至 0/{max_p}，覆盖骤降告警")
            is_override = True
        if anomaly:
            await asyncio.sleep(2)
            self.server_cache.pop(s["id"], None)
            data2 = None
            for _ in range(2):
                data2 = await self._fetch(url, sid=s["id"])
                if data2 is not None:
                    break
                await asyncio.sleep(2)
            data_cn, data_mh = await asyncio.gather(
                self._fetch_cn(s["id"]), self._fetch_manghui(s["id"]), return_exceptions=True
            )
            if isinstance(data_cn, BaseException):
                data_cn = None
            if isinstance(data_mh, BaseException):
                data_mh = None

            def _extract_p(d, default=None):
                if not d:
                    return None
                ps = str(d.get("players", "0/0"))
                return int(ps.split("/")[0]) if "/" in ps else (int(ps) if ps.isdigit() else default)

            p_primary = _extract_p(data2)
            p_cn = _extract_p(data_cn)
            p_mh = _extract_p(data_mh)

            def _is_low(p_val):
                return p_val is not None and p_val < prev * (1 - drop_pct) if p_val is not None else None

            primary_ok = _is_low(p_primary)
            cn_ok = _is_low(p_cn)
            mh_ok = _is_low(p_mh)

            votes = sum(1 for v in (primary_ok, cn_ok, mh_ok) if v is True)
            has_any = any(v is not None for v in (primary_ok, cn_ok, mh_ok))
            confirmed = votes >= 2 or (votes >= 1 and not has_any) or not has_any

            if votes == 1 and has_any:
                logger.warning(
                    f"[服务器框架] 告警源不一致: {name} "
                    f"主源={'异常' if primary_ok else '正常' if primary_ok is False else '无数据'} "
                    f"CN={'异常' if cn_ok else '正常' if cn_ok is False else '无数据'} "
                    f"MH={'异常' if mh_ok else '正常' if mh_ok is False else '无数据'} "
                    f"votes={votes} → {'仍触发' if confirmed else '跳过'}"
                )
            if confirmed:
                if name not in self._alerted or is_override:
                    if is_override:
                        self._alerted.pop(name, None)
                        self._stable_count.pop(name, None)
                    self._push_alert(grp, name, anomaly[0], anomaly[1])
                    self._alerted[name] = anomaly[0]
                if p == 0 and not was_zero and anomaly[0] == "正在重启":
                    self._was_zero[name] = True
        if name in self._alerted:
            if p > min_p:
                cnt = self._stable_count.get(name, 0) + 1
                self._stable_count[name] = cnt
                if cnt >= 3:
                    self._alerted.pop(name, None)
                    self._stable_count.pop(name, None)
            else:
                self._stable_count.pop(name, None)
        if p > 0 and was_zero:
            self._was_zero[name] = False
        self.last_player_counts[name] = {"p": p, "m": max_p}

    def _update_adaptive_interval(self):
        if self._adaptive_locked or not self.server_history:
            return
        all_recent = []
        for entries in self.server_history.values():
            recent = entries[-10:]
            for e in recent:
                all_recent.append(e.get("players", 0))
        if not all_recent:
            return
        all_recent.sort()
        n = len(all_recent)
        top3 = all_recent[-max(1, n//3):] if n >= 3 else all_recent
        peak_avg = sum(top3) / len(top3)
        vol = sum(1 for v in all_recent if v > 5) / n
        if peak_avg >= 45 and vol > 0.6:
            self.history_interval, self.cache_ttl = 60, 30
        elif peak_avg >= 25 and vol > 0.4:
            self.history_interval, self.cache_ttl = 90, 45
        elif peak_avg >= 10 and vol > 0.2:
            self.history_interval, self.cache_ttl = 180, 90
        elif peak_avg >= 3:
            self.history_interval, self.cache_ttl = 300, 150
        else:
            self.history_interval, self.cache_ttl = 600, 300

    def _push_alert(self, group_name, name, alert_type, msg):
        now = datetime.now()
        if self._last_alert_send and (now - self._last_alert_send).total_seconds() < self._alert_send_interval:
            return
        key = f"{name}::{alert_type}"
        if key in self.alert_cooldown:
            if (now - self.alert_cooldown[key]).total_seconds() < self.alert_cooldown_min * 60:
                return
        self._last_alert_send = now
        self.alert_cooldown[key] = now
        text = f"[告警] {name} {alert_type}\n{msg}"
        for gid, gname in self.group_bindings.items():
            if gname == group_name:
                self._send_alert_to_group(gid, text)
        self._send_telegram(text)

    def _send_alert_to_group(self, group_id: str, text: str):
        if not self._bot:
            return
        async def _send_and_retract():
            try:
                resp = await self._bot.api.call_action("send_group_msg", group_id=int(group_id),
                    message=[{"type": "text", "data": {"text": text}}])
                msg_id = self._extract_msg_id(resp)
                if msg_id is not None:
                    msg_id = int(msg_id)
                    await asyncio.sleep(self.retract_seconds)
                    try:
                        await self._bot.api.call_action("delete_msg", message_id=msg_id)
                    except Exception as e:
                        logger.debug(f"non-critical: {e}")
                        pass
            except Exception as e:
                logger.debug(f"non-critical: {e}")
                pass
        self._create_tracked_task(_send_and_retract())

    @staticmethod
    def _extract_msg_id(resp) -> int | None:
        if isinstance(resp, dict):
            data = resp.get("data") or resp
            if isinstance(data, dict):
                return data.get("message_id")
            elif isinstance(data, int):
                return data
        if isinstance(resp, dict):
            return resp.get("message_id")
        return None

    def _schedule_retract(self, bot, msg_id: int, img_path: str = None):
        async def _retract():
            await asyncio.sleep(self.retract_seconds)
            try:
                await bot.api.call_action("delete_msg", message_id=msg_id)
            except Exception as e:
                logger.debug(f"non-critical: {e}")
                pass
            finally:
                if img_path:
                    try:
                        os.unlink(img_path)
                    except Exception as e:
                        logger.debug(f"non-critical: {e}")
                        pass
        self._create_tracked_task(_retract())

    async def _report_loop(self):
        await asyncio.sleep(10)
        while True:
            now = datetime.now()
            h = now.hour
            m = now.minute
            if h in (0, 12) and m < 2:
                day_key = now.strftime("%Y-%m-%d") + ("_am" if h == 0 else "_pm")
                if day_key not in self.last_report_time and not getattr(self, '_sending_report', False):
                    self._sending_report = True
                    self.last_report_time[day_key] = now
                    stale = [k for k, v in self.last_report_time.items() if (now - v).days > 1]
                    for k in stale:
                        self.last_report_time.pop(k, None)
                    try:
                        await self._send_daily_report()
                    finally:
                        self._sending_report = False
            await asyncio.sleep(50)

    async def _send_daily_report(self):
        groups = list(set(s["group"] for s in GLOBAL_DATA["servers"]))
        for g in groups:
            img_path = await asyncio.to_thread(self._build_stats_image, g, "一天")
            if not img_path:
                continue
            text = f"每日报告 {g} {datetime.now().strftime('%m-%d %H:%M')}"
            for gid, gname in self.group_bindings.items():
                if gname == g and self._bot:
                    self._send_image_to_group(gid, img_path, text)
            self._send_telegram(text, img_path)

    def _send_image_to_group(self, group_id: str, img_path: str, caption: str = ""):
        if not self._bot:
            return
        async def _send():
            try:
                msg = [{"type": "image", "data": {"file": "file:///" + img_path.replace(chr(92), "/")}}]
                if caption:
                    msg.insert(0, {"type": "text", "data": {"text": caption + "\n"}})
                await self._bot.api.call_action("send_group_msg", group_id=int(group_id), message=msg)
            except Exception as e:
                logger.debug(f"non-critical: {e}")
                pass
            finally:
                try:
                    os.unlink(img_path)
                except Exception as e:
                    logger.debug(f"non-critical: {e}")
                    pass
        self._create_tracked_task(_send())

    def _send_telegram(self, text: str, img_path: str = None):
        token = GLOBAL_DATA.get("telegram_bot_token", "")
        chat_id = GLOBAL_DATA.get("telegram_chat_id", "")
        if not token or not chat_id:
            return
        async def _tg():
            try:
                session = await self._get_session()
                if img_path:
                    with open(img_path, "rb") as fh:
                        img_bytes = fh.read()
                    form = aiohttp.FormData()
                    form.add_field("chat_id", chat_id)
                    form.add_field("caption", text)
                    form.add_field("photo", img_bytes, filename=os.path.basename(img_path), content_type="image/png")
                    await session.post(f"https://api.telegram.org/bot{token}/sendPhoto", data=form)
                else:
                    await session.post(f"https://api.telegram.org/bot{token}/sendMessage", json={"chat_id": chat_id, "text": text})
            except Exception as e:
                logger.debug(f"non-critical: {e}")
                pass
            finally:
                if img_path:
                    try:
                        os.unlink(img_path)
                    except Exception as e:
                        logger.debug(f"non-critical: {e}")
                        pass
        self._create_tracked_task(_tg())

    def _build_stats_image(self, group_name: str, period: str) -> str:
        now = datetime.now()
        if period == "一天":
            cutoff = now.timestamp() - 86400
        elif period == "一周":
            cutoff = now.timestamp() - 604800
        else:
            cutoff = now.timestamp() - 2592000
        server_data = []
        colors = ["#4A90D9", "#E85D47", "#50B86C", "#F5A623", "#8B5CF6", "#EC4899"]
        ci = 0
        for name, entries in self.server_history.items():
            srv = next((s for s in GLOBAL_DATA["servers"] if s["display_name"] == name and (group_name is None or s["group"] == group_name)), None)
            if not srv:
                continue
            filtered = [e for e in entries if e.get("raw_time", "")]
            filtered = [e for e in filtered if datetime.strptime(e["raw_time"], "%Y-%m-%d %H:%M:%S").timestamp() >= cutoff]
            if not filtered:
                continue
            players = [e["players"] for e in filtered]
            peak = max(players)
            low = min(players)
            avg = sum(players) // len(players)
            cur = filtered[-1]
            cur_str = f"{cur['players']}/{cur['max']}" if cur['max'] > 0 else str(cur['players'])
            server_data.append((name, filtered, colors[ci % len(colors)], peak, low, avg, cur_str))
            ci += 1
        if not server_data:
            return ""
        f_title = self._load_font(22, bold=True)
        f_row = self._load_font(13)
        row_h = 28
        img_w = 750
        img_h = 60 + len(server_data) * row_h + 10
        img = Image.new("RGB", (img_w, img_h), (255, 255, 255))
        img = self._apply_background(img)
        draw = ImageDraw.Draw(img)
        col1, col2, col3, col4, col5 = 20, 200, 290, 370, 450
        title_str = group_name if group_name else "全部"
        draw.text((20, 12), f"{title_str} {period}统计 {now.strftime('%m-%d %H:%M')}", fill=(34, 34, 34), font=f_title)
        draw.text((col1, 42), "服务器", fill=(100, 100, 100), font=f_row)
        draw.text((col2, 42), "当前", fill=(100, 100, 100), font=f_row)
        draw.text((col3, 42), "峰值", fill=(100, 100, 100), font=f_row)
        draw.text((col4, 42), "低谷", fill=(100, 100, 100), font=f_row)
        draw.text((col5, 42), "均值", fill=(100, 100, 100), font=f_row)
        for i, (name, _, color, peak, low, avg, cur) in enumerate(server_data):
            y = 65 + i * row_h
            r, g, b = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)
            draw.text((col1, y), name, fill=(51, 51, 51), font=f_row)
            draw.text((col2, y), cur, fill=(r, g, b), font=f_row)
            draw.text((col3, y), str(peak), fill=(51, 51, 51), font=f_row)
            draw.text((col4, y), str(low), fill=(51, 51, 51), font=f_row)
            draw.text((col5, y), str(avg), fill=(r, g, b), font=f_row)
        self._temp_seq += 1
        path = os.path.join(tempfile.gettempdir(), f"astrbot_stats_{group_name}_{self._temp_seq}.png")
        img.save(path, "PNG")
        return path

    def _reply_at(self, event, text):
        if event.get_platform_name() == "aiocqhttp":
            self._create_tracked_task(self._send_onebot_and_retract(event, text))
            return
        if event.is_private_chat():
            yield event.plain_result(text)
        else:
            chain = [Comp.At(qq=event.get_sender_id()), Comp.Plain(f"\n{text}")]
            yield event.chain_result(chain)

    async def _send_onebot_and_retract(self, event, text: str):
        user_id = str(event.get_sender_id())
        msg_array = [
            {"type": "at", "data": {"qq": user_id}},
            {"type": "text", "data": {"text": f"\n{text}"}},
        ]
        try:
            if event.is_private_chat():
                resp = await event.bot.api.call_action("send_private_msg", user_id=int(user_id), message=msg_array)
            else:
                group_id = int(event.message_obj.group_id)
                resp = await event.bot.api.call_action("send_group_msg", group_id=group_id, message=msg_array)
            msg_id = self._extract_msg_id(resp)
            if msg_id is not None:
                msg_id = int(msg_id)
                bot = event.bot
                async def _retract():
                    await asyncio.sleep(self.retract_seconds)
                    try:
                        await bot.api.call_action("delete_msg", message_id=msg_id)
                    except Exception as e:
                        logger.debug(f"non-critical: {e}")
                        pass
                self._create_tracked_task(_retract())
        except Exception as e:
            logger.warning(f"[服务器框架] OneBot发送/撤回失败: {e}")

    ADMIN_COMMANDS = [
        "/查看所有服", "/添加服", "/删除服", "/删除组", "/启用端口", "/禁用端口",
        "/黑名单", "/设置组头部文字", "/改服ID", "/改服名", "/改服组",
        "/调整刷新", "/绑定组", "/解绑组", "/开启模糊匹配", "/关闭模糊匹配",
        "/开启无斜杠", "/关闭无斜杠", "/告警设置", "/狂暴模式", "/轮询间隔", "/撤回时间", "/报文", "/长报文", "/tg设置", "/debug", "/niulog", "/牛服日志", "/清除日志", "/历史", "/调整显示", "/日志", "/统计", "/切换源",
    ]

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_message(self, event: AstrMessageEvent):
        if not self._bot and hasattr(event, 'bot'):
            self._bot = event.bot
            self.start_background_tasks()
        if self._is_blacklisted(event):
            return
        msg = event.get_message_str().strip()
        if not msg:
            return
        msg_lower = msg.lower()
        if msg_lower.startswith("/"):
            for cmd in self.ADMIN_COMMANDS:
                if msg_lower.startswith(cmd):
                    return
            if msg_lower.startswith("/牛服") or msg_lower.startswith("/鸽服"):
                return
            return
        registered_commands = [
            "/查服", "/ip", "/info", "/help", "/查看所有服", "/添加服", "/删除服", "/删除组",
            "/启用端口", "/禁用端口", "/黑名单", "/设置组头部文字", "/改服ID",
            "/改服名", "/改服组", "/调整刷新", "/绑定组", "/解绑组",
            "/开启模糊匹配", "/关闭模糊匹配", "/开启无斜杠", "/关闭无斜杠",
            "/牛服", "/鸽服", "/info", "/告警设置", "/狂暴模式", "/轮询间隔", "/撤回时间", "/报文", "/长报文", "/tg设置", "/debug", "/niulog", "/牛服日志", "/清除日志", "/历史", "/调整显示", "/日志", "/统计",
            "/详情", "/搜索", "/查IP", "/切换源",
        ]
        for cmd in registered_commands:
            if cmd in msg_lower:
                return
        trigger_keywords = ["炸了", "服务器炸了", "炸服", "卡了", "连不上", "宕机", "崩了"]
        if any(keyword in msg_lower for keyword in trigger_keywords):
            self._log_command(event, msg)
            self._trigger_active_refresh()
            if not event.is_private_chat():
                group_id = str(event.message_obj.group_id)
                bound_group = self.group_bindings.get(group_id)
                if bound_group:
                    data = await self._build_group_info(bound_group)
                    for chunk in self._reply_at(event, "\n".join(data)):
                        yield chunk
                else:
                    reply = f" 本群尚未绑定任何服务器组。\n管理员可使用 /绑定组 <组名> 为本群绑定。\n可用组名：{', '.join(set(s['group'] for s in GLOBAL_DATA['servers']))}"
                    for chunk in self._reply_at(event, reply):
                        yield chunk
            else:
                for chunk in self._reply_at(event, "请在群聊中使用此功能。"):
                    yield chunk
            event.stop_event()
            return
        group_id = None
        if not event.is_private_chat():
            group_id = str(event.message_obj.group_id)
        if group_id is None or is_fuzzy_enabled(group_id, self.fuzzy_toggle):
            for group_name, triggers in GLOBAL_DATA.get("group_triggers", {}).items():
                for trigger in triggers:
                    if trigger in msg_lower:
                        hint_msg = f" 检测到关键词【{trigger}】，对应服务器组【{group_name}】。\n👉 查询人数：/查服 {group_name}\n👉 获取地址：/ip {group_name}\n 输入 /help 查看更多。"
                        for chunk in self._reply_at(event, hint_msg):
                            yield chunk
                        event.stop_event()
                        return
        if "/" not in msg_lower:
            all_groups = set(s["group"] for s in GLOBAL_DATA["servers"])
            for g in all_groups:
                if g in msg_lower and is_noslash_enabled(g, self.group_noslash):
                    self._log_command(event, f"无斜杠:{msg}")
                    self._trigger_active_refresh()
                    data = await self._build_group_info(g)
                    for chunk in self._reply_at(event, "\n".join(data)):
                        yield chunk
                    event.stop_event()
                    return

    async def _query_by_keyword(self, event: AstrMessageEvent, keyword: str, fallback: str, cmd: str):
        if self._is_blacklisted(event): return
        self._log_command(event, cmd)
        self._trigger_active_refresh()
        groups = [s["group"] for s in GLOBAL_DATA["servers"] if keyword in s["group"]]
        groups = list(dict.fromkeys(groups)) or [fallback]
        data = await self._build_aggregated_info(groups)
        for chunk in self._reply_at(event, "\n".join(data)):
            yield chunk

    @filter.command("牛服")
    async def cmd_niufu(self, event: AstrMessageEvent):
        async for chunk in self._query_by_keyword(event, "牛", "牛", "/牛服"):
            yield chunk

    @filter.command("鸽服")
    async def cmd_pigeon(self, event: AstrMessageEvent):
        async for chunk in self._query_by_keyword(event, "鸽", "鸽", "/鸽服"):
            yield chunk

    @filter.command("查服")
    async def query_generic_group(self, event: AstrMessageEvent):
        if self._is_blacklisted(event): return
        self._log_command(event, "/查服")
        self._trigger_active_refresh()
        msg = event.get_message_str().strip().split(maxsplit=1)
        if len(msg) < 2:
            groups = list(set(s["group"] for s in GLOBAL_DATA["servers"]))
            groups_str = ", ".join(groups) if groups else "暂无任何配置"
            for chunk in self._reply_at(event, f" 请提供要查询的组别名称。\n当前已有组别: {groups_str}\n用法: /查服 <组别名>"):
                yield chunk
            return
        target_group = msg[1].strip()
        data = await self._build_group_info(target_group)
        for chunk in self._reply_at(event, "\n".join(data)):
            yield chunk

    @filter.command("ip")
    async def ip_cmd(self, event: AstrMessageEvent):
        if self._is_blacklisted(event): return
        self._trigger_active_refresh()
        msg = event.get_message_str().strip().split(maxsplit=1)
        target_group = msg[1].strip() if len(msg) > 1 else None
        data = await self._build_ip_info(target_group)
        for chunk in self._reply_at(event, "\n".join(data)):
            yield chunk

    @filter.command("查IP")
    async def query_ip_cmd(self, event: AstrMessageEvent):
        if self._is_blacklisted(event): return
        self._log_command(event, "/查IP")
        parts = event.get_message_str().strip().split(maxsplit=1)
        if len(parts) < 2:
            for chunk in self._reply_at(event, "用法：/查IP <IP地址>\n示例：/查IP 180.188.21.103"):
                yield chunk
            return
        ip = parts[1].strip()
        try:
            session = await self._get_session()
            url = f"{API_CN}&s={ip}"
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    raw = await resp.json()
                    servers = raw.get("data", []) if isinstance(raw, dict) else []
                    if not servers:
                        for chunk in self._reply_at(event, f" 未找到IP {ip} 对应的服务器"):
                            yield chunk
                        return
                    import base64
                    lines = [f" IP {ip} 查询结果", "=============="]
                    for s in servers:
                        sid = s.get("serverId", "?")
                        port = s.get("port", "?")
                        players = s.get("players", "?/?")
                        version = s.get("version", "")
                        modded = "插件" if s.get("modded") else "纯净"
                        info_raw = s.get("info", "")
                        desc = ""
                        if info_raw:
                            try:
                                desc = base64.b64decode(info_raw).decode("utf-8", errors="replace")
                                desc = re.sub(r"<[^>]+>", "", desc).strip()
                                desc = re.sub(r"\s+", " ", desc)[:80]
                            except Exception:
                                pass
                        lines.append(f"[{sid}] {ip}:{port} {players}人 {modded} v{version}")
                        if desc:
                            lines.append(f"  {desc}")
                    lines.append("==============")
                    for chunk in self._reply_at(event, "\n".join(lines)):
                        yield chunk
                else:
                    for chunk in self._reply_at(event, f" API查询失败: HTTP {resp.status}"):
                        yield chunk
        except Exception as e:
            for chunk in self._reply_at(event, f" 查询失败: {e}"):
                yield chunk

    @filter.command("搜索")
    async def search_cmd(self, event: AstrMessageEvent):
        if self._is_blacklisted(event): return
        self._log_command(event, "/搜索")
        parts = event.get_message_str().strip().split(maxsplit=1)
        if len(parts) < 2:
            for chunk in self._reply_at(event, "用法：/搜索 <关键词>\n示例：/搜索 插件  — 搜索包含「插件」的服务器"):
                yield chunk
            return
        keyword = parts[1].strip()
        results = await self._search_servers(keyword)
        if not results:
            for chunk in self._reply_at(event, f" 未找到包含「{keyword}」的服务器"):
                yield chunk
            return
        img_path = await asyncio.to_thread(self._render_search_image, keyword, results)
        if not img_path:
            for chunk in self._reply_at(event, "渲染搜索结果失败"):
                yield chunk
            return
        try:
            if event.get_platform_name() == "aiocqhttp" and not event.is_private_chat():
                group_id = int(event.message_obj.group_id)
                img_msg = [{"type": "image", "data": {"file": "file:///" + img_path.replace(chr(92), "/")}}]
                resp = await event.bot.api.call_action("send_group_msg", group_id=group_id, message=img_msg)
                msg_id = self._extract_msg_id(resp)
                if msg_id is not None:
                    self._schedule_retract(event.bot, int(msg_id), img_path)
            else:
                self._create_tracked_task(self._gc_file(img_path))
                yield event.image_result(img_path)
        except Exception as e:
            logger.debug(f"non-critical: {e}")
            pass

    @filter.command("详情")
    async def detail_cmd(self, event: AstrMessageEvent):
        if self._is_blacklisted(event): return
        self._log_command(event, "/详情")
        parts = event.get_message_str().strip().split(maxsplit=1)
        if len(parts) < 2:
            for chunk in self._reply_at(event, "用法：/详情 <服名或ID>\n示例：/详情 示范服1 或 /详情 59471"):
                yield chunk
            return
        arg = parts[1].strip()
        srv = next((s for s in GLOBAL_DATA["servers"] if arg in s["display_name"] or arg in s["default_name"]), None)
        if srv:
            sid = srv["id"]
        elif arg.isdigit():
            sid = arg
            srv = {"id": sid, "display_name": f"#{sid}", "group": "", "default_name": ""}
        else:
            for chunk in self._reply_at(event, f" 未找到服务器「{arg}」（可使用 /搜索 查找或直接输入ID）"):
                yield chunk
            return
        url = f"{API_BASE}{sid}"
        primary_data = await self._fetch(url, sid=sid)
        cn_data = await self._fetch_cn(sid)
        mh_data = await self._fetch_manghui(sid)
        if srv["display_name"].startswith("#") and cn_data:
            name = cn_data.get("info", "").split(" ")[0][:30] if cn_data.get("info") else f"#{sid}"
            srv["display_name"] = name or f"#{sid}"
        img_path = await asyncio.to_thread(
            self._render_server_detail, srv, primary_data, cn_data, mh_data
        )
        if not img_path:
            for chunk in self._reply_at(event, "渲染详情失败"):
                yield chunk
            return
        try:
            if event.get_platform_name() == "aiocqhttp" and not event.is_private_chat():
                group_id = int(event.message_obj.group_id)
                img_msg = [{"type": "image", "data": {"file": "file:///" + img_path.replace(chr(92), "/")}}]
                resp = await event.bot.api.call_action("send_group_msg", group_id=group_id, message=img_msg)
                msg_id = self._extract_msg_id(resp)
                if msg_id is not None:
                    self._schedule_retract(event.bot, int(msg_id), img_path)
            else:
                self._create_tracked_task(self._gc_file(img_path))
                yield event.image_result(img_path)
        except Exception as e:
            logger.debug(f"non-critical: {e}")
            pass

    @filter.command("info")
    async def info_cmd(self, event: AstrMessageEvent):
        if self._is_blacklisted(event): return
        self._log_command(event, "/info")
        self._trigger_active_refresh()
        raw = event.get_message_str().strip()
        as_image = raw.endswith("图")
        parts = raw.split(maxsplit=1)
        target_group = parts[1].strip().replace(" 图", "").strip() if len(parts) > 1 else None
        if target_group:
            groups = [g for g in set(s["group"] for s in GLOBAL_DATA["servers"]) if target_group in g] or [target_group]
        else:
            groups = list(set(s["group"] for s in GLOBAL_DATA["servers"]))
        servers = [s for s in GLOBAL_DATA["servers"] if s["group"] in groups and self.toggle_state.get(_get_toggle_key(s["group"], s["default_name"]), True)]
        if not servers:
            for chunk in self._reply_at(event, "暂无启用的服务器。"):
                yield chunk
            return
        if not as_image:
            lines = []
            for g in groups:
                g_servers = [s for s in servers if s["group"] == g]
                if not g_servers:
                    continue
                lines.append(f"--- {g} INFO ---")
                urls = [f"{API_BASE}{s['id']}" for s in g_servers]
                results = await asyncio.gather(*(self._fetch(url, sid=s["id"]) for url, s in zip(urls, g_servers)))
                for s, data in zip(g_servers, results):
                    if data:
                        info = re.sub(r'<[^>]+>', '', data.get("info", "")).strip()
                        info = re.sub(r'\s+', ' ', info)
                        players = data.get("players", "?/?")
                        online = data.get("online", False)
                        status = f"{players}" if online else "离线"
                        lines.append(f"{s['display_name']} [{status}]")
                        lines.append(f"  {info}")
                    else:
                        lines.append(f"{s['display_name']} 离线")
            for chunk in self._reply_at(event, "\n".join(lines)):
                yield chunk
        else:
            # pre-fetch all data before thread
            info_data = []
            for s in servers:
                url = f"{API_BASE}{s['id']}"
                data = await self._fetch(url, sid=s["id"])
                info_data.append((s, data))
            img_path = await asyncio.to_thread(self._render_info_image, info_data)
            if not img_path:
                for chunk in self._reply_at(event, "渲染失败"):
                    yield chunk
                return
            try:
                if event.get_platform_name() == "aiocqhttp" and not event.is_private_chat():
                    group_id = int(event.message_obj.group_id)
                    img_msg = [{"type": "image", "data": {"file": "file:///" + img_path.replace(chr(92), "/")}}]
                    resp = await event.bot.api.call_action("send_group_msg", group_id=group_id, message=img_msg)
                    msg_id = self._extract_msg_id(resp)
                    if msg_id is not None:
                        self._schedule_retract(event.bot, int(msg_id), img_path)
                else:
                    self._create_tracked_task(self._gc_file(img_path))
                    yield event.image_result(img_path)
            except Exception:
                for chunk in self._reply_at(event, "发送图片失败"):
                    yield chunk

    def _render_info_image(self, info_data):
        f_title = self._load_font(20, bold=True)
        f_name = self._load_font(16, bold=True)
        f_info = self._load_font(14)

        rows = []
        cur_group = None
        for s, data in info_data:
            g = s["group"]
            if g != cur_group:
                cur_group = g
                rows.append(("title", f"{g} 服务器信息"))
            if data:
                players = data.get("players", "?/?")
                online = data.get("online", False)
                status = f"{players}" if online else "离线(offline)"
                rows.append(("name", f"{s['display_name']}  [{status}]"))
                segments = self._parse_html_color(data.get("info", ""))
                rows.append(("colored", segments))
            else:
                rows.append(("name", f"{s['display_name']}  离线"))
            rows.append(("sep", None))

        if not rows:
            return ""
        line_h = 26
        margin = 20
        img_w = 820
        img_h = margin + len(rows) * line_h + 20
        img = Image.new("RGB", (img_w, img_h), (255, 255, 255))
        img = self._apply_background(img)
        draw = ImageDraw.Draw(img)
        y = 15
        for rtype, rdata in rows:
            if rtype == "title":
                draw.text((margin, y), rdata, fill=(34, 34, 34), font=f_title)
                y += line_h + 4
            elif rtype == "sep":
                draw.line([(margin, y), (img_w - margin, y)], fill=(220, 220, 220), width=1)
                y += line_h
            elif rtype == "name":
                draw.text((margin, y), rdata, fill=(51, 51, 51), font=f_name)
                y += line_h
            elif rtype == "colored":
                x = margin + 10
                for text, color in rdata:
                    if color.startswith("#"):
                        cr = int(color[1:3], 16)
                        cg = int(color[3:5], 16)
                        cb = int(color[5:7], 16)
                    else:
                        cr, cg, cb = 51, 51, 51
                    tw = draw.textbbox((0, 0), text, font=f_info)[2]
                    draw.text((x, y), text, fill=(cr, cg, cb), font=f_info)
                    x += tw
                y += line_h
        self._temp_seq += 1
        path = os.path.join(tempfile.gettempdir(), f"astrbot_info_{self._temp_seq}.png")
        img.save(path, "PNG")
        return path

    @staticmethod
    def _parse_html_color(html: str):
        result = []
        pattern = re.compile(r'<span style="color:(#[0-9A-Fa-f]+)">([^<]*)</span>')
        pos = 0
        for m in pattern.finditer(html):
            if m.start() > pos:
                plain = re.sub(r'<[^>]+>', '', html[pos:m.start()])
                if plain.strip():
                    result.append((plain, "#333333"))
            result.append((m.group(2), m.group(1)))
            pos = m.end()
        if pos < len(html):
            plain = re.sub(r'<[^>]+>', '', html[pos:])
            if plain.strip():
                result.append((plain, "#333333"))
        return result if result else [(re.sub(r'<[^>]+>', '', html).strip(), "#333333")]

    @filter.command("help")
    async def help_cmd(self, event: AstrMessageEvent):
        if self._is_blacklisted(event): return
        is_admin = await self._is_admin(event)
        if is_admin:
            help_text = """通用服务器框架帮助 [管理员]

 查询: /牛服 /鸽服 /查服 /ip /详情 /搜索 /查IP /历史 /统计 /日志 /info
/牛服 /鸽服 — 快捷查组
/查服 <组名> — 查看组内服务器人数
/ip [组名] — 查看服务器IP端口
/详情 <服名或ID> — 服务器详情卡片
/搜索 <关键词> — 搜索全网服务器
/查IP <IP> — 按IP查服务器
/历史 [组名] [服名] — 人数趋势图
/统计 [一天/一周/一月] [组名] — 统计数据
/日志 [日期] [条数] — 命令日志
/info [组名] [图] — 服务器信息

 管理:
/查看所有服 /添加服 /删除服 /删除组 /改服ID /改服名 /改服组
/启用端口 /禁用端口 /黑名单 /设置组头部文字
/调整刷新 /绑定组 /解绑组
/开启模糊匹配 /关闭模糊匹配 /开启无斜杠 /关闭无斜杠
/切换源 <主源/备份1/备份2>
/告警设置 <降幅%> <人数下限> /狂暴模式 /轮询间隔 /撤回时间
/tg设置 <token> /tg设置chat <id>
/niulog /清除日志 /调整显示 <5-240>

炸了/卡了/宕机/崩了自动回复 模糊匹配 无斜杠触发"""
        else:
            help_text = """通用服务器框架帮助

 查询: /牛服 /鸽服 /查服 /ip /详情 /搜索 /查IP /历史 /统计 /日志 /info
/牛服 /鸽服 — 快捷查组
/查服 <组名> — 查看组内人数
/ip [组名] — 查看IP端口
/详情 <服名或ID> — 服务器详情
/搜索 <关键词> — 搜索全网服务器
/查IP <IP> — 按IP查服务器
/历史 [组名] [服名] — 人数趋势图
/统计 [一天/一周/一月] [组名] — 统计
/info [组名] [图] — 服务器信息

炸了/卡了/宕机/崩了自动查询 无斜杠触发"""
        for chunk in self._reply_at(event, help_text):
            yield chunk

    @filter.command("开启无斜杠")
    async def _set_noslash(self, event: AstrMessageEvent, enable: bool):
        if not await self._is_admin(event):
            return
        parts = event.get_message_str().strip().split()
        action_cn = "开启" if enable else "关闭"
        cmd = f"/{action_cn}无斜杠"
        if len(parts) < 2:
            groups = list(set(s["group"] for s in GLOBAL_DATA["servers"]))
            for chunk in self._reply_at(event, f"用法：{cmd} <组名>\n可用组名：{', '.join(groups)}"):
                yield chunk
            return
        group_name = parts[1].strip()
        if group_name not in set(s["group"] for s in GLOBAL_DATA["servers"]):
            for chunk in self._reply_at(event, f" 组【{group_name}】不存在。"):
                yield chunk
            return
        self.group_noslash[group_name] = enable
        save_group_noslash(self.group_noslash)
        for chunk in self._reply_at(event, f" 已{action_cn}组【{group_name}】的无斜杠直接触发。"):
            yield chunk

    @filter.command("开启无斜杠")
    async def enable_noslash(self, event: AstrMessageEvent):
        async for chunk in self._set_noslash(event, True):
            yield chunk

    @filter.command("关闭无斜杠")
    async def disable_noslash(self, event: AstrMessageEvent):
        async for chunk in self._set_noslash(event, False):
            yield chunk

    @filter.command("查看所有服")
    async def list_all_servers(self, event: AstrMessageEvent):
        if not await self._is_admin(event):
            return
        if not GLOBAL_DATA["servers"]:
            for chunk in self._reply_at(event, "当前配置中暂无任何服务器"):
                yield chunk
            return
        groups_dict = {}
        for s in GLOBAL_DATA["servers"]:
            g = s["group"]
            if g not in groups_dict:
                groups_dict[g] = []
            groups_dict[g].append(s)
        lines = ["📊 所有服务器列表", "================"]
        headers_map = GLOBAL_DATA.get("group_headers", {})
        for g, s_list in groups_dict.items():
            h_list = headers_map.get(g, [])
            h_str = " | ".join(h_list) if h_list else "默认结构"
            lines.append(f"🗂️ 组别: {g}")
            lines.append(f"  🔸 头部定义: {h_str}")
            s_list_sorted = sorted(s_list, key=lambda x: self._extract_number(x["display_name"]))
            for s in s_list_sorted:
                status = "启用中" if self.toggle_state.get(_get_toggle_key(s["group"], s["default_name"]), True) else "已封锁"
                lines.append(f"    🔹 标识: {s['default_name']} | 名字: {s['display_name']} [ID: {s['id']}] ({status})")
            lines.append("================")
        for chunk in self._reply_at(event, "\n".join(lines)):
            yield chunk

    @filter.command("添加服")
    async def add_server(self, event: AstrMessageEvent):
        if not await self._is_admin(event):
            return
        msg = event.get_message_str().strip().split(maxsplit=4)
        if len(msg) < 5:
            for chunk in self._reply_at(event, "用法：/添加服 <组别名> <识别名> <API_ID> <展示名>"):
                yield chunk
            return
        group_name, default_name, sid, display_name = msg[1], msg[2], msg[3], msg[4]
        if any(s["default_name"] == default_name and s["group"] == group_name for s in GLOBAL_DATA["servers"]):
            for chunk in self._reply_at(event, f" 已存在：组【{group_name}】下识别名【{default_name}】重复"):
                yield chunk
            return
        GLOBAL_DATA["servers"].append({"id": sid, "group": group_name, "default_name": default_name, "display_name": display_name})
        if group_name not in GLOBAL_DATA["group_headers"]:
            GLOBAL_DATA["group_headers"][group_name] = [f"--- {group_name} 状态 ---", "=============="]
        await self._atomic_save()
        self.toggle_state[_get_toggle_key(group_name, default_name)] = True
        save_toggle_state(self.toggle_state)
        await self._force_refresh_all()
        for chunk in self._reply_at(event, f" 成功添加服务器【{display_name}】到组【{group_name}】"):
            yield chunk

    @filter.command("删除服")
    async def del_server(self, event: AstrMessageEvent):
        if not await self._is_admin(event):
            return
        msg = event.get_message_str().strip().split(maxsplit=2)
        if len(msg) < 3:
            for chunk in self._reply_at(event, "用法：/删除服 <组别名> <识别名>"):
                yield chunk
            return
        group_name, target_name = msg[1], msg[2]
        idx = -1
        for i, s in enumerate(GLOBAL_DATA["servers"]):
            if s["group"] == group_name and s["default_name"] == target_name:
                idx = i
                break
        if idx != -1:
            removed = GLOBAL_DATA["servers"].pop(idx)
            await self._atomic_save()
            t_key = _get_toggle_key(group_name, target_name)
            if t_key in self.toggle_state:
                self.toggle_state.pop(t_key)
                save_toggle_state(self.toggle_state)
            await self._force_refresh_all()
            for chunk in self._reply_at(event, f" 已删除组【{group_name}】下的服务器：{removed['display_name']}"):
                yield chunk
        else:
            existing_names = [s["default_name"] for s in GLOBAL_DATA["servers"] if s["group"] == group_name]
            if existing_names:
                names_list = "、".join(existing_names)
                for chunk in self._reply_at(event, f" 在组【{group_name}】中未找到识别名为【{target_name}】的服务器。\n当前该组下的识别名有：{names_list}"):
                    yield chunk
            else:
                for chunk in self._reply_at(event, f" 组【{group_name}】不存在或该组下没有服务器。"):
                    yield chunk

    @filter.command("删除组")
    async def del_group(self, event: AstrMessageEvent):
        if not await self._is_admin(event):
            return
        msg = event.get_message_str().strip().split(maxsplit=1)
        if len(msg) < 2:
            groups = list(set(s["group"] for s in GLOBAL_DATA["servers"]))
            for chunk in self._reply_at(event, f"用法：/删除组 <组名>\n已有组别：{', '.join(groups)}"):
                yield chunk
            return
        gname = msg[1].strip()
        if gname not in set(s["group"] for s in GLOBAL_DATA["servers"]):
            for chunk in self._reply_at(event, f"组【{gname}】不存在。"):
                yield chunk
            return
        GLOBAL_DATA["servers"] = [s for s in GLOBAL_DATA["servers"] if s["group"] != gname]
        GLOBAL_DATA["group_headers"].pop(gname, None)
        await self._atomic_save()
        await self._force_refresh_all()
        for chunk in self._reply_at(event, f"已删除组【{gname}】及其下所有服务器。"):
            yield chunk

    @filter.command("设置组头部文字")
    async def set_group_headers(self, event: AstrMessageEvent):
        if not await self._is_admin(event):
            return
        msg = event.get_message_str().strip().split(maxsplit=2)
        if len(msg) < 3:
            for chunk in self._reply_at(event, "用法：/设置组头部文字 <组别名> <第一行|第二行|分隔符>"):
                yield chunk
            return
        group_name, headers_str = msg[1], msg[2]
        headers_list = [h.strip() for h in headers_str.split("|") if h.strip()]
        if not headers_list:
            for chunk in self._reply_at(event, "错误：格式不规范，请用 | 符号分隔"):
                yield chunk
            return
        if "group_headers" not in GLOBAL_DATA:
            GLOBAL_DATA["group_headers"] = {}
        GLOBAL_DATA["group_headers"][group_name] = headers_list
        await self._atomic_save()
        await self._force_refresh_all()
        for chunk in self._reply_at(event, f" 组【{group_name}】的头部显示已更新"):
            yield chunk

    @filter.command("改服ID")
    async def change_server_id(self, event: AstrMessageEvent):
        if not await self._is_admin(event):
            return
        msg = event.get_message_str().strip().split(maxsplit=3)
        if len(msg) < 4:
            for chunk in self._reply_at(event, "用法：/改服ID <组别名> <识别名> <新ID>"):
                yield chunk
            return
        group_name, target_name, new_id = msg[1], msg[2], msg[3]
        found = False
        for s in GLOBAL_DATA["servers"]:
            if s["group"] == group_name and s["default_name"] == target_name:
                s["id"] = new_id
                found = True
                break
        if found:
            await self._atomic_save()
            await self._force_refresh_all()
            for chunk in self._reply_at(event, f" 组【{group_name}】服务器【{target_name}】的API_ID已改为：{new_id}"):
                yield chunk
        else:
            for chunk in self._reply_at(event, f" 找不到该指定服务器"):
                yield chunk

    @filter.command("改服名")
    async def change_server_display(self, event: AstrMessageEvent):
        if not await self._is_admin(event):
            return
        msg = event.get_message_str().strip().split(maxsplit=3)
        if len(msg) < 4:
            for chunk in self._reply_at(event, "用法：/改服名 <组别名> <识别名> <新展示名>"):
                yield chunk
            return
        group_name, target_name, new_display = msg[1], msg[2], msg[3]
        found = False
        for s in GLOBAL_DATA["servers"]:
            if s["group"] == group_name and s["default_name"] == target_name:
                s["display_name"] = new_display
                found = True
                break
        if found:
            await self._atomic_save()
            await self._force_refresh_all()
            for chunk in self._reply_at(event, f" 组【{group_name}】服务器【{target_name}】显示名已改为：{new_display}"):
                yield chunk
        else:
            for chunk in self._reply_at(event, f" 找不到该指定服务器"):
                yield chunk

    @filter.command("改服组")
    async def change_server_group(self, event: AstrMessageEvent):
        if not await self._is_admin(event):
            return
        msg = event.get_message_str().strip().split(maxsplit=3)
        if len(msg) < 4:
            for chunk in self._reply_at(event, "用法：/改服组 <原组别名> <识别名> <新组别名>"):
                yield chunk
            return
        old_group, target_name, new_group = msg[1], msg[2], msg[3]
        found = False
        for s in GLOBAL_DATA["servers"]:
            if s["group"] == old_group and s["default_name"] == target_name:
                old_key = _get_toggle_key(old_group, target_name)
                s["group"] = new_group
                new_key = _get_toggle_key(new_group, target_name)
                self.toggle_state[new_key] = self.toggle_state.pop(old_key, True)
                found = True
                break
        if found:
            if new_group not in GLOBAL_DATA["group_headers"]:
                GLOBAL_DATA["group_headers"][new_group] = [f"--- {new_group} 状态 ---", "=============="]
            await self._atomic_save()
            save_toggle_state(self.toggle_state)
            await self._force_refresh_all()
            for chunk in self._reply_at(event, f" 已将【{target_name}】从原组移到【{new_group}】"):
                yield chunk
        else:
            for chunk in self._reply_at(event, f" 找不到该服务器"):
                yield chunk

    @filter.command("启用端口")
    async def enable(self, event: AstrMessageEvent):
        if not await self._is_admin(event):
            return
        msg = event.get_message_str().strip().split()
        if len(msg) < 2:
            for chunk in self._reply_at(event, "用法：/启用端口 所有/组别名 或 /启用端口 <组别名> <识别名>"):
                yield chunk
            return
        if len(msg) == 2:
            target = msg[1].strip()
            if target == "所有":
                for s in GLOBAL_DATA["servers"]:
                    self.toggle_state[_get_toggle_key(s["group"], s["default_name"])] = True
                save_toggle_state(self.toggle_state)
                await self._force_refresh_all()
                for chunk in self._reply_at(event, " 已恢复所有服务器数据查询"):
                    yield chunk
            elif any(s["group"] == target for s in GLOBAL_DATA["servers"]):
                for s in GLOBAL_DATA["servers"]:
                    if s["group"] == target:
                        self.toggle_state[_get_toggle_key(s["group"], s["default_name"])] = True
                save_toggle_state(self.toggle_state)
                await self._force_refresh_all()
                for chunk in self._reply_at(event, f" 已恢复组【{target}】下的所有服务器数据刷新"):
                    yield chunk
            else:
                for chunk in self._reply_at(event, f" 未找到匹配的组别名【{target}】"):
                    yield chunk
        elif len(msg) >= 3:
            g_name, d_name = msg[1].strip(), msg[2].strip()
            if any(s["group"] == g_name and s["default_name"] == d_name for s in GLOBAL_DATA["servers"]):
                self.toggle_state[_get_toggle_key(g_name, d_name)] = True
                save_toggle_state(self.toggle_state)
                await self._force_refresh_all()
                for chunk in self._reply_at(event, f" 已恢复组【{g_name}】下的服务器【{d_name}】数据刷新"):
                    yield chunk
            else:
                for chunk in self._reply_at(event, f" 在组【{g_name}】下未找到识别名为【{d_name}】的服务器"):
                    yield chunk

    @filter.command("禁用端口")
    async def disable(self, event: AstrMessageEvent):
        if not await self._is_admin(event):
            return
        msg = event.get_message_str().strip().split()
        if len(msg) < 2:
            for chunk in self._reply_at(event, "用法：/禁用端口 所有/组别名 或 /禁用端口 <组别名> <识别名>"):
                yield chunk
            return
        if len(msg) == 2:
            target = msg[1].strip()
            if target == "所有":
                for s in GLOBAL_DATA["servers"]:
                    self.toggle_state[_get_toggle_key(s["group"], s["default_name"])] = False
                save_toggle_state(self.toggle_state)
                await self._force_refresh_all()
                for chunk in self._reply_at(event, " 已停止所有服务器数据刷新"):
                    yield chunk
            elif any(s["group"] == target for s in GLOBAL_DATA["servers"]):
                for s in GLOBAL_DATA["servers"]:
                    if s["group"] == target:
                        self.toggle_state[_get_toggle_key(s["group"], s["default_name"])] = False
                save_toggle_state(self.toggle_state)
                await self._force_refresh_all()
                for chunk in self._reply_at(event, f" 已停止组【{target}】下的所有服务器数据刷新"):
                    yield chunk
            else:
                for chunk in self._reply_at(event, f" 未找到匹配的组别名【{target}】"):
                    yield chunk
        elif len(msg) >= 3:
            g_name, d_name = msg[1].strip(), msg[2].strip()
            if any(s["group"] == g_name and s["default_name"] == d_name for s in GLOBAL_DATA["servers"]):
                self.toggle_state[_get_toggle_key(g_name, d_name)] = False
                save_toggle_state(self.toggle_state)
                await self._force_refresh_all()
                for chunk in self._reply_at(event, f" 已停止组【{g_name}】下的服务器【{d_name}】数据刷新"):
                    yield chunk
            else:
                for chunk in self._reply_at(event, f" 在组【{g_name}】下未找到识别名为【{d_name}】的服务器"):
                    yield chunk

    @filter.command("调整刷新")
    async def change_refresh_rate(self, event: AstrMessageEvent):
        if not await self._is_admin(event):
            return
        msg = event.get_message_str().strip().split()
        if len(msg) < 2:
            for chunk in self._reply_at(event, "用法：/调整刷新 <最小秒数> [最大秒数]"):
                yield chunk
            return
        try:
            imin = int(msg[1])
            imax = int(msg[2]) if len(msg) > 2 else imin
            if imin < 2 or imax < imin:
                raise ValueError
            GLOBAL_DATA["refresh_interval_min"] = imin
            GLOBAL_DATA["refresh_interval_max"] = imax
            await self._atomic_save()
            self.current_interval = imin
            out = f"已设定固定轮询速率：{imin}s" if imin == imax else f"已设定动态轮询区间：{imin}s - {imax}s"
            for chunk in self._reply_at(event, out):
                yield chunk
        except ValueError:
            for chunk in self._reply_at(event, "参数错误：刷新速率最低不可低于2秒"):
                yield chunk

    @filter.command("黑名单")
    async def handle_blacklist_cmd(self, event: AstrMessageEvent):
        if not await self._is_admin(event):
            return
        msg = event.get_message_str().strip().split()
        if len(msg) < 3:
            for chunk in self._reply_at(event, "用法：/黑名单 <添加群/删除群/添加人/删除人> <号码>"):
                yield chunk
            return
        subcmd, target_id = msg[1], msg[2]
        if subcmd == "添加群":
            if target_id not in self.blacklist["groups"]:
                self.blacklist["groups"].append(target_id)
                save_blacklist(self.blacklist)
                for chunk in self._reply_at(event, f"已将群聊【{target_id}】加入黑名单"):
                    yield chunk
            else:
                for chunk in self._reply_at(event, f"群聊【{target_id}】已在黑名单中"):
                    yield chunk
        elif subcmd == "删除群":
            if target_id in self.blacklist["groups"]:
                self.blacklist["groups"].remove(target_id)
                save_blacklist(self.blacklist)
                for chunk in self._reply_at(event, f"已将群聊【{target_id}】移出黑名单"):
                    yield chunk
            else:
                for chunk in self._reply_at(event, f"群聊【{target_id}】不在黑名单中"):
                    yield chunk
        elif subcmd == "添加人":
            if target_id not in self.blacklist["users"]:
                self.blacklist["users"].append(target_id)
                save_blacklist(self.blacklist)
                for chunk in self._reply_at(event, f"已将用户【{target_id}】加入黑名单"):
                    yield chunk
            else:
                for chunk in self._reply_at(event, f"用户【{target_id}】已在黑名单中"):
                    yield chunk
        elif subcmd == "删除人":
            if target_id in self.blacklist["users"]:
                self.blacklist["users"].remove(target_id)
                save_blacklist(self.blacklist)
                for chunk in self._reply_at(event, f"已将用户【{target_id}】移出黑名单"):
                    yield chunk
            else:
                for chunk in self._reply_at(event, f"用户【{target_id}】不在黑名单中"):
                    yield chunk
        else:
            for chunk in self._reply_at(event, "未知黑名单子命令。"):
                yield chunk

    @filter.command("绑定组")
    async def bind_group_cmd(self, event: AstrMessageEvent):
        if not await self._is_admin(event):
            return
        msg_parts = event.get_message_str().strip().split()
        if len(msg_parts) < 2:
            groups = list(set(s["group"] for s in GLOBAL_DATA["servers"]))
            for chunk in self._reply_at(event, f"用法：/绑定组 <组名> 或 /绑定组 <群号> <组名>\n可用组名：{', '.join(groups)}"):
                yield chunk
            return
        if len(msg_parts) == 2:
            group_name = msg_parts[1].strip()
            if event.is_private_chat():
                for chunk in self._reply_at(event, "私聊中无法绑定当前群，请使用：/绑定组 <群号> <组名>"):
                    yield chunk
                return
            group_id = str(event.message_obj.group_id)
        else:
            group_id = msg_parts[1].strip()
            group_name = msg_parts[2].strip()
        all_groups = set(s["group"] for s in GLOBAL_DATA["servers"])
        if group_name not in all_groups:
            for chunk in self._reply_at(event, f" 组别【{group_name}】不存在。可用组名：{', '.join(all_groups)}"):
                yield chunk
            return
        self.group_bindings[group_id] = group_name
        save_group_bindings(self.group_bindings)
        for chunk in self._reply_at(event, f" 群 {group_id} 已绑定到服务器组【{group_name}】。"):
            yield chunk

    @filter.command("解绑组")
    async def unbind_group_cmd(self, event: AstrMessageEvent):
        if not await self._is_admin(event):
            return
        msg_parts = event.get_message_str().strip().split()
        if len(msg_parts) == 1:
            if event.is_private_chat():
                for chunk in self._reply_at(event, "私聊中请指定群号：/解绑组 <群号>"):
                    yield chunk
                return
            group_id = str(event.message_obj.group_id)
        else:
            group_id = msg_parts[1].strip()
        if group_id in self.group_bindings:
            del self.group_bindings[group_id]
            save_group_bindings(self.group_bindings)
            for chunk in self._reply_at(event, f" 群 {group_id} 已解绑。"):
                yield chunk
        else:
            for chunk in self._reply_at(event, f"群 {group_id} 未绑定任何服务器组。"):
                yield chunk

    @filter.command("开启模糊匹配")
    async def _set_fuzzy(self, event: AstrMessageEvent, enable: bool):
        if not await self._is_admin(event):
            return
        action_cn = "开启" if enable else "关闭"
        msg_parts = event.get_message_str().strip().split()
        if len(msg_parts) == 1:
            if event.is_private_chat():
                for chunk in self._reply_at(event, f"该命令需要在群聊中使用，或指定群号：/{action_cn}模糊匹配 <群号>"):
                    yield chunk
                return
            group_id = str(event.message_obj.group_id)
        else:
            group_id = msg_parts[1].strip()
        self.fuzzy_toggle[group_id] = enable
        save_fuzzy_toggle(self.fuzzy_toggle)
        for chunk in self._reply_at(event, f" 群 {group_id} 已{action_cn}模糊匹配。"):
            yield chunk

    @filter.command("开启模糊匹配")
    async def enable_fuzzy_match(self, event: AstrMessageEvent):
        async for chunk in self._set_fuzzy(event, True):
            yield chunk

    @filter.command("关闭模糊匹配")
    async def disable_fuzzy_match(self, event: AstrMessageEvent):
        async for chunk in self._set_fuzzy(event, False):
            yield chunk

    @filter.command("niulog")
    async def cmd_niulog(self, event: AstrMessageEvent):
        if not await self._is_admin(event):
            return
        if not self.error_logs:
            for chunk in self._reply_at(event, " 暂无错误日志，一切正常。"):
                yield chunk
            return
        lines = [" 服务器查询错误日志", "================"]
        for entry in self.error_logs[-20:]:
            lines.append(f"[{entry['time']}] {entry['msg']}")
        lines.append("================")
        lines.append(f"共 {len(self.error_logs)} 条记录，显示最近 20 条 | /清除日志 清空")
        for chunk in self._reply_at(event, "\n".join(lines)):
            yield chunk

    @filter.command("牛服日志")
    async def cmd_niulog_cn(self, event: AstrMessageEvent):
        async for chunk in self.cmd_niulog(event):
            yield chunk

    @filter.command("清除日志")
    async def cmd_clear_logs(self, event: AstrMessageEvent):
        if not await self._is_admin(event):
            return
        count = len(self.error_logs)
        self.error_logs.clear()
        for chunk in self._reply_at(event, f"已清除 {count} 条错误日志。"):
            yield chunk

    @filter.command("历史")
    async def cmd_history(self, event: AstrMessageEvent):
        self._log_command(event, "/历史")
        parts = event.get_message_str().strip().split(maxsplit=2)
        target_group = parts[1].strip() if len(parts) > 1 else None
        name_filter = parts[2].strip() if len(parts) > 2 else None

        all_gs = set(s["group"] for s in GLOBAL_DATA["servers"])
        if target_group:
            groups_to_show = [g for g in all_gs if target_group in g]
            if not groups_to_show:
                groups_to_show = [g for g in all_gs if target_group == g]
            if not groups_to_show:
                groups_to_show = [g for g in all_gs]  # show all as fallback
        else:
            groups_to_show = list(all_gs)

        self._trigger_active_refresh()
        await asyncio.gather(*(self._build_group_info(g) for g in groups_to_show), return_exceptions=True)
        if not self.server_history:
            for chunk in self._reply_at(event, "暂无历史数据，请先使用 /牛服 或 /查服 生成数据。"):
                yield chunk
            return

        img_path = await asyncio.to_thread(self._build_history_chart_image, groups_to_show, name_filter=name_filter)
        if not img_path:
            for chunk in self._reply_at(event, "暂无历史数据，请先使用 /牛服 或 /查服 生成数据。"):
                yield chunk
            return

        try:
            if event.get_platform_name() == "aiocqhttp" and not event.is_private_chat():
                group_id = int(event.message_obj.group_id)
                img_msg = [{"type": "image", "data": {"file": "file:///" + img_path.replace(chr(92), "/")}}]
                resp = await event.bot.api.call_action("send_group_msg", group_id=group_id, message=img_msg)
                msg_id = self._extract_msg_id(resp)
                if msg_id:
                    msg_id = int(msg_id) if msg_id is not None else None
                    self._schedule_retract(event.bot, msg_id, img_path)
            else:
                yield event.image_result(img_path)
        except Exception as e:
            err_msg = f"渲染历史图表失败: {e}"
            logger.warning(f"[服务器框架] {err_msg}")
            self._log_error(err_msg)
            for chunk in self._reply_at(event, "渲染图表失败，请稍后重试。"):
                yield chunk

    @filter.command("调整显示")
    async def cmd_adjust_count(self, event: AstrMessageEvent):
        if not await self._is_admin(event):
            return
        self._log_command(event, "/调整显示")
        parts = event.get_message_str().strip().split()
        if len(parts) < 2:
            for chunk in self._reply_at(event, f"用法：/调整显示 <数字>\n当前显示 {self.history_count} 条记录"):
                yield chunk
            return
        try:
            n = int(parts[1])
            if n < 5 or n > 240:
                raise ValueError
            self.history_count = n
            for chunk in self._reply_at(event, f"历史图表显示条数已调整为 {n} 条"):
                yield chunk
        except ValueError:
            for chunk in self._reply_at(event, "请输入 5-240 之间的整数。"):
                yield chunk

    @filter.command("统计")
    async def cmd_stats(self, event: AstrMessageEvent):
        self._log_command(event, "/统计")
        parts = event.get_message_str().strip().split()
        period = "一天"
        target_g = None
        for p in parts[1:]:
            if p in ("一天", "一周", "一月"):
                period = p
            else:
                target_g = p
        if not self.server_history:
            for chunk in self._reply_at(event, "暂无历史数据。"):
                yield chunk
            return
        groups = [target_g] if target_g else list(set(s["group"] for s in GLOBAL_DATA["servers"]))
        for g in groups:
            img_path = await asyncio.to_thread(self._build_stats_image, g, period)
            if not img_path:
                for chunk in self._reply_at(event, f"{g} 暂无足够数据。"):
                    yield chunk
                continue
            try:
                if event.get_platform_name() == "aiocqhttp" and not event.is_private_chat():
                    group_id = int(event.message_obj.group_id)
                    img_msg = [{"type": "image", "data": {"file": "file:///" + img_path.replace(chr(92), "/")}}]
                    resp = await event.bot.api.call_action("send_group_msg", group_id=group_id, message=img_msg)
                    msg_id = self._extract_msg_id(resp)
                    if msg_id is not None:
                        self._schedule_retract(event.bot, int(msg_id), img_path)
                else:
                    self._create_tracked_task(self._gc_file(img_path))
                    yield event.image_result(img_path)
            except Exception as e:
                logger.warning(f"[服务器框架] 发送统计图片失败: {e}")
                for chunk in self._reply_at(event, "发送统计图片失败。"):
                    yield chunk

    @filter.command("日志")
    async def cmd_logsearch(self, event: AstrMessageEvent):
        self._log_command(event, "/日志")
        parts = event.get_message_str().strip().split()
        count = 60
        target_date = datetime.now().strftime("%Y-%m-%d")
        for p in parts[1:]:
            if re.match(r'^\d{4}-\d{2}-\d{2}$', p) or re.match(r'^\d{2}-\d{2}$', p):
                if len(p) == 5:
                    target_date = f"{datetime.now().year}-{p}"
                else:
                    target_date = p
            elif p.isdigit():
                count = max(5, min(int(p), 500))
        date_prefix = target_date
        cmd_logs = self.command_logs
        err_logs = load_error_logs()
        cmd_filtered = [e for e in cmd_logs if e.get("time", "").startswith(date_prefix)][-count:]
        err_filtered = [e for e in err_logs if e.get("time", "").startswith(date_prefix)][-count:]
        hist_data = {}
        for name, entries in self.server_history.items():
            recent = [e for e in entries if e.get("raw_time", e.get("time", "")).startswith(date_prefix)]
            if recent:
                hist_data[name] = recent[-count:]

        empty = not cmd_filtered and not err_filtered and not hist_data
        if empty:
            for chunk in self._reply_at(event, f"{target_date} 无日志记录。"):
                yield chunk
            return

        img_path = await asyncio.to_thread(self._render_log_image, date_prefix, cmd_filtered, err_filtered, hist_data, count)
        if not img_path:
            for chunk in self._reply_at(event, "渲染日志图片失败。"):
                yield chunk
            return
        try:
            if event.get_platform_name() == "aiocqhttp" and not event.is_private_chat():
                group_id = int(event.message_obj.group_id)
                img_msg = [{"type": "image", "data": {"file": "file:///" + img_path.replace(chr(92), "/")}}]
                resp = await event.bot.api.call_action("send_group_msg", group_id=group_id, message=img_msg)
                msg_id = self._extract_msg_id(resp)
                if msg_id is not None:
                    msg_id = int(msg_id)
                    self._schedule_retract(event.bot, msg_id, img_path)
            else:
                yield event.image_result(img_path)
        except Exception as e:
            logger.warning(f"[服务器框架] 发送日志图片失败: {e}")
            for chunk in self._reply_at(event, "发送日志图片失败。"):
                yield chunk

    def _render_log_image(self, date_str, cmd_logs, err_logs, hist_data, max_count):
        f_title = self._load_font(20, bold=True)
        f_section = self._load_font(15, bold=True)
        f_row = self._load_font(12)

        rows = []
        rows.append(f"日志检索 {date_str} (最多{max_count}条)")

        if cmd_logs:
            rows.append("")
            rows.append("--- 指令日志 ---")
            for e in cmd_logs:
                t = e.get("time", "")[-8:]
                sender = e.get("sender", "")[-8:]
                g = e.get("group", "")
                if g == "private":
                    g = "私"
                else:
                    g = g[-6:] if g else ""
                rows.append(f"{t}  [{g}] {sender}  {e.get('cmd','')}")

        if err_logs:
            rows.append("")
            rows.append("--- 错误日志 ---")
            for e in err_logs:
                t = e.get("time", "")[-8:]
                rows.append(f"{t}  {e.get('msg','')}")

        if hist_data:
            rows.append("")
            rows.append("--- 人数日志 ---")
            for name, entries in hist_data.items():
                vals = [f"{e.get('players','?')}/{e.get('max','?')}" for e in entries[-10:]]
                recent_vals = "  ".join(vals)
                rows.append(f"{name}: {recent_vals}")

        row_h = 22
        img_w = 900
        img_h = len(rows) * row_h + 40
        img = Image.new("RGB", (img_w, img_h), (255, 255, 255))
        img = self._apply_background(img)
        draw = ImageDraw.Draw(img)
        for i, line in enumerate(rows):
            y = 15 + i * row_h
            if line.startswith("日志检索"):
                draw.text((20, y), line, fill=(34, 34, 34), font=f_title)
            elif line.startswith("---"):
                draw.text((20, y), line, fill=(74, 144, 226), font=f_section)
            else:
                draw.text((20, y), line, fill=(68, 68, 68), font=f_row)

        self._temp_seq += 1
        path = os.path.join(tempfile.gettempdir(), f"astrbot_niufu_log_{self._temp_seq}.png")
        img.save(path, "PNG")
        return path

    @filter.command("告警设置")
    async def cmd_alert_config(self, event: AstrMessageEvent):
        if not await self._is_admin(event):
            return
        parts = event.get_message_str().strip().split()
        pct = self.alert_drop_pct
        floor = self.alert_min_players
        if len(parts) < 3:
            for chunk in self._reply_at(event, f"用法：/告警设置 <降幅%> <人数下限>\n当前：降幅>{pct}% 且 >{floor}人时告警\n告警生效一次后需重新设置"):
                yield chunk
            return
        try:
            np = int(parts[1])
            nf = int(parts[2])
            if np < 10 or np > 90 or nf < 5 or nf > 100:
                raise ValueError
            self.alert_drop_pct = np
            self.alert_min_players = nf
            GLOBAL_DATA["alert_drop_pct"] = np
            GLOBAL_DATA["alert_min_players"] = nf
            await self._atomic_save()
            for chunk in self._reply_at(event, f"告警阈值已设为：降幅>{np}% 且 >{nf}人（一次有效）"):
                yield chunk
        except ValueError:
            for chunk in self._reply_at(event, "降幅 10-90，人数 5-100。"):
                yield chunk

    @filter.command("狂暴模式")
    async def cmd_frenzy(self, event: AstrMessageEvent):
        if not await self._is_admin(event):
            return
        parts = event.get_message_str().strip().split()
        if len(parts) >= 2 and parts[1] == "关闭":
            self._adaptive_locked = False
            self.history_interval = GLOBAL_DATA.get("history_interval", 120)
            self.cache_ttl = GLOBAL_DATA.get("cache_ttl", 60)
            await self._atomic_save()
            for chunk in self._reply_at(event, "狂暴模式已关闭 恢复自适应"):
                yield chunk
            return
        if len(parts) < 2 or parts[1] != "确认":
            if self._adaptive_locked and self.history_interval == 10:
                for chunk in self._reply_at(event, "狂暴模式已开启(10s请求)\n/狂暴模式 关闭 退出"):
                    yield chunk
            else:
                for chunk in self._reply_at(event, "此操作将每10秒请求API 增加服务器负担\n确认请输入 /狂暴模式 确认"):
                    yield chunk
            return
        self.history_interval = 10
        self.cache_ttl = 5
        self._adaptive_locked = True
        GLOBAL_DATA["history_interval"] = 10
        GLOBAL_DATA["cache_ttl"] = 5
        await self._atomic_save()
        for chunk in self._reply_at(event, "狂暴模式已开启 每10秒请求\n/狂暴模式 关闭 退出"):
            yield chunk

    @filter.command("轮询间隔")
    async def cmd_poll_interval(self, event: AstrMessageEvent):
        if not await self._is_admin(event):
            return
        parts = event.get_message_str().strip().split()
        if len(parts) < 2:
            locked = "（手动锁定）" if self._adaptive_locked else "（自适应）"
            for chunk in self._reply_at(event, f"用法：/轮询间隔 <秒> 或 /轮询间隔 auto\n当前：记录间隔{self.history_interval}s 缓存TTL{self.cache_ttl}s{locked}"):
                yield chunk
            return
        if parts[1].strip().lower() == "auto":
            self._adaptive_locked = False
            GLOBAL_DATA.pop("history_interval", None)
            GLOBAL_DATA.pop("cache_ttl", None)
            await self._atomic_save()
            for chunk in self._reply_at(event, "已恢复自适应频率"):
                yield chunk
            return
        try:
            t = int(parts[1])
            if t < 30 or t > 600:
                raise ValueError
            self.history_interval = t
            self.cache_ttl = max(30, t // 2)
            GLOBAL_DATA["history_interval"] = t
            GLOBAL_DATA["cache_ttl"] = self.cache_ttl
            await self._atomic_save()
            self._adaptive_locked = True
            for chunk in self._reply_at(event, f"轮询间隔已设为 {t}s，缓存TTL {self.cache_ttl}s（自适应已停用）"):
                yield chunk
        except ValueError:
            for chunk in self._reply_at(event, "请输入 30-600 之间的整数。"):
                yield chunk

    @filter.command("撤回时间")
    async def cmd_retract_time(self, event: AstrMessageEvent):
        if not await self._is_admin(event):
            return
        parts = event.get_message_str().strip().split()
        if len(parts) < 2:
            for chunk in self._reply_at(event, f"用法：/撤回时间 <10-300>\n当前撤回时间：{self.retract_seconds}秒"):
                yield chunk
            return
        try:
            t = int(parts[1])
            if t < 10 or t > 300:
                raise ValueError
            self.retract_seconds = t
            GLOBAL_DATA["retract_seconds"] = t
            await self._atomic_save()
            for chunk in self._reply_at(event, f"消息撤回时间已设为 {t} 秒"):
                yield chunk
        except ValueError:
            for chunk in self._reply_at(event, "请输入 10-300 之间的整数。"):
                yield chunk

    @filter.command("报文")
    async def cmd_raw_data(self, event: AstrMessageEvent):
        if not await self._is_admin(event):
            return
        parts = event.get_message_str().strip().split()
        date_filter = None
        count_limit = 0
        # parse optional date and count args
        extra = parts[1:] if len(parts) > 1 else []
        filtered_extra = []
        for a in extra:
            if re.match(r'^\d{2,4}-\d{2}', a):
                date_filter = a
            elif a.isdigit():
                count_limit = int(a)
            else:
                filtered_extra.append(a)
        parts = [parts[0]] + filtered_extra

        raw = getattr(self, '_raw_data', None) or load_raw_responses()
        if not raw:
            for chunk in self._reply_at(event, "暂无存储的报文。"):
                yield chunk
            return
        if len(parts) >= 3:
            grp, sname = parts[1], parts[2]
            srv = next((s for s in GLOBAL_DATA["servers"] if s["group"] == grp and (sname in s["default_name"] or sname in s["display_name"])), None)
            if not srv:
                for chunk in self._reply_at(event, f"未找到 {grp}/{sname}"):
                    yield chunk
                return
            sid = srv["id"]
            entries = raw.get(sid, [])
            if date_filter:
                entries = [e for e in entries if e.get("time","").startswith(date_filter)]
            if not entries:
                for chunk in self._reply_at(event, f"{srv['display_name']} 暂无报文"):
                    yield chunk
                return
            if count_limit > 0:
                entries = entries[-count_limit:]
            label_parts = []
            if date_filter:
                label_parts.append(f"日期{date_filter}")
            if count_limit > 0:
                label_parts.append(f"最近{count_limit}条")
            label = " ".join(label_parts) + " " if label_parts else ""
            lines = [f"--- {srv['display_name']} [{sid}] {label}共{len(entries)}条 ---"]
            for e in entries:
                d = e["data"]
                lines.append(f"[{e['time']}] online={d.get('online')} players={d.get('players')}")
        elif len(parts) >= 2:
            grp = parts[1]
            servers = [s for s in GLOBAL_DATA["servers"] if s["group"] == grp]
            if not servers:
                for chunk in self._reply_at(event, f"组 {grp} 不存在"):
                    yield chunk
                return
            lines = [f"--- {grp} 报文统计 ---"]
            for s in servers:
                count = len(raw.get(s["id"], []))
                lines.append(f"  {s['display_name']} [{s['id']}]: {count}条")
        else:
            total = sum(len(v) for v in raw.values())
            lines = [f"全部服务器报文统计 (共{total}条)"]
            all_srv = sorted(GLOBAL_DATA["servers"], key=lambda x: x["display_name"])
            for s in all_srv:
                count = len(raw.get(s["id"], []))
                lines.append(f"  {s['display_name']} [{s['group']}]: {count}条")
            lines.append("用法: /报文 <组名> <识别名>")
        for chunk in self._reply_at(event, "\n".join(lines)):
            yield chunk

    @filter.command("长报文")
    async def cmd_raw_full(self, event: AstrMessageEvent):
        if not await self._is_admin(event):
            return
        parts = event.get_message_str().strip().split(maxsplit=3)
        date_filter = None
        if len(parts) >= 4:
            date_filter = parts[3]
        elif len(parts) == 3 and re.match(r'^\d{2,4}-\d{2}', parts[2]):
            date_filter = parts[2]
            parts = [parts[0], parts[1]]
        if len(parts) < 3:
            for chunk in self._reply_at(event, "用法: /长报文 <组名> <识别名> [日期]"):
                yield chunk
            return
        grp, sname = parts[1], parts[2]
        srv = next((s for s in GLOBAL_DATA["servers"] if s["group"] == grp and (sname in s["default_name"] or sname in s["display_name"])), None)
        if not srv:
            for chunk in self._reply_at(event, f"未找到 {grp}/{sname}"):
                yield chunk
            return
        raw = getattr(self, '_raw_data', None) or load_raw_responses()
        entries = raw.get(srv["id"], [])
        if date_filter:
            entries = [e for e in entries if e.get("time","").startswith(date_filter)]
        if not entries:
            for chunk in self._reply_at(event, f"{srv['display_name']} 暂无报文"):
                yield chunk
            return
        dlabel = f" 日期{date_filter}" if date_filter else ""
        show = entries[-5:] if len(entries) > 5 else entries
        lines = [json.dumps(e["data"], ensure_ascii=False, indent=2) for e in show]
        img_path = await asyncio.to_thread(self._render_text_image, f"{srv['display_name']} 完整报文{dlabel} ({len(entries)}条)", "\n\n".join(lines))
        if img_path:
            if event.get_platform_name() == "aiocqhttp" and not event.is_private_chat():
                group_id = int(event.message_obj.group_id)
                img_msg = [{"type": "image", "data": {"file": "file:///" + img_path.replace(chr(92), "/")}}]
                await event.bot.api.call_action("send_group_msg", group_id=group_id, message=img_msg)
            else:
                yield event.image_result(img_path)
        else:
            for chunk in self._reply_at(event, "渲染失败"):
                yield chunk

    def _render_text_image(self, title, text):
        f_title = self._load_font(16)
        f_body = self._load_font(11)
        raw_lines = text.split("\n")
        body_lines = []
        for raw in raw_lines:
            while len(raw) > 80:
                body_lines.append(raw[:80])
                raw = raw[80:]
            body_lines.append(raw)
        line_h = 18
        margin = 15
        img_w = 900
        img_h = 50 + len(body_lines) * line_h + 20
        img = Image.new("RGB", (img_w, img_h), (255, 255, 255))
        img = self._apply_background(img)
        draw = ImageDraw.Draw(img)
        draw.text((margin, 12), title, fill=(34, 34, 34), font=f_title)
        y = 45
        for line in body_lines:
            draw.text((margin, y), line, fill=(51, 51, 51), font=f_body)
            y += line_h
        self._temp_seq += 1
        path = os.path.join(tempfile.gettempdir(), f"astrbot_raw_{self._temp_seq}.png")
        img.save(path, "PNG")
        return path

    def _render_search_image(self, keyword: str, results: list) -> str:
        f_title = self._load_font(18, bold=True)
        f_name = self._load_font(13, bold=True)
        f_info = self._load_font(11)
        f_tag = self._load_font(10, bold=True)
        f_small = self._load_font(10)

        margin = 14
        pad = 10
        col_id = margin
        col_name = margin + 62
        col_players = 620
        col_ver = 680
        info_max_w = col_players - col_name - 16
        img_w = 800

        colors = [
            (37, 99, 235), (220, 38, 38), (22, 163, 74), (217, 119, 6),
            (147, 51, 234), (8, 145, 178), (190, 18, 60), (21, 128, 61),
        ]

        def _wrap(text, font, max_w):
            lines = []
            for raw_line in text.split("\n"):
                raw_line = raw_line.strip()
                if not raw_line:
                    continue
                while raw_line:
                    for cut in range(len(raw_line), 0, -1):
                        if draw.textbbox((0, 0), raw_line[:cut], font=font)[2] <= max_w:
                            lines.append(raw_line[:cut])
                            raw_line = raw_line[cut:].lstrip()
                            break
                    else:
                        lines.append(raw_line[:1])
                        raw_line = raw_line[1:]
            return lines

        row_heights = []
        header_h = 52
        min_row_h = 58

        for r in results:
            name = r["name"][:40] or f"#{r['id']}"
            info = r["info"][:200] if r["info"] else ""
            info_lines = _wrap(info, f_info, info_max_w)
            n_info = min(len(info_lines), 4)
            extra_h = n_info * 16
            row_heights.append(max(min_row_h, 40 + extra_h))

        img_h = header_h + sum(row_heights) + 20
        bg_color = (245, 247, 250)
        img = Image.new("RGB", (img_w, max(img_h, 120)), bg_color)
        draw = ImageDraw.Draw(img)

        draw.rectangle([(0, 0), (img_w, header_h)], fill=(30, 41, 59))
        draw.text((margin, 10), f"搜索「{keyword}」— {len(results)}个结果", fill=(255, 255, 255), font=f_title)
        header_labels = f"ID     名称 / 简介                                                                                        人数       版本"
        draw.text((margin, 34), header_labels, fill=(170, 180, 195), font=f_small)

        y = header_h + 4
        for i, r in enumerate(results):
            rh = row_heights[i]
            color = colors[i % len(colors)]
            draw.rectangle([(margin - 4, y), (img_w - margin + 4, y + rh - 4)], fill=(255, 255, 255), outline=(225, 228, 232), width=1)

            sid_str = str(r["id"])
            draw.text((col_id + 2, y + 8), sid_str, fill=(130, 130, 130), font=f_small)

            name = r["name"][:40] or f"#{r['id']}"
            draw.text((col_name, y + 6), name, fill=color, font=f_name)

            ip_port = f"{r['ip']}:{r['port']}"
            draw.text((col_name, y + 26), ip_port, fill=(150, 150, 150), font=f_small)

            info = r["info"][:200] if r["info"] else ""
            info_lines = _wrap(info, f_info, info_max_w)
            iy = y + 6
            for li, line in enumerate(info_lines[:4]):
                draw.text((col_name + 210, iy), line[:55], fill=(100, 100, 100), font=f_info)
                iy += 16

            players_str = r.get("players", "?/?")
            p_val = players_str.split("/")[0] if "/" in players_str else "?"
            m_val = players_str.split("/")[1] if "/" in players_str else "?"
            is_online = p_val != "0" and p_val != "?"
            pl_color = (22, 163, 74) if is_online else (150, 150, 150)
            draw.text((col_players, y + 10), players_str, fill=pl_color, font=f_name)

            ver = r.get("version", "") or ""
            modded = r.get("modded", False)
            tag_x = col_ver
            if ver:
                tw = draw.textbbox((0, 0), ver, font=f_tag)[2] + 10
                draw.rectangle([(tag_x, y + 10), (tag_x + tw, y + 26)], fill=(219, 234, 254))
                draw.text((tag_x + 5, y + 12), ver, fill=(30, 64, 175), font=f_tag)
                tag_x += tw + 6
            mod_tag = "插件" if modded else "纯净"
            mod_bg = (254, 243, 199) if modded else (209, 250, 229)
            mod_fg = (146, 64, 14) if modded else (6, 95, 70)
            tw = draw.textbbox((0, 0), mod_tag, font=f_tag)[2] + 10
            draw.rectangle([(tag_x, y + 10), (tag_x + tw, y + 26)], fill=mod_bg)
            draw.text((tag_x + 5, y + 12), mod_tag, fill=mod_fg, font=f_tag)

            y += rh

        self._temp_seq += 1
        path = os.path.join(tempfile.gettempdir(), f"astrbot_search_{self._temp_seq}.png")
        img.save(path, "PNG")
        return path

    def _render_server_detail(self, srv: dict, primary: dict | None, cn: dict | None, mh: dict | None) -> str:
        import base64
        f_title = self._load_font(22, bold=True)
        f_label = self._load_font(13, bold=True)
        f_body = self._load_font(13)
        f_small = self._load_font(11)
        f_tag = self._load_font(10, bold=True)
        margin = 20
        line_h = 22
        img_w = 780

        def _tag_box(text, color):
            tw = draw.textbbox((0, 0), text, font=f_tag)[2] + 12
            return tw

        def _pick(*keys):
            for src in (primary, cn, mh):
                if src:
                    for k in keys:
                        v = src.get(k)
                        if v is not None and v != "" and v != 0:
                            return v
            return ""

        name = srv["display_name"]
        sid = srv["id"]

        ip = _pick("ip")
        port = _pick("port")
        ip_str = f"{ip}:{port}" if ip and port else (f"{ip}:?" if ip else "未知IP")

        players = _pick("players")
        max_p = _pick("max_players")
        if not max_p and players and "/" in str(players):
            max_p = str(players).split("/")[1]
        online = _pick("online")
        if online is None and players:
            online = True

        version = _pick("version") or ""
        modded = _pick("modded")
        if modded is None:
            modded = False
        distance = _pick("distance") or 0

        info_text = ""
        if cn and cn.get("info"):
            info_text = cn["info"]
        elif mh and mh.get("info"):
            info_text = mh["info"]
        elif primary and primary.get("info"):
            raw_info = primary.get("info", "")
            info_text = re.sub(r"<[^>]+>", "", str(raw_info)).strip()
            info_text = re.sub(r"\s+", " ", info_text)
        if not info_text:
            info_text = "(暂无介绍)"

        sources = []
        if primary:
            sources.append("scplist.kr")
        if cn:
            sources.append("scpslgame.top")
        if mh:
            sources.append("manghui.net")

        info_lines = []
        for raw_line in info_text.split("\n"):
            clean = raw_line.strip()
            while len(clean) > 100:
                info_lines.append(clean[:100])
                clean = clean[100:]
            if clean:
                info_lines.append(clean)
        info_lines = info_lines[:15]

        num_info = len(info_lines)
        info_h = num_info * (line_h - 2)
        card_h = 190 + info_h
        img_h = max(card_h, 200)

        bg_color = (248, 250, 252)
        card_color = (255, 255, 255)
        accent = (37, 99, 235)
        green = (22, 163, 74)
        red = (220, 38, 38)
        gray = (107, 114, 128)
        dark = (31, 41, 55)

        img = Image.new("RGB", (img_w, img_h), bg_color)
        img = self._apply_background(img)
        draw = ImageDraw.Draw(img)

        draw.rectangle([(margin, 8), (img_w - margin, img_h - 8)], radius=12, fill=card_color)
        draw.rectangle([(margin, 8), (img_w - margin, 52)], radius=12, fill=accent)
        draw.rectangle([(margin, 40), (img_w - margin, 52)], fill=accent)

        draw.text((margin + 12, 14), name, fill=(255, 255, 255), font=f_title)
        sid_str = f"ID: {sid}"
        sid_w = draw.textbbox((0, 0), sid_str, font=f_small)[2]
        draw.text((img_w - margin - 16 - sid_w, 18), sid_str, fill=(200, 220, 255), font=f_small)

        y = 60
        label_x = margin + 12
        val_x = label_x + 70

        draw.text((label_x, y), "地址", fill=gray, font=f_label)
        draw.text((val_x, y), ip_str, fill=dark, font=f_body)
        y += line_h

        players_str = str(players) if players else "?/?"
        draw.text((label_x, y), "人数", fill=gray, font=f_label)
        if online:
            draw.text((val_x, y), f"{players_str}  在线", fill=green, font=f_body)
        else:
            draw.text((val_x, y), f"{players_str}  离线", fill=red, font=f_body)
        y += line_h

        tags_y = y
        tag_x = val_x
        if version:
            tw = _tag_box(version, (240, 240, 255))
            draw.rectangle([(tag_x, tags_y + 2), (tag_x + tw, tags_y + 20)], radius=6, fill=(219, 234, 254))
            draw.text((tag_x + 6, tags_y + 3), version, fill=(30, 64, 175), font=f_tag)
            tag_x += tw + 10
        mod_tag = "插件服" if modded else "纯净服"
        mod_bg = (254, 243, 199) if modded else (209, 250, 229)
        mod_fg = (146, 64, 14) if modded else (6, 95, 70)
        tw = _tag_box(mod_tag, mod_bg)
        draw.rectangle([(tag_x, tags_y + 2), (tag_x + tw, tags_y + 20)], radius=6, fill=mod_bg)
        draw.text((tag_x + 6, tags_y + 3), mod_tag, fill=mod_fg, font=f_tag)
        tag_x += tw + 10
        if distance > 0:
            dist_tag = f"距离 {distance}km"
            tw = _tag_box(dist_tag, (243, 244, 246))
            draw.rectangle([(tag_x, tags_y + 2), (tag_x + tw, tags_y + 20)], radius=6, fill=(243, 244, 246))
            draw.text((tag_x + 6, tags_y + 3), dist_tag, fill=gray, font=f_tag)
        y = tags_y + 28

        draw.line([(label_x, y), (img_w - margin - 12, y)], fill=(229, 231, 235), width=1)
        y += 6
        draw.text((label_x, y), "介绍", fill=gray, font=f_label)
        y += line_h

        for line in info_lines:
            draw.text((val_x, y), line, fill=dark, font=f_body)
            y += line_h - 2

        y += 4
        draw.line([(label_x, y), (img_w - margin - 12, y)], fill=(229, 231, 235), width=1)
        y += 6
        src_str = "数据源: " + " / ".join(sources)
        draw.text((label_x, y), src_str, fill=gray, font=f_small)

        self._temp_seq += 1
        path = os.path.join(tempfile.gettempdir(), f"astrbot_detail_{self._temp_seq}.png")
        img.save(path, "PNG")
        return path

    @filter.command("tg设置")
    async def cmd_tg_token(self, event: AstrMessageEvent):
        if not await self._is_admin(event):
            return
        parts = event.get_message_str().strip().split(maxsplit=1)
        if len(parts) < 2:
            token = GLOBAL_DATA.get("telegram_bot_token", "") or "(未设置)"
            chat = GLOBAL_DATA.get("telegram_chat_id", "") or "(未设置)"
            mask = token[:4] + "****" if token != "(未设置)" else token
            for chunk in self._reply_at(event, f"用法：/tg设置 <token>\n/tg设置chat <chat_id>\n当前Token: {mask}\n当前Chat: {chat}"):
                yield chunk
            return
        arg = parts[1].strip()
        if arg.startswith("chat "):
            chat_id = arg[5:].strip()
            GLOBAL_DATA["telegram_chat_id"] = chat_id
            await self._atomic_save()
            for chunk in self._reply_at(event, f"Telegram Chat ID 已设为 {chat_id}"):
                yield chunk
        else:
            GLOBAL_DATA["telegram_bot_token"] = arg
            await self._atomic_save()
            for chunk in self._reply_at(event, f"Telegram Bot Token 已设置"):
                yield chunk

    def start_tg_polling(self):
        if hasattr(self, '_tg_task') and self._tg_task and not self._tg_task.done():
            return
        token = GLOBAL_DATA.get("telegram_bot_token", "")
        if not token:
            return
        self._tg_task = asyncio.create_task(self._tg_poll_loop(token))

    async def _tg_poll_loop(self, token: str):
        await asyncio.sleep(5)
        offset = 0
        async with aiohttp.ClientSession() as sess:
            while True:
                try:
                    url = f"https://api.telegram.org/bot{token}/getUpdates?timeout=30&offset={offset}"
                    async with sess.get(url, timeout=aiohttp.ClientTimeout(total=35)) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            if data.get("ok") and data.get("result"):
                                for upd in data["result"]:
                                    offset = upd["update_id"] + 1
                                    self._create_tracked_task(self._tg_handle_update(upd, token))
                except Exception:
                    await asyncio.sleep(5)

    async def _tg_handle_update(self, upd: dict, token: str):
        msg = upd.get("message") or upd.get("channel_post")
        if not msg:
            return
        chat = msg.get("chat", {})
        chat_id = chat.get("id")
        text = msg.get("text", "")
        if not chat_id or not text:
            return
        parts = text.strip().split()
        cmd = parts[0].lower() if parts else ""
        args = parts[1:] if len(parts) > 1 else []

        if cmd == "/牛服" or cmd == "/niufu":
            groups = list(dict.fromkeys([s["group"] for s in GLOBAL_DATA["servers"] if "牛" in s["group"]])) or ["牛"]
            data = await self._build_aggregated_info(groups)
            await self._tg_send_text(token, chat_id, "\n".join(data))

        elif cmd == "/鸽服" or cmd == "/gef":
            groups = list(dict.fromkeys([s["group"] for s in GLOBAL_DATA["servers"] if "鸽" in s["group"]])) or ["鸽"]
            data = await self._build_aggregated_info(groups)
            await self._tg_send_text(token, chat_id, "\n".join(data))

        elif cmd == "/查服" or cmd == "/chafu":
            g = args[0] if args else ""
            if not g:
                await self._tg_send_text(token, chat_id, "用法: /查服 <组名>")
            else:
                data = await self._build_group_info(g)
                await self._tg_send_text(token, chat_id, "\n".join(data))

        elif cmd == "/help" or cmd == "/帮助":
            h = ("通用服务器框架\n\n"
                 "/牛服\n/鸽服\n/查服 <组名>\n/ip [组名]\n"
                 "/历史 [组名] [服名]\n/统计 [天/周/月] [组名]\n"
                 "/日志 [日期] [条数]\n/info [组名]\n/niulog\n/help\n\n"
                 "直接发送组名即可查询 炸了/卡了等关键词自动回复")
            await self._tg_send_text(token, chat_id, h)

        elif cmd == "/ip":
            g = args[0] if args else None
            data = await self._build_ip_info(g)
            await self._tg_send_text(token, chat_id, "\n".join(data))

        elif cmd == "/历史" or cmd == "/history":
            g = args[0] if args else None
            nf = args[1] if len(args) > 1 else None
            groups = [g] if g else list(set(s["group"] for s in GLOBAL_DATA["servers"]))
            if g and g not in groups:
                groups = [gg for gg in set(s["group"] for s in GLOBAL_DATA["servers"]) if g in gg] or [g]
            img = await asyncio.to_thread(self._build_history_chart_image, groups, name_filter=nf)
            if img:
                await self._tg_send_photo(token, chat_id, img, "历史趋势")
            else:
                await self._tg_send_text(token, chat_id, "暂无历史数据")

        elif cmd == "/统计" or cmd == "/stats":
            period = "一天"
            g = None
            for a in args:
                if a in ("一天", "一周", "一月"):
                    period = a
                else:
                    g = a
            groups = [g] if g else list(set(s["group"] for s in GLOBAL_DATA["servers"]))
            for grp in groups:
                img = await asyncio.to_thread(self._build_stats_image, grp, period)
                if img:
                    await self._tg_send_photo(token, chat_id, img, f"{grp} {period}统计")

        elif cmd == "/日志" or cmd == "/log":
            count = 60
            target_date = datetime.now().strftime("%Y-%m-%d")
            for a in args:
                if re.match(r'^\d{4}-\d{2}-\d{2}$', a) or re.match(r'^\d{2}-\d{2}$', a):
                    target_date = f"{datetime.now().year}-{a}" if len(a) == 5 else a
                elif a.isdigit():
                    count = max(5, min(int(a), 500))
            cmd_logs = self.command_logs
            err_logs = load_error_logs()
            cmd_f = [e for e in cmd_logs if e.get("time", "").startswith(target_date)][-count:]
            err_f = [e for e in err_logs if e.get("time", "").startswith(target_date)][-count:]
            hist_data = {}
            for name, entries in self.server_history.items():
                recent = [e for e in entries if e.get("raw_time", e.get("time", "")).startswith(target_date)]
                if recent:
                    hist_data[name] = recent[-count:]
            img = await asyncio.to_thread(self._render_log_image, target_date, cmd_f, err_f, hist_data, count)
            if img:
                await self._tg_send_photo(token, chat_id, img, f"日志 {target_date}")

        elif cmd == "/niulog":
            if not self.error_logs:
                await self._tg_send_text(token, chat_id, "暂无错误日志")
            else:
                lines = ["错误日志", "========"]
                for e in self.error_logs[-20:]:
                    lines.append(f"[{e['time']}] {e['msg']}")
                await self._tg_send_text(token, chat_id, "\n".join(lines))

        else:
            all_groups = set(s["group"] for s in GLOBAL_DATA["servers"])
            for g in all_groups:
                if g in text:
                    data = await self._build_group_info(g)
                    await self._tg_send_text(token, chat_id, "\n".join(data))
                    return

    async def _tg_send_text(self, token: str, chat_id, text: str):
        try:
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            session = await self._get_session()
            await session.post(url, json={"chat_id": chat_id, "text": text[:4000]}, timeout=aiohttp.ClientTimeout(total=10))
        except Exception as e:
            logger.debug(f"non-critical: {e}")
            pass

    async def _tg_send_photo(self, token: str, chat_id, img_path: str, caption: str = ""):
        try:
            url = f"https://api.telegram.org/bot{token}/sendPhoto"
            with open(img_path, "rb") as fh:
                img_bytes = fh.read()
            form = aiohttp.FormData()
            form.add_field("chat_id", str(chat_id))
            form.add_field("caption", caption[:200])
            form.add_field("photo", img_bytes, filename=os.path.basename(img_path), content_type="image/png")
            session = await self._get_session()
            await session.post(url, data=form, timeout=aiohttp.ClientTimeout(total=15))
        except Exception as e:
            logger.debug(f"non-critical: {e}")
            pass

    @filter.command("切换源")
    async def cmd_switch_source(self, event: AstrMessageEvent):
        if not await self._is_admin(event):
            return
        parts = event.get_message_str().strip().split()
        sources = {"主源": "api.scplist.kr", "备份1": "scpslgame.top (中文站)", "备份2": "manghui.net (芒辉CN)"}
        if len(parts) < 2:
            current = sources.get(self._active_source, self._active_source)
            opts = "\n".join(f"  {k} → {v}" for k, v in sources.items())
            for chunk in self._reply_at(event, f"用法：/切换源 <主源/备份1/备份2>\n当前源：{self._active_source} ({current})\n可选：\n{opts}"):
                yield chunk
            return
        choice = parts[1].strip()
        if choice not in sources:
            for chunk in self._reply_at(event, f"未知源 {choice}，可选：{', '.join(sources.keys())}"):
                yield chunk
            return
        self._active_source = choice
        self.current_interval = GLOBAL_DATA["refresh_interval_min"]
        self._trigger_active_refresh()
        for chunk in self._reply_at(event, f"已切换到 {choice} ({sources[choice]})"):
            yield chunk

    @filter.command("debug")
    async def cmd_debug(self, event: AstrMessageEvent):
        if not await self._is_admin(event):
            return
        self._log_command(event, "/debug")
        results = ["[DEBUG] 指令自检开始", "================"]
        gs = list(set(x["group"] for x in GLOBAL_DATA["servers"]))
        first_group = gs[0] if gs else "牛"
        niu_groups = list(dict.fromkeys([x["group"] for x in GLOBAL_DATA["servers"] if "牛" in x["group"]])) or ["牛"]
        tests = [
            ("/牛服", lambda: self._build_aggregated_info(niu_groups)),
            ("/查服", lambda: self._build_group_info(first_group)),
            ("/ip", lambda: self._build_ip_info()),
            ("/搜索(插件)", lambda: self._search_servers("插件")),
            ("/详情(首台)", lambda: self._fetch_cn(str(GLOBAL_DATA["servers"][0]["id"])) if GLOBAL_DATA["servers"] else None),
            ("/历史图表", lambda: asyncio.to_thread(self._build_history_chart_image, gs)),
            ("/统计图", lambda: asyncio.to_thread(self._build_stats_image, None, "一天")),
            ("/日志图", lambda: asyncio.to_thread(self._render_log_image, datetime.now().strftime("%Y-%m-%d"), self.command_logs[-10:], load_error_logs()[-10:], dict(list(self.server_history.items())[:2]), 10)),
            ("/niulog", lambda: self.error_logs),
            ("缓存", lambda: self.server_cache),
            ("历史数据", lambda: self.server_history),
            ("绑定", lambda: self.group_bindings),
            ("告警冷却", lambda: self.alert_cooldown),
        ]
        images_to_send = []
        for name, fn in tests:
            try:
                result = fn()
                if asyncio.iscoroutine(result):
                    result = await result
                status = "OK" if result else "空"
                if isinstance(result, list):
                    status = f"OK({len(result)}行)"
                elif isinstance(result, dict):
                    status = f"OK({len(result)}条)"
                elif isinstance(result, str) and result:
                    status = "OK(图片)"
                    images_to_send.append((name, result))
                results.append(f"{name}: {status}")
            except Exception as e:
                results.append(f"{name}: 失败({e})")
        results.append("================")
        results.append(f"服务器: {len(GLOBAL_DATA['servers'])}台 | 组别: {len(set(s['group'] for s in GLOBAL_DATA['servers']))}个")
        results.append(f"历史: {len(self.server_history)}台 | 缓存: {len(self.server_cache)}条 | 错误: {len(self.error_logs)}条")
        results.append(f"绑定群: {len(self.group_bindings)}个 | 撤回: {self.retract_seconds}s | 频率: {self.history_interval}s | 缓存TTL: {self.cache_ttl}s")
        results.append(f"当前数据源: {self._active_source} | CN缓存: {len(self._cn_cache)}服 | MH缓存: {len(self._mh_cache)}服 | 背景图: {len(self._bg_images)}张")
        for chunk in self._reply_at(event, "\n".join(results)):
            yield chunk
        for name, img_path in images_to_send:
            try:
                if event.get_platform_name() == "aiocqhttp" and not event.is_private_chat():
                    group_id = int(event.message_obj.group_id)
                    img_msg = [{"type": "image", "data": {"file": "file:///" + img_path.replace(chr(92), "/")}}]
                    resp = await event.bot.api.call_action("send_group_msg", group_id=group_id, message=img_msg)
                else:
                    self._create_tracked_task(self._gc_file(img_path))
                    yield event.image_result(img_path)
                await asyncio.sleep(0.3)
            except Exception as e:
                logger.debug(f"non-critical: {e}")
                pass

    async def teardown(self):
        for attr in ('refresh_task', 'alert_task', 'report_task', '_tg_task'):
            task = getattr(self, attr, None)
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
        for task in list(self._pending_tasks):
            if not task.done():
                task.cancel()
        if self._pending_tasks:
            await asyncio.gather(*self._pending_tasks, return_exceptions=True)
        if self._errlog_dirty:
            try:
                save_error_logs(self.error_logs)
            except Exception as e:
                logger.debug(f"non-critical: {e}")
                pass
        if self._cmdlog_dirty:
            try:
                save_command_logs(self.command_logs)
            except Exception as e:
                logger.debug(f"non-critical: {e}")
                pass
        if self._cache_dirty:
            try:
                save_server_cache(self.server_cache)
            except Exception as e:
                logger.debug(f"non-critical: {e}")
                pass
        if self._h_dirty:
            try:
                save_server_history(self.server_history)
            except Exception as e:
                logger.debug(f"non-critical: {e}")
                pass
        if self._raw_dirty and hasattr(self, '_raw_data'):
            try:
                save_raw_responses(self._raw_data)
            except Exception as e:
                logger.debug(f"non-critical: {e}")
                pass
        if self._plogs_dirty and hasattr(self, '_plog_data'):
            try:
                save_player_logs(self._plog_data)
            except Exception as e:
                logger.debug(f"non-critical: {e}")
                pass
        if hasattr(self, 'session') and self.session and not self.session.closed:
            try:
                await self.session.close()
            except Exception as e:
                logger.debug(f"non-critical: {e}")
                pass

    def __del__(self):
        if hasattr(self, 'session') and self.session and not self.session.closed:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.ensure_future(self.session.close())
                else:
                    loop.run_until_complete(self.session.close())
            except Exception:
                pass