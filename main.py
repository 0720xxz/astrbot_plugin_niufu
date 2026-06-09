import json
import asyncio
import re
import os
import tempfile
from pathlib import Path
from datetime import datetime
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Star, Context, register
from astrbot.api import logger
import aiohttp
import astrbot.api.message_components as Comp
from PIL import Image, ImageDraw, ImageFont

PLUGIN_DIR = Path(__file__).parent

def _data_dir():
    try:
        from astrbot.core.utils.astrbot_path import get_astrbot_plugin_data_path
        d = Path(get_astrbot_plugin_data_path()) / "astrbot_plugin_niufu"
        d.mkdir(parents=True, exist_ok=True)
        return d
    except Exception:
        d = Path.home() / ".astrbot" / "data" / "plugin_data" / "astrbot_plugin_niufu"
        d.mkdir(parents=True, exist_ok=True)
        return d

DATA_DIR = _data_dir()
TOGGLE_FILE = DATA_DIR / "toggle_state.json"
SERVER_DATA_FILE = DATA_DIR / "server_data.json"
BLACKLIST_FILE = DATA_DIR / "blacklist.json"
GROUP_BINDING_FILE = DATA_DIR / "group_bindings.json"
FUZZY_TOGGLE_FILE = DATA_DIR / "fuzzy_toggle.json"
GROUP_NOSLASH_FILE = DATA_DIR / "group_noslash.json"
SERVER_HISTORY_FILE = DATA_DIR / "server_history.json"
SERVER_CACHE_FILE = DATA_DIR / "server_cache.json"
COMMAND_LOGS_FILE = DATA_DIR / "command_logs.json"
ERROR_LOGS_FILE = DATA_DIR / "error_logs.json"

DEFAULT_SERVER_DATA = {
    "refresh_interval_min": 30,
    "refresh_interval_max": 120,
    "refresh_decay_step": 15,
    "group_headers": {
        "内战组": ["--- 通用服务器框架 ---", "=================="]
    },
    "servers": [
        {"id": "59288", "group": "内战组", "default_name": "示范服1", "display_name": "测试服务器"}
    ]
}

def load_server_data():
    if SERVER_DATA_FILE.exists():
        try:
            with open(SERVER_DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if "group_headers" not in data:
                    data["group_headers"] = DEFAULT_SERVER_DATA["group_headers"].copy()
                return data
        except Exception:
            pass
    with open(SERVER_DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(DEFAULT_SERVER_DATA, f, ensure_ascii=False, indent=2)
    return DEFAULT_SERVER_DATA

def save_server_data(data):
    with open(SERVER_DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

GLOBAL_DATA = load_server_data()

def _get_toggle_key(group: str, default_name: str) -> str:
    return f"{group}::{default_name}"

def load_toggle_state():
    if TOGGLE_FILE.exists():
        with open(TOGGLE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {_get_toggle_key(s["group"], s["default_name"]): True for s in GLOBAL_DATA["servers"]}

def save_toggle_state(state):
    with open(TOGGLE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def load_blacklist():
    if BLACKLIST_FILE.exists():
        try:
            with open(BLACKLIST_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"groups": [], "users": []}

def save_blacklist(data):
    with open(BLACKLIST_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_group_bindings():
    if GROUP_BINDING_FILE.exists():
        try:
            with open(GROUP_BINDING_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_group_bindings(bindings):
    with open(GROUP_BINDING_FILE, "w", encoding="utf-8") as f:
        json.dump(bindings, f, ensure_ascii=False, indent=2)

def load_fuzzy_toggle():
    if FUZZY_TOGGLE_FILE.exists():
        try:
            with open(FUZZY_TOGGLE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_fuzzy_toggle(data):
    with open(FUZZY_TOGGLE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def is_fuzzy_enabled(group_id: str, fuzzy_toggle_data: dict) -> bool:
    return fuzzy_toggle_data.get(group_id, True)

def load_group_noslash():
    if GROUP_NOSLASH_FILE.exists():
        try:
            with open(GROUP_NOSLASH_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_group_noslash(data):
    with open(GROUP_NOSLASH_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def is_noslash_enabled(group_name: str, noslash_data: dict) -> bool:
    return noslash_data.get(group_name, False)

def load_server_history():
    if SERVER_HISTORY_FILE.exists():
        try:
            with open(SERVER_HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_server_history(data):
    with open(SERVER_HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_server_cache():
    if SERVER_CACHE_FILE.exists():
        try:
            with open(SERVER_CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_server_cache(data):
    with open(SERVER_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_command_logs():
    if COMMAND_LOGS_FILE.exists():
        try:
            with open(COMMAND_LOGS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []

def save_command_logs(data):
    with open(COMMAND_LOGS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_error_logs():
    if ERROR_LOGS_FILE.exists():
        try:
            with open(ERROR_LOGS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []

def save_error_logs(data):
    with open(ERROR_LOGS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


@register("astrbot_plugin_niufu", "内战狂热爱好者", "Dynamic Server Framework", "4.0")
class UniversalServerPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
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
        self.error_log_max = 50
        self.server_history: dict[str, list] = load_server_history()
        self.history_max = 240
        self.history_interval = 120
        self.history_count = 240
        self.server_cache: dict[str, dict] = load_server_cache()
        self.cache_ttl = 60
        self.last_history_save = datetime.now()
        self.alert_cooldown: dict[str, datetime] = {}
        self.alert_cooldown_min = 10
        self.last_player_counts: dict[str, int] = {}
        self.last_report_time: dict[str, datetime] = {}
        self.alert_task = None
        self.report_task = None
        self._bot = None
        self.retract_seconds = GLOBAL_DATA.get("retract_seconds", 30)

    async def _get_session(self):
        if self.session is None or self.session.closed:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AstrBot-SCP-Query/3.8",
                "Accept": "application/json",
            }
            self.session = aiohttp.ClientSession(headers=headers)
        return self.session

    async def _fetch(self, url, sid=None):
        now_ts = datetime.now().timestamp()
        cache_key = sid if sid else url
        if cache_key in self.server_cache:
            entry = self.server_cache[cache_key]
            if now_ts - entry.get("ts", 0) < self.cache_ttl:
                return entry.get("data")
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
                    save_server_cache(self.server_cache)
                    return data
                else:
                    msg = f"API 返回非 200 状态码: {resp.status} - {url}"
                    logger.warning(f"[服务器框架] {msg}")
                    self._log_error(msg)
        except Exception as e:
            msg = f"获取服务器数据失败: {e} - {url}"
            logger.warning(f"[服务器框架] {msg}")
            self._log_error(msg)
        return None

    def _log_error(self, msg: str):
        self.error_logs.append({"time": datetime.now().strftime("%m-%d %H:%M:%S"), "msg": msg})
        if len(self.error_logs) > self.error_log_max:
            self.error_logs = self.error_logs[-self.error_log_max:]
        save_error_logs(self.error_logs)

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
                except Exception:
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
        save_server_history(self.server_history)

    def _log_command(self, event: AstrMessageEvent, cmd: str):
        entry = {
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "cmd": cmd,
            "sender": str(event.get_sender_id()),
            "group": str(event.message_obj.group_id) if not event.is_private_chat() else "private",
        }
        logs = load_command_logs()
        logs.append(entry)
        if len(logs) > 2000:
            logs = logs[-2000:]
        save_command_logs(logs)

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

        font_name = "C:/Windows/Fonts/msyh.ttc"
        font_bold = "C:/Windows/Fonts/msyhbd.ttc"
        try:
            f_title = ImageFont.truetype(font_bold, 22)
        except Exception:
            f_title = ImageFont.load_default()
        try:
            f_sub = ImageFont.truetype(font_name, 13)
        except Exception:
            f_sub = ImageFont.load_default()
        try:
            f_name = ImageFont.truetype(font_bold, 14)
        except Exception:
            f_name = ImageFont.load_default()
        try:
            f_cur = ImageFont.truetype(font_bold, 15)
        except Exception:
            f_cur = ImageFont.load_default()
        try:
            f_peak = ImageFont.truetype(font_name, 12)
        except Exception:
            f_peak = ImageFont.load_default()
        try:
            f_axis = ImageFont.truetype(font_name, 11)
        except Exception:
            f_axis = ImageFont.load_default()

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

        path = os.path.join(tempfile.gettempdir(), "astrbot_niufu_history.png")
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

    def _extract_number(self, name: str) -> int:
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

    async def _build_group_info(self, target_group):
        headers_map = GLOBAL_DATA.get("group_headers", {})
        default_headers = [f"--- {target_group} 状态 ---", "=============="]
        headers = headers_map.get(target_group, default_headers)
        lines = headers.copy()
        servers = [s for s in GLOBAL_DATA["servers"] if s["group"] == target_group and self.toggle_state.get(_get_toggle_key(s["group"], s["default_name"]), True)]
        servers.sort(key=lambda x: self._extract_number(x["display_name"]))
        if not servers:
            lines.append("该组别暂无启用的服务器")
            lines.append("==============")
            return lines
        urls = [f"https://api.scplist.kr/api/servers/{s['id']}" for s in servers]
        results = await asyncio.gather(*(self._fetch(url, sid=s["id"]) for url in urls))
        for s, data in zip(servers, results):
            if data:
                players = data.get("players", 0)
                max_players = data.get("max_players")
                self._save_history(s["display_name"], players, max_players)
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
            lines.append("该组别暂无启用的服务器")
            lines.append("==============")
            return lines

        if len(groups) == 1:
            def _name_prefix(name: str) -> str:
                return re.sub(r'#?\d+$', '', name).strip()

            buckets = {}
            for s in all_servers:
                pf = _name_prefix(s["display_name"])
                if pf not in buckets:
                    buckets[pf] = []
                buckets[pf].append(s)
            sub_groups = list(buckets.values())
        else:
            sub_groups = [[s for s in all_servers if s["group"] == g] for g in groups]
            sub_groups = [sg for sg in sub_groups if sg]

        all_empty = True
        for sg in sub_groups:
            sg.sort(key=lambda x: self._extract_number(x["display_name"]))
            urls = [f"https://api.scplist.kr/api/servers/{s['id']}" for s in sg]
            results = await asyncio.gather(*(self._fetch(url, sid=s["id"]) for url in urls))
            all_empty = False
            for s, data in zip(sg, results):
                if data:
                    players = data.get("players", 0)
                    max_players = data.get("max_players")
                    self._save_history(s["display_name"], players, max_players)
                    status_str = f"{s['display_name']} {players}/{max_players}" if max_players is not None else f"{s['display_name']} {players}"
                    lines.append(status_str)
                else:
                    lines.append(f"{s['display_name']} 离线")
            lines.append("==============")

        if all_empty:
            lines.append("该组别暂无启用的服务器")
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
        urls = [f"https://api.scplist.kr/api/servers/{s['id']}" for s in active_servers]
        results = await asyncio.gather(*(self._fetch(url, sid=s["id"]) for url in urls))
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
            try:
                groups = set(s["group"] for s in GLOBAL_DATA["servers"])
                new_cache = {}
                for g in groups:
                    new_cache[g] = await self._build_group_info(g)
                self.cache = new_cache
            except Exception:
                pass
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
        except Exception:
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
            except Exception:
                pass
            await asyncio.sleep(60)

    async def _check_alerts(self):
        servers = GLOBAL_DATA["servers"]
        for s in servers:
            if not self.toggle_state.get(_get_toggle_key(s["group"], s["default_name"]), True):
                continue
            name = s["display_name"]
            grp = s["group"]
            url = f"https://api.scplist.kr/api/servers/{s['id']}"
            data = None
            for _ in range(3):
                data = await self._fetch(url, sid=s["id"])
                if data is not None:
                    break
                await asyncio.sleep(3)
            if data is None:
                self._push_alert(grp, name, "离线", "服务器连续3次请求失败，可能已离线")
                continue
            players_str = str(data.get("players", "0"))
            p = int(players_str.split("/")[0]) if "/" in players_str else int(players_str) if players_str.isdigit() else 0
            max_p = data.get("max_players") or (int(players_str.split("/")[1]) if "/" in players_str else 0)
            prev = self.last_player_counts.get(name, p)
            if prev > 20 and p < prev * 0.5:
                self._push_alert(grp, name, "人数骤降", f"人数从 {prev} 降至 {p}/{max_p}，跌幅超过50%")
            self.last_player_counts[name] = p
        self._update_adaptive_interval()

    def _update_adaptive_interval(self):
        if not self.last_player_counts:
            return
        total_players = sum(self.last_player_counts.values())
        count = len(self.last_player_counts)
        avg = total_players / count if count > 0 else 0
        if avg >= 40:
            self.history_interval, self.cache_ttl = 60, 30
        elif avg >= 20:
            self.history_interval, self.cache_ttl = 120, 60
        elif avg >= 5:
            self.history_interval, self.cache_ttl = 180, 90
        else:
            self.history_interval, self.cache_ttl = 300, 150

    def _push_alert(self, group_name, name, alert_type, msg):
        key = f"{name}::{alert_type}"
        now = datetime.now()
        if key in self.alert_cooldown:
            if (now - self.alert_cooldown[key]).total_seconds() < self.alert_cooldown_min * 60:
                return
        self.alert_cooldown[key] = now
        text = f"[告警] {name} {alert_type}\n{msg}"
        for gid, gname in self.group_bindings.items():
            if gname == group_name:
                self._send_to_group_id(gid, text)
        self._send_telegram(text)

    def _send_to_group_id(self, group_id: str, text: str):
        if not self._bot:
            return
        async def _send():
            try:
                await self._bot.api.call_action("send_group_msg", group_id=int(group_id),
                    message=[{"type": "text", "data": {"text": text}}])
            except Exception:
                pass
        asyncio.create_task(_send())

    async def _report_loop(self):
        await asyncio.sleep(10)
        while True:
            now = datetime.now()
            hm = now.strftime("%H:%M")
            if hm in ("00:00", "00:01", "12:00", "12:01"):
                day_key = now.strftime("%Y-%m-%d") + ("_am" if now.hour == 0 else "_pm")
                if day_key not in self.last_report_time:
                    self.last_report_time[day_key] = now
                    stale = [k for k, v in self.last_report_time.items() if (now - v).days > 1]
                    for k in stale:
                        self.last_report_time.pop(k, None)
                    await self._send_daily_report()
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
            except Exception:
                pass
        asyncio.create_task(_send())

    def _send_telegram(self, text: str, img_path: str = None):
        token = GLOBAL_DATA.get("telegram_bot_token", "")
        chat_id = GLOBAL_DATA.get("telegram_chat_id", "")
        if not token or not chat_id:
            return
        async def _tg():
            try:
                import aiohttp
                session = aiohttp.ClientSession()
                if img_path:
                    url_tg = f"https://api.telegram.org/bot{token}/sendPhoto"
                    form = aiohttp.FormData()
                    form.add_field("chat_id", chat_id)
                    form.add_field("caption", text)
                    form.add_field("photo", open(img_path, "rb"))
                    await session.post(url_tg, data=form)
                else:
                    url_tg = f"https://api.telegram.org/bot{token}/sendMessage"
                    await session.post(url_tg, json={"chat_id": chat_id, "text": text})
                await session.close()
            except Exception:
                pass
        asyncio.create_task(_tg())

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
            srv = next((s for s in GLOBAL_DATA["servers"] if s["display_name"] == name and s["group"] == group_name), None)
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
        font_name = "C:/Windows/Fonts/msyh.ttc"
        font_bold = "C:/Windows/Fonts/msyhbd.ttc"
        try:
            f_title = ImageFont.truetype(font_bold, 22)
            f_row = ImageFont.truetype(font_name, 13)
        except Exception:
            f_title = f_row = ImageFont.load_default()
        row_h = 28
        img_w = 750
        img_h = 60 + len(server_data) * row_h + 10
        img = Image.new("RGB", (img_w, img_h), (255, 255, 255))
        draw = ImageDraw.Draw(img)
        col1, col2, col3, col4, col5 = 20, 200, 290, 370, 450
        draw.text((20, 12), f"{group_name} {period}统计 {now.strftime('%m-%d %H:%M')}", fill=(34, 34, 34), font=f_title)
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
        path = os.path.join(tempfile.gettempdir(), f"astrbot_stats_{group_name}.png")
        img.save(path, "PNG")
        return path

    def _reply_at(self, event, text):
        if event.get_platform_name() == "aiocqhttp":
            asyncio.create_task(self._send_onebot_and_retract(event, text))
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
            msg_id = None
            if isinstance(resp, dict):
                data = resp.get("data") or resp
                if isinstance(data, dict):
                    msg_id = data.get("message_id")
                elif isinstance(data, int):
                    msg_id = data
            if msg_id is None and isinstance(resp, dict):
                msg_id = resp.get("message_id")
            if msg_id is not None:
                msg_id = int(msg_id)
                bot = event.bot
                async def _retract():
                    await asyncio.sleep(self.retract_seconds)
                    try:
                        await bot.api.call_action("delete_msg", message_id=msg_id)
                    except Exception:
                        pass
                asyncio.create_task(_retract())
        except Exception as e:
            logger.warning(f"[服务器框架] OneBot发送/撤回失败: {e}")

    ADMIN_COMMANDS = [
        "/查看所有服", "/添加服", "/删除服", "/删除组", "/删除组", "/启用端口", "/禁用端口",
        "/黑名单", "/设置组头部文字", "/改服ID", "/改服名", "/改服组",
        "/调整刷新", "/绑定组", "/解绑组", "/开启模糊匹配", "/关闭模糊匹配",
        "/开启无斜杠", "/关闭无斜杠", "/撤回时间", "/tg设置", "/niulog", "/牛服日志", "/清除日志", "/历史", "/调整显示", "/日志", "/统计", "/调整显示", "/日志", "/统计"
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
            if msg_lower.startswith("/牛服"):
                self._log_command(event, "/牛服")
                self._trigger_active_refresh()
                niufu_groups = list(dict.fromkeys([s["group"] for s in GLOBAL_DATA["servers"] if "牛" in s["group"]]))
                if not niufu_groups:
                    niufu_groups = ["牛"]
                data = await self._build_aggregated_info(niufu_groups)
                for chunk in self._reply_at(event, "\n".join(data)):
                    yield chunk
                event.stop_event()
                return
            if msg_lower.startswith("/鸽服"):
                self._log_command(event, "/鸽服")
                self._trigger_active_refresh()
                ge_groups = list(dict.fromkeys([s["group"] for s in GLOBAL_DATA["servers"] if "鸽" in s["group"]]))
                if not ge_groups:
                    ge_groups = ["鸽"]
                data = await self._build_aggregated_info(ge_groups)
                for chunk in self._reply_at(event, "\n".join(data)):
                    yield chunk
                event.stop_event()
                return
            return
        registered_commands = [
            "/查服", "/ip", "/help", "/查看所有服", "/添加服", "/删除服", "/删除组", "/删除组",
            "/启用端口", "/禁用端口", "/黑名单", "/设置组头部文字", "/改服ID",
            "/改服名", "/改服组", "/调整刷新", "/绑定组", "/解绑组",
            "/开启模糊匹配", "/关闭模糊匹配", "/开启无斜杠", "/关闭无斜杠",
            "/牛服", "/鸽服", "/撤回时间", "/tg设置", "/niulog", "/牛服日志", "/清除日志", "/历史", "/调整显示", "/日志", "/统计"
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
        has_slash = "/" in msg_lower
        has_cmd = any(msg_lower.startswith(cmd.lstrip("/")) for cmd in registered_commands)
        if not has_slash and not has_cmd:
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

    @filter.command("牛服")
    async def cmd_niufu(self, event: AstrMessageEvent):
        if self._is_blacklisted(event): return
        self._log_command(event, "/牛服")
        self._trigger_active_refresh()
        niufu_groups = list(dict.fromkeys([s["group"] for s in GLOBAL_DATA["servers"] if "牛" in s["group"]]))
        if not niufu_groups:
            niufu_groups = ["牛"]
        data = await self._build_aggregated_info(niufu_groups)
        for chunk in self._reply_at(event, "\n".join(data)):
            yield chunk

    @filter.command("鸽服")
    async def cmd_pigeon(self, event: AstrMessageEvent):
        if self._is_blacklisted(event): return
        self._log_command(event, "/鸽服")
        self._trigger_active_refresh()
        ge_groups = list(dict.fromkeys([s["group"] for s in GLOBAL_DATA["servers"] if "鸽" in s["group"]]))
        if not ge_groups:
            ge_groups = ["鸽"]
        data = await self._build_aggregated_info(ge_groups)
        for chunk in self._reply_at(event, "\n".join(data)):
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

    @filter.command("help")
    async def help_cmd(self, event: AstrMessageEvent):
        if self._is_blacklisted(event): return
        is_admin = await self._is_admin(event)
        if is_admin:
            help_text = """ 通用服务器框架使用帮助 [管理员]

【快捷查询】
/牛服 - 查询"牛"组状态
/鸽服 - 查询"鸽"组状态
/查服 <组名> - 查询任意组状态
/ip [组名] - 查询服务器IP与端口
/历史 [组名] [服名] - 查看人数历史趋势图
/统计 [一天/一周/一月] [组名] - 渲染各服峰值/低谷/均值统计图
/日志 [日期] [条数] - 检索指令/错误/人数日志并渲染为图片

【管理员指令】
/查看所有服 - 查看所有组别、服务器及启用状态
/添加服 <组别> <识别名> <API_ID> <展示名>
/删除服 <组别> <识别名>
/删除组 <组名> - 删除整个组别及其下所有服务器
/启用端口 所有/<组别> 或 /启用端口 <组别> <识别名>
/禁用端口 所有/<组别> 或 /禁用端口 <组别> <识别名>
/黑名单 <添加群/删除群/添加人/删除人> <号码>
/设置组头部文字 <组别> <第一行|第二行|分隔符>
/改服ID <组别> <识别名> <新ID>
/改服名 <组别> <识别名> <新展示名>
/改服组 <原组别> <识别名> <新组别>
/调整刷新 <最小秒数> [最大秒数]
/绑定组 <组名> 或 /绑定组 <群号> <组名>
/解绑组 [群号]
/开启模糊匹配 [群号] /关闭模糊匹配 [群号]
/开启无斜杠 <组名> /关闭无斜杠 <组名>
/niulog /牛服日志 /清除日志
/调整显示 <5-240> /撤回时间 <10-300>
/tg设置 <token> /tg设置chat <id>

【智能触发】炸了/卡了/连不上/宕机/崩了 自动回复 | 模糊匹配 | 无斜杠触发"""
        else:
            help_text = """ 通用服务器框架使用帮助

/牛服 - 查询"牛"组状态
/鸽服 - 查询"鸽"组状态
/查服 <组名> - 查询任意组状态
/ip [组名] - 查询服务器IP与端口
/历史 [组名] [服名] - 查看人数历史趋势图
/统计 [一天/一周/一月] [组名] - 统计图
/日志 [日期] [条数] - 日志检索图

【智能触发】
- 发送"炸了/卡了/连不上/宕机/崩了"自动查询绑定组状态
- 直接发送组名（如"牛"）查询服务器人数"""
        for chunk in self._reply_at(event, help_text):
            yield chunk

    @filter.command("开启无斜杠")
    async def enable_noslash(self, event: AstrMessageEvent):
        if not await self._is_admin(event):
            return
        parts = event.get_message_str().strip().split()
        if len(parts) < 2:
            groups = list(set(s["group"] for s in GLOBAL_DATA["servers"]))
            for chunk in self._reply_at(event, f"用法：/开启无斜杠 <组名>\n可用组名：{', '.join(groups)}"):
                yield chunk
            return
        group_name = parts[1].strip()
        if group_name not in set(s["group"] for s in GLOBAL_DATA["servers"]):
            for chunk in self._reply_at(event, f" 组【{group_name}】不存在。"):
                yield chunk
            return
        self.group_noslash[group_name] = True
        save_group_noslash(self.group_noslash)
        for chunk in self._reply_at(event, f" 已开启组【{group_name}】的无斜杠直接触发。"):
            yield chunk

    @filter.command("关闭无斜杠")
    async def disable_noslash(self, event: AstrMessageEvent):
        if not await self._is_admin(event):
            return
        parts = event.get_message_str().strip().split()
        if len(parts) < 2:
            groups = list(set(s["group"] for s in GLOBAL_DATA["servers"]))
            for chunk in self._reply_at(event, f"用法：/关闭无斜杠 <组名>\n可用组名：{', '.join(groups)}"):
                yield chunk
            return
        group_name = parts[1].strip()
        if group_name not in set(s["group"] for s in GLOBAL_DATA["servers"]):
            for chunk in self._reply_at(event, f" 组【{group_name}】不存在。"):
                yield chunk
            return
        self.group_noslash[group_name] = False
        save_group_noslash(self.group_noslash)
        for chunk in self._reply_at(event, f" 已关闭组【{group_name}】的无斜杠直接触发。"):
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
            for chunk in self._reply_at(event, f" 冲突：组别【{group_name}】下识别名【{default_name}】已存在"):
                yield chunk
            return
        GLOBAL_DATA["servers"].append({"id": sid, "group": group_name, "default_name": default_name, "display_name": display_name})
        if group_name not in GLOBAL_DATA["group_headers"]:
            GLOBAL_DATA["group_headers"][group_name] = [f"--- {group_name} 状态 ---", "=============="]
        save_server_data(GLOBAL_DATA)
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
            save_server_data(GLOBAL_DATA)
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
        save_server_data(GLOBAL_DATA)
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
        save_server_data(GLOBAL_DATA)
        await self._force_refresh_all()
        for chunk in self._reply_at(event, f" 组【{group_name}】的报头渲染模板更新完毕！"):
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
            save_server_data(GLOBAL_DATA)
            await self._force_refresh_all()
            for chunk in self._reply_at(event, f" 组【{group_name}】内服务器【{target_name}】的API_ID已变更为：{new_id}"):
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
            save_server_data(GLOBAL_DATA)
            await self._force_refresh_all()
            for chunk in self._reply_at(event, f" 组【{group_name}】内服务器【{target_name}】的展现别名已变更为：{new_display}"):
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
            save_server_data(GLOBAL_DATA)
            save_toggle_state(self.toggle_state)
            await self._force_refresh_all()
            for chunk in self._reply_at(event, f" 成功跨组迁移：服务器【{target_name}】已移入【{new_group}】"):
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
                for chunk in self._reply_at(event, " 已恢复全局所有服务器的数据轮询"):
                    yield chunk
            elif any(s["group"] == target for s in GLOBAL_DATA["servers"]):
                for s in GLOBAL_DATA["servers"]:
                    if s["group"] == target:
                        self.toggle_state[_get_toggle_key(s["group"], s["default_name"])] = True
                save_toggle_state(self.toggle_state)
                await self._force_refresh_all()
                for chunk in self._reply_at(event, f" 已恢复组【{target}】下的所有服务器数据轮询"):
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
                for chunk in self._reply_at(event, f" 已恢复组【{g_name}】下的服务器【{d_name}】数据轮询"):
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
                for chunk in self._reply_at(event, " 全局阻断：所有服务器已停止数据轮询"):
                    yield chunk
            elif any(s["group"] == target for s in GLOBAL_DATA["servers"]):
                for s in GLOBAL_DATA["servers"]:
                    if s["group"] == target:
                        self.toggle_state[_get_toggle_key(s["group"], s["default_name"])] = False
                save_toggle_state(self.toggle_state)
                await self._force_refresh_all()
                for chunk in self._reply_at(event, f" 已批量隔离组【{target}】下的所有服务器数据轮询"):
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
                for chunk in self._reply_at(event, f" 已隔离组【{g_name}】下的服务器【{d_name}】数据轮询"):
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
            save_server_data(GLOBAL_DATA)
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
            for chunk in self._reply_at(event, f" 已将群聊【{target_id}】加入黑名单"):
                yield chunk
        elif subcmd == "删除群":
            if target_id in self.blacklist["groups"]:
                self.blacklist["groups"].remove(target_id)
                save_blacklist(self.blacklist)
            for chunk in self._reply_at(event, f" 已将群聊【{target_id}】移出黑名单"):
                yield chunk
        elif subcmd == "添加人":
            if target_id not in self.blacklist["users"]:
                self.blacklist["users"].append(target_id)
                save_blacklist(self.blacklist)
            for chunk in self._reply_at(event, f" 已将用户【{target_id}】加入全局黑名单"):
                yield chunk
        elif subcmd == "删除人":
            if target_id in self.blacklist["users"]:
                self.blacklist["users"].remove(target_id)
                save_blacklist(self.blacklist)
            for chunk in self._reply_at(event, f" 已将用户【{target_id}】移出黑名单"):
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
    async def enable_fuzzy_match(self, event: AstrMessageEvent):
        if not await self._is_admin(event):
            return
        msg_parts = event.get_message_str().strip().split()
        if len(msg_parts) == 1:
            if event.is_private_chat():
                for chunk in self._reply_at(event, "该命令需要在群聊中使用，或指定群号：/开启模糊匹配 <群号>"):
                    yield chunk
                return
            group_id = str(event.message_obj.group_id)
        else:
            group_id = msg_parts[1].strip()
        self.fuzzy_toggle[group_id] = True
        save_fuzzy_toggle(self.fuzzy_toggle)
        for chunk in self._reply_at(event, f" 群 {group_id} 已开启模糊匹配。"):
            yield chunk

    @filter.command("关闭模糊匹配")
    async def disable_fuzzy_match(self, event: AstrMessageEvent):
        if not await self._is_admin(event):
            return
        msg_parts = event.get_message_str().strip().split()
        if len(msg_parts) == 1:
            if event.is_private_chat():
                for chunk in self._reply_at(event, "该命令需要在群聊中使用，或指定群号：/关闭模糊匹配 <群号>"):
                    yield chunk
                return
            group_id = str(event.message_obj.group_id)
        else:
            group_id = msg_parts[1].strip()
        self.fuzzy_toggle[group_id] = False
        save_fuzzy_toggle(self.fuzzy_toggle)
        for chunk in self._reply_at(event, f" 群 {group_id} 已关闭模糊匹配。"):
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

        if target_group:
            groups_to_show = [g for g in set(s["group"] for s in GLOBAL_DATA["servers"]) if target_group in g]
            if not groups_to_show:
                groups_to_show = [target_group]
        else:
            groups_to_show = list(set(s["group"] for s in GLOBAL_DATA["servers"]))

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
                msg_id = None
                if isinstance(resp, dict) and "data" in resp and isinstance(resp["data"], dict):
                    msg_id = resp["data"].get("message_id")
                if msg_id:
                    msg_id = int(msg_id) if msg_id is not None else None
                    bot = event.bot
                    async def _retract_img():
                        await asyncio.sleep(self.retract_seconds)
                        try:
                            await bot.api.call_action("delete_msg", message_id=msg_id)
                        except Exception:
                            pass
                    asyncio.create_task(_retract_img())
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
                    msg_id = None
                    if isinstance(resp, dict):
                        d = resp.get("data") or resp
                        msg_id = d.get("message_id") if isinstance(d, dict) else (d if isinstance(d, int) else None)
                    if msg_id is not None:
                        msg_id = int(msg_id)
                        bot = event.bot
                        async def _retract_s():
                            await asyncio.sleep(self.retract_seconds)
                            try:
                                await bot.api.call_action("delete_msg", message_id=msg_id)
                            except Exception:
                                pass
                        asyncio.create_task(_retract_s())
                else:
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
        cmd_logs = load_command_logs()
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
                msg_id = None
                if isinstance(resp, dict) and "data" in resp and isinstance(resp["data"], dict):
                    msg_id = resp["data"].get("message_id")
                if msg_id is not None:
                    msg_id = int(msg_id)
                    bot = event.bot
                    async def _retract_log():
                        await asyncio.sleep(self.retract_seconds)
                        try:
                            await bot.api.call_action("delete_msg", message_id=msg_id)
                        except Exception:
                            pass
                    asyncio.create_task(_retract_log())
            else:
                yield event.image_result(img_path)
        except Exception as e:
            logger.warning(f"[服务器框架] 发送日志图片失败: {e}")
            for chunk in self._reply_at(event, "发送日志图片失败。"):
                yield chunk

    def _render_log_image(self, date_str, cmd_logs, err_logs, hist_data, max_count):
        font_name = "C:/Windows/Fonts/msyh.ttc"
        font_bold = "C:/Windows/Fonts/msyhbd.ttc"
        try:
            f_title = ImageFont.truetype(font_bold, 20)
            f_section = ImageFont.truetype(font_bold, 15)
            f_row = ImageFont.truetype(font_name, 12)
        except Exception:
            f_title = f_section = f_row = ImageFont.load_default()

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
                rows.append(f"{t}  {e.get('msg','')[:100]}")

        if hist_data:
            rows.append("")
            rows.append("--- 人数日志 ---")
            for name, entries in hist_data.items():
                vals = [f"{e.get('players','?')}/{e.get('max','?')}" for e in entries[-10:]]
                recent_vals = "  ".join(vals)
                rows.append(f"{name}: {recent_vals}")

        row_h = 22
        img_w = 780
        img_h = len(rows) * row_h + 40
        img = Image.new("RGB", (img_w, img_h), (255, 255, 255))
        draw = ImageDraw.Draw(img)
        for i, line in enumerate(rows):
            y = 15 + i * row_h
            if line.startswith("日志检索"):
                draw.text((20, y), line, fill=(34, 34, 34), font=f_title)
            elif line.startswith("---"):
                draw.text((20, y), line, fill=(74, 144, 226), font=f_section)
            else:
                draw.text((20, y), line, fill=(68, 68, 68), font=f_row)

        path = os.path.join(tempfile.gettempdir(), "astrbot_niufu_log.png")
        img.save(path, "PNG")
        return path

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
            save_server_data(GLOBAL_DATA)
            for chunk in self._reply_at(event, f"消息撤回时间已设为 {t} 秒"):
                yield chunk
        except ValueError:
            for chunk in self._reply_at(event, "请输入 10-300 之间的整数。"):
                yield chunk

    @filter.command("tg设置")
    async def cmd_tg_token(self, event: AstrMessageEvent):
        if not await self._is_admin(event):
            return
        parts = event.get_message_str().strip().split(maxsplit=1)
        if len(parts) < 2:
            token = GLOBAL_DATA.get("telegram_bot_token", "") or "(未设置)"
            chat = GLOBAL_DATA.get("telegram_chat_id", "") or "(未设置)"
            mask = token[:8] + "***" if token != "(未设置)" else token
            for chunk in self._reply_at(event, f"用法：/tg设置 <token>\n/tg设置chat <chat_id>\n当前Token: {mask}\n当前Chat: {chat}"):
                yield chunk
            return
        arg = parts[1].strip()
        if arg.startswith("chat "):
            chat_id = arg[5:].strip()
            GLOBAL_DATA["telegram_chat_id"] = chat_id
            save_server_data(GLOBAL_DATA)
            for chunk in self._reply_at(event, f"Telegram Chat ID 已设为 {chat_id}"):
                yield chunk
        else:
            GLOBAL_DATA["telegram_bot_token"] = arg
            save_server_data(GLOBAL_DATA)
            for chunk in self._reply_at(event, f"Telegram Bot Token 已设置"):
                yield chunk

    def start_tg_polling(self):
        token = GLOBAL_DATA.get("telegram_bot_token", "")
        if not token:
            return
        asyncio.create_task(self._tg_poll_loop(token))

    async def _tg_poll_loop(self, token: str):
        await asyncio.sleep(5)
        offset = 0
        while True:
            try:
                url = f"https://api.telegram.org/bot{token}/getUpdates?timeout=30&offset={offset}"
                async with aiohttp.ClientSession() as sess:
                    async with sess.get(url, timeout=aiohttp.ClientTimeout(total=35)) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            if data.get("ok") and data.get("result"):
                                for upd in data["result"]:
                                    offset = upd["update_id"] + 1
                                    asyncio.create_task(self._tg_handle_update(upd, token))
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
            h = ("通用服务器框架\n"
                 "/牛服 /鸽服 /查服 <组名> /ip [组名]\n"
                 "/历史 [组名] [服名] /统计 [天/周/月] [组名]\n"
                 "/日志 [日期] [条数] /niulog /help\n\n"
                 "直接发送组名(如"牛")也可查询 炸了/卡了等关键词自动回复")
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
            cmd_logs = load_command_logs()
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
            async with aiohttp.ClientSession() as sess:
                await sess.post(url, json={"chat_id": chat_id, "text": text[:4000]}, timeout=aiohttp.ClientTimeout(total=10))
        except Exception:
            pass

    async def _tg_send_photo(self, token: str, chat_id, img_path: str, caption: str = ""):
        try:
            url = f"https://api.telegram.org/bot{token}/sendPhoto"
            form = aiohttp.FormData()
            form.add_field("chat_id", str(chat_id))
            form.add_field("caption", caption[:200])
            form.add_field("photo", open(img_path, "rb"))
            async with aiohttp.ClientSession() as sess:
                await sess.post(url, data=form, timeout=aiohttp.ClientTimeout(total=15))
        except Exception:
            pass

    async def __del__(self):
        if self.session and not self.session.closed:
            await self.session.close()