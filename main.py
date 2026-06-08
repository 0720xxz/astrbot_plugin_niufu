import json
import asyncio
import re
from pathlib import Path
from datetime import datetime
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Star, Context, register
from astrbot.api import logger
import aiohttp
import astrbot.api.message_components as Comp

PLUGIN_DIR = Path(__file__).parent
TOGGLE_FILE = PLUGIN_DIR / "toggle_state.json"
SERVER_DATA_FILE = PLUGIN_DIR / "server_data.json"
BLACKLIST_FILE = PLUGIN_DIR / "blacklist.json"
GROUP_BINDING_FILE = PLUGIN_DIR / "group_bindings.json"
FUZZY_TOGGLE_FILE = PLUGIN_DIR / "fuzzy_toggle.json"
GROUP_NOSLASH_FILE = PLUGIN_DIR / "group_noslash.json"

DEFAULT_SERVER_DATA = {
    "refresh_interval_min": 30,
    "refresh_interval_max": 120,
    "refresh_decay_step": 15,
    "group_headers": {
        "示范组": ["--- 通用服务器框架 ---", "=================="]
    },
    "servers": [
        {"id": "59288", "group": "示范组", "default_name": "示范服1", "display_name": "测试服务器"}
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


@register("astrbot_plugin_niufu", "内战狂热爱好者", "Dynamic Server Framework", "3.8")
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
        self.error_logs: list[dict] = []
        self.error_log_max = 50
        self.server_history: dict[str, list] = {}  # {display_name: [(time_str, players, max_players), ...]}
        self.history_max = 30

    async def _get_session(self):
        if self.session is None or self.session.closed:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AstrBot-SCP-Query/3.8",
                "Accept": "application/json",
            }
            self.session = aiohttp.ClientSession(headers=headers)
        return self.session

    async def _fetch(self, url):
        try:
            session = await self._get_session()
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    return await resp.json()
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

    def _save_history(self, display_name: str, players, max_players):
        key = display_name
        if key not in self.server_history:
            self.server_history[key] = []
        p = int(str(players).split("/")[0]) if players else 0
        m = max_players if max_players is not None else (int(str(players).split("/")[1]) if players and "/" in str(players) else 0)
        self.server_history[key].append({
            "time": datetime.now().strftime("%m-%d %H:%M"),
            "players": p,
            "max": m
        })
        if len(self.server_history[key]) > self.history_max:
            self.server_history[key] = self.server_history[key][-self.history_max:]

    def _build_history_chart_html(self, groups_to_show: list) -> str:
        """用 SVG 折线图渲染服务器历史数据，返回 HTML 字符串"""
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
                if name in shown:
                    continue
                shown.add(name)
                entries = self.server_history.get(name, [])
                if entries and len(entries) >= 1:
                    server_data.append((name, entries, colors[ci % len(colors)]))
                    ci += 1

        if not server_data:
            return ""

        # 统一用所有服务器的最大玩家数作为 Y 轴上限，方便横向对比
        global_max = max((e["players"] for _, entries, _ in server_data for e in entries), default=1)
        if global_max <= 10:
            y_ceil = 10
        elif global_max <= 30:
            y_ceil = ((global_max // 5) + 1) * 5
        elif global_max <= 60:
            y_ceil = ((global_max // 10) + 1) * 10
        else:
            y_ceil = ((global_max // 20) + 1) * 20

        # 找出最长的数据序列，统一 X 轴
        max_len = max(len(entries) for _, entries, _ in server_data)
        total_w = min(max_len * 28, 720)
        chart_w = total_w
        chart_h = 150
        pad_l, pad_r, pad_t, pad_b = 38, 8, 8, 28
        plot_w = chart_w - pad_l - pad_r
        plot_h = chart_h - pad_t - pad_b

        rows_html = []
        for name, entries, color in server_data:
            values = [e["players"] for e in entries]
            n = len(values)
            if n == 1:
                xs = [pad_l + plot_w / 2]
            else:
                xs = [pad_l + i * plot_w / (n - 1) for i in range(n)]

            def y_pos(v):
                return pad_t + plot_h - (v / y_ceil) * plot_h

            svg = []
            # 水平网格线
            for i in range(5):
                y = pad_t + i * plot_h / 4
                svg.append(f'<line x1="{pad_l}" y1="{y:.1f}" x2="{pad_l + plot_w}" y2="{y:.1f}" stroke="#eee" stroke-width="1"/>')
            # Y 轴刻度
            for i in range(5):
                v = y_ceil - i * y_ceil / 4
                y = pad_t + i * plot_h / 4
                svg.append(f'<text x="{pad_l - 4}" y="{y + 4:.1f}" text-anchor="end" font-size="10" fill="#999">{int(v)}</text>')
            # 折线
            pts = " ".join(f"{x:.1f},{y_pos(v):.1f}" for x, v in zip(xs, values))
            svg.append(f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>')
            # 数据点
            for x, v in zip(xs, values):
                svg.append(f'<circle cx="{x:.1f}" cy="{y_pos(v):.1f}" r="3" fill="{color}"/>')
            # X 轴时间标签（每 5 个显示一个）
            times = [e["time"] for e in entries]
            step = max(1, n // 6)
            for i in range(0, n, step):
                x = xs[i]
                svg.append(f'<text x="{x:.1f}" y="{pad_t + plot_h + 18}" text-anchor="middle" font-size="10" fill="#999">{times[i]}</text>')

            svg_str = "".join(svg)
            latest = entries[-1]
            cur = f"{latest['players']}/{latest['max']}" if latest['max'] > 0 else str(latest['players'])
            peak = max(values)

            rows_html.append(f'''<div style="display:flex;align-items:center;margin:0 0 10px 0;padding:6px 0;border-bottom:1px solid #f0f0f0;">
<div style="width:90px;text-align:right;padding-right:10px;font-size:13px;font-weight:bold;color:#333;flex-shrink:0;">{name}</div>
<svg width="{chart_w}" height="{chart_h}" viewBox="0 0 {chart_w} {chart_h}" xmlns="http://www.w3.org/2000/svg">{svg_str}</svg>
<div style="width:70px;text-align:center;font-size:14px;font-weight:bold;color:{color};flex-shrink:0;">{cur}</div>
<div style="width:40px;text-align:center;font-size:11px;color:#aaa;flex-shrink:0;">峰值{peak}</div>
</div>''')

        title = groups_to_show[0] if groups_to_show else "全部组别"
        html = f'''<!DOCTYPE html><html><head><meta charset="utf-8"><style>
body{{font-family:"Microsoft YaHei",sans-serif;margin:12px 16px;background:#fff;}}
</style></head><body>
<h3 style="color:#222;margin:0 0 2px 0;">{title} 在线人数趋势</h3>
<p style="color:#aaa;font-size:11px;margin:0 0 14px 0;">Y轴范围 0-{y_ceil}人 | 横轴左旧右新 | 最多{max_len}轮</p>
{"".join(rows_html)}
</body></html>'''
        return html

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
        results = await asyncio.gather(*(self._fetch(url) for url in urls))
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
        """聚合多个组别到一个输出，共享第一个组的头部，组间用分隔线隔开。
        如果只有一个逻辑组，则按服务器名前缀（去掉 #数字）拆分子区块。"""
        if not groups:
            return ["暂无可用组别", "=============="]
        headers_map = GLOBAL_DATA.get("group_headers", {})
        main_group = groups[0]
        header = headers_map.get(main_group, [f"--- {main_group} 状态 ---", "=============="])
        header_lines = header[:-1] if len(header) > 1 and header[-1].startswith("=") else header
        lines = header_lines.copy()
        lines.append("==============")

        # 收集所有服务器
        all_servers = []
        for g in groups:
            servers = [s for s in GLOBAL_DATA["servers"] if s["group"] == g
                       and self.toggle_state.get(_get_toggle_key(s["group"], s["default_name"]), True)]
            all_servers.extend(servers)

        if not all_servers:
            lines.append("该组别暂无启用的服务器")
            lines.append("==============")
            return lines

        # 如果只有一个逻辑组，按展示名前缀拆分子区块
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
            # 多组时每组一个区块
            sub_groups = [[s for s in all_servers if s["group"] == g] for g in groups]
            sub_groups = [sg for sg in sub_groups if sg]

        all_empty = True
        for sg in sub_groups:
            sg.sort(key=lambda x: self._extract_number(x["display_name"]))
            urls = [f"https://api.scplist.kr/api/servers/{s['id']}" for s in sg]
            results = await asyncio.gather(*(self._fetch(url) for url in urls))
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
        results = await asyncio.gather(*(self._fetch(url) for url in urls))
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

    def _reply_at(self, event, text):
        if event.is_private_chat():
            yield event.plain_result(text)
        else:
            chain = [Comp.At(qq=event.get_sender_id()), Comp.Plain(f"\n{text}")]
            yield event.chain_result(chain)

    ADMIN_COMMANDS = [
        "/查看所有服", "/添加服", "/删除服", "/启用端口", "/禁用端口",
        "/黑名单", "/设置组头部文字", "/改服ID", "/改服名", "/改服组",
        "/调整刷新", "/绑定组", "/解绑组", "/开启模糊匹配", "/关闭模糊匹配",
        "/开启无斜杠", "/关闭无斜杠", "/niulog", "/牛服日志", "/清除日志", "/历史"
    ]

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_message(self, event: AstrMessageEvent):
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
            "/查服", "/ip", "/help", "/查看所有服", "/添加服", "/删除服",
            "/启用端口", "/禁用端口", "/黑名单", "/设置组头部文字", "/改服ID",
            "/改服名", "/改服组", "/调整刷新", "/绑定组", "/解绑组",
            "/开启模糊匹配", "/关闭模糊匹配", "/开启无斜杠", "/关闭无斜杠",
            "/牛服", "/鸽服", "/niulog", "/牛服日志", "/清除日志", "/历史"
        ]
        for cmd in registered_commands:
            if cmd in msg_lower:
                return
        trigger_keywords = ["炸了", "服务器炸了", "炸服", "卡了", "连不上", "宕机", "崩了"]
        if any(keyword in msg_lower for keyword in trigger_keywords):
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
        # 无斜杠触发：仅当消息不含 / 且不以注册指令关键词开头
        has_slash = "/" in msg_lower
        has_cmd = any(msg_lower.startswith(cmd.lstrip("/")) for cmd in registered_commands)
        if not has_slash and not has_cmd:
            all_groups = set(s["group"] for s in GLOBAL_DATA["servers"])
            for g in all_groups:
                if g in msg_lower and is_noslash_enabled(g, self.group_noslash):
                    self._trigger_active_refresh()
                    data = await self._build_group_info(g)
                    for chunk in self._reply_at(event, "\n".join(data)):
                        yield chunk
                    event.stop_event()
                    return

    @filter.command("牛服")
    async def cmd_niufu(self, event: AstrMessageEvent):
        if self._is_blacklisted(event): return
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
        help_text = """ 通用服务器框架使用帮助

【快捷查询】
/牛服 - 查询“牛”组状态
/鸽服 - 查询“鸽”组状态
/查服 <组名> - 查询任意组状态
/ip [组名] - 查询服务器IP与端口
/历史 [组名] - 查看人数历史趋势图（折线图渲染为图片）

【管理员指令】（仅管理员可用）
/查看所有服 - 查看所有组别、服务器及启用状态
/添加服 <组别> <识别名> <API_ID> <展示名>
/删除服 <组别> <识别名>
/启用端口 所有/<组别> 或 /启用端口 <组别> <识别名>
/禁用端口 所有/<组别> 或 /禁用端口 <组别> <识别名>
/黑名单 <添加群/删除群/添加人/删除人> <号码>
/设置组头部文字 <组别> <第一行|第二行|分隔符>
/改服ID <组别> <识别名> <新ID>
/改服名 <组别> <识别名> <新展示名>
/改服组 <原组别> <识别名> <新组别>
/调整刷新 <最小秒数> [最大秒数]
/绑定组 <组名> 或 /绑定组 <群号> <组名> - 将群绑定到指定组（关键词“炸了”等生效）
/解绑组 [群号] - 解除群绑定
/开启模糊匹配 [群号] - 开启当前群或指定群的触发词提示（默认开启）
/关闭模糊匹配 [群号] - 关闭触发词提示
/开启无斜杠 <组名> - 允许直接发送组名（不带/）查询
/关闭无斜杠 <组名> - 禁止直接发送组名查询
/niulog 或 /牛服日志 - 查看最近的服务器查询错误日志
/清除日志 - 清空错误日志记录
/历史 [组名] - 查看服务器在线人数历史趋势图（渲染为图片）

【智能触发】
- 当群已绑定时，发送“炸了/卡了/连不上/宕机/崩了”自动返回该组状态
- 当群未绑定时，发送上述关键词会提示绑定
- 模糊匹配：发送“牛服”等触发词会提示使用 /查服 命令
- 无斜杠触发（需管理员开启）：直接发送组名（如“牛”）即可查询

 所有开关状态均保存在插件目录下的json文件中，重启机器人后依然有效。"""
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
        msg = event.get_message_str().strip().split(maxsplit=1)
        target_group = msg[1].strip() if len(msg) > 1 else None

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

        html = self._build_history_chart_html(groups_to_show)
        if not html:
            for chunk in self._reply_at(event, "暂无历史数据，请先使用 /牛服 或 /查服 生成数据。"):
                yield chunk
            return

        try:
            server_count = sum(1 for g in groups_to_show
                               for s in GLOBAL_DATA["servers"] if s["group"] == g
                               and self.toggle_state.get(_get_toggle_key(s["group"], s["default_name"]), True)
                               and s["display_name"] in self.server_history)
            img_h = 80 + max(server_count, 1) * 170
            url = await self.html_render(html, {}, options={
                "type": "png",
                "full_page": False,
                "clip": {"x": 0, "y": 0, "width": 860, "height": img_h},
                "scale": "device",
                "device_scale_factor_level": "ultra",
            })
            yield event.image_result(url)
            # 30秒后自动撤回图片
            self._schedule_retract(event)
        except Exception as e:
            err_msg = f"渲染历史图表失败: {e}"
            logger.warning(f"[服务器框架] {err_msg}")
            self._log_error(err_msg)
            for chunk in self._reply_at(event, "渲染图表失败，请稍后重试。"):
                yield chunk

    def _schedule_retract(self, event: AstrMessageEvent):
        """30秒后尝试撤回已发送的图片消息"""
        async def _retract():
            await asyncio.sleep(30)
            try:
                adapter = event.get_platform_adapter()
                if adapter and hasattr(adapter, 'delete_message'):
                    await adapter.delete_message(event)
                elif hasattr(event, 'bot') and hasattr(event.bot, 'api'):
                    msg_id = event.message_obj.message_id if hasattr(event, 'message_obj') else None
                    if msg_id:
                        await event.bot.api.call_action("delete_msg", message_id=msg_id)
            except Exception:
                pass
        asyncio.create_task(_retract())

    async def __del__(self):
        if self.session and not self.session.closed:
            await self.session.close()