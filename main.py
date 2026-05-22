import json
import asyncio
from pathlib import Path
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Star, Context, register
from astrbot.api import logger
import aiohttp
import astrbot.api.message_components as Comp

PLUGIN_DIR = Path(__file__).parent
TOGGLE_FILE = PLUGIN_DIR / "toggle_state.json"
SERVER_DATA_FILE = PLUGIN_DIR / "server_data.json"

DEFAULT_SERVER_DATA = {
    "refresh_interval_min": 30,
    "refresh_interval_max": 120,
    "refresh_decay_step": 15,
    "group_triggers": {
      "牛服插件": ["牛服"],
      "牛服纯净": ["牛服"],
      "鸽": ["鸽服"]
    },
    "group_headers": {
      "牛服插件": ["鸢神祈冬&原神高手", "原大牛牛", "=============="],
      "牛服纯净": ["鸢神祈冬&原神高手", "原大牛牛", "=============="],
      "鸽": ["大唐合鸟子社区", "============"]
    },
    "servers": [
        {"id": "59288", "group": "牛服插件", "default_name": "插件1", "display_name": "鸢神祈冬#1"},
        {"id": "72039", "group": "牛服插件", "default_name": "插件2", "display_name": "鸢神祈冬#2"},
        {"id": "102637", "group": "牛服插件", "default_name": "插件3", "display_name": "鸢神祈冬#3"},
        {"id": "72041", "group": "牛服插件", "default_name": "插件4", "display_name": "鸢神祈冬#4"},
        {"id": "99987", "group": "牛服插件", "default_name": "插件5", "display_name": "内测"},
        {"id": "72044", "group": "牛服插件", "default_name": "插件6", "display_name": "鸢神祈冬#6"},
        {"id": "101108", "group": "牛服纯净", "default_name": "纯净1", "display_name": "原神高手#1"},
        {"id": "71164", "group": "牛服纯净", "default_name": "纯净2", "display_name": "原神高手#2"},
        {"id": "71165", "group": "牛服纯净", "default_name": "纯净3", "display_name": "原神高手#3"},
        {"id": "71166", "group": "牛服纯净", "default_name": "纯净4", "display_name": "原神高手#4"},
        {"id": "71167", "group": "牛服纯净", "default_name": "纯净5", "display_name": "原神高手#5"},
        {"id": "101594", "group": "牛服纯净", "default_name": "纯净6", "display_name": "原神高手#6"},
        {"id": "99742", "group": "鸽", "default_name": "鸽1", "display_name": "鸽子一服"},
        {"id": "99743", "group": "鸽", "default_name": "鸽2", "display_name": "鸽子二服"},
        {"id": "99744", "group": "鸽", "default_name": "鸽3", "display_name": "鸽子三服"},
        {"id": "99745", "group": "鸽", "default_name": "鸽4", "display_name": "鸽子四服"},
        {"id": "99746", "group": "鸽", "default_name": "鸽5", "display_name": "鸽子五服"}
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

def load_toggle_state():
    if TOGGLE_FILE.exists():
        with open(TOGGLE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {s["default_name"]: True for s in GLOBAL_DATA["servers"]}

def save_toggle_state(state):
    with open(TOGGLE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def find_cmd_config():
    current = Path(__file__).resolve().parent
    for _ in range(5):
        data_json = current / "data" / "cmd_config.json"
        if data_json.exists():
            return data_json
        current = current.parent
    paths_to_check = [
        Path.cwd() / "data" / "cmd_config.json",
        Path.cwd() / "cmd_config.json",
        Path(__file__).parent / "cmd_config.json"
    ]
    for p in paths_to_check:
        if p.exists():
            return p
    return Path.cwd() / "data" / "cmd_config.json"

async def get_admin_list():
    config_path = find_cmd_config()
    if not config_path.exists():
        logger.warning(f"[牛服插件] 未找到配置文件: {config_path}")
        return []
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        return [str(uid) for uid in config.get("admins_id", [])]
    except Exception as e:
        logger.error(f"[牛服插件] 读取管理员列表失败: {e}")
        return []

async def save_admin_list(admin_list):
    config_path = find_cmd_config()
    try:
        if not config_path.exists():
            config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump({"admins_id": admin_list}, f, ensure_ascii=False, indent=2)
            return
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        config["admins_id"] = admin_list
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        logger.info(f"[牛服插件] 成功同步管理员列表至文件: {config_path}")
    except Exception as e:
        logger.error(f"[牛服插件] 保存管理员列表失败: {e}")

def is_admin(sender_id: str, admin_list: list) -> bool:
    return str(sender_id) in admin_list if admin_list else False

@register("astrbot_plugin_niufu", "niufu", "query", "2.6.0")
class NiufuPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.toggle_state = load_toggle_state()
        self.cache = {}
        self.refresh_task = None
        self.current_interval = GLOBAL_DATA["refresh_interval_min"]
        self.session = None

    async def _get_session(self):
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session

    async def _fetch(self, url):
        try:
            session = await self._get_session()
            async with session.get(url, timeout=5) as resp:
                if resp.status == 200:
                    return await resp.json()
        except Exception:
            pass
        return None

    def _trigger_active_refresh(self):
        self.current_interval = GLOBAL_DATA["refresh_interval_min"]
        if self.refresh_task is None or self.refresh_task.done():
            self.refresh_task = asyncio.create_task(self._refresh_loop())

    async def _build_group_info(self, target_group):
        headers_map = GLOBAL_DATA.get("group_headers", {})
        if target_group in headers_map:
            lines = list(headers_map[target_group])
            sep = lines[-1] if lines else "=============="
        else:
            lines = ["鸢神祈冬&原神高手", "原大牛牛", "=============="]
            sep = "=============="
            
        servers = [s for s in GLOBAL_DATA["servers"] if s["group"] == target_group and self.toggle_state.get(s["default_name"], True)]
        if not servers:
            lines.append("该组别暂无启用的服务器")
            lines.append(sep)
            return lines
            
        urls = [f"https://api.scplist.kr/api/servers/{s['id']}" for s in servers]
        results = await asyncio.gather(*(self._fetch(url) for url in urls))
        for s, data in zip(servers, results):
            if data:
                players = data.get("players", 0)
                max_players = data.get("max_players")
                if max_players is not None:
                    lines.append(f"{s['display_name']} {players}/{max_players}")
                else:
                    lines.append(f"{s['display_name']} {players}")
            else:
                lines.append(f"{s['display_name']} 获取失败")
        lines.append(sep)
        return lines

    async def _build_ip_info(self):
        lines = ["鸢神祈冬&原神高手", "原大牛牛", "=============="]
        servers = [s for s in GLOBAL_DATA["servers"] if s["group"] != "鸽" and self.toggle_state.get(s["default_name"], True)]
        if not servers:
            lines.append("暂无启用服务器")
            lines.append("==============")
            return lines
        urls = [f"https://api.scplist.kr/api/servers/{s['id']}" for s in servers]
        results = await asyncio.gather(*(self._fetch(url) for url in urls))
        for s, data in zip(servers, results):
            if s["display_name"] in ("鸢神祈冬#4", "原神高手#4"):
                lines.append(f"{s['display_name']} 史头不喜欢这个数")
                continue
            if data:
                ip, port = data.get("ip", ""), data.get("port", "")
                if ip and port:
                    lines.append(f"{s['display_name']} {ip}:{port}")
                else:
                    lines.append(f"{s['display_name']} 史头不喜欢这个数")
            else:
                lines.append(f"{s['display_name']} 查询失败")
        lines.append("==============")
        return lines

    async def _refresh_loop(self):
        while True:
            try:
                groups = set(s["group"] for s in GLOBAL_DATA["servers"])
                new_cache = {}
                for g in groups:
                    new_cache[g] = await self._build_group_info(g)
                new_cache["ip"] = await self._build_ip_info()
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
            self.cache["ip"] = await self._build_ip_info()
        except Exception:
            pass

    def _reply_at(self, event, text):
        if event.is_private_chat():
            yield event.plain_result(text)
        else:
            chain = [Comp.At(qq=event.get_sender_id()), Comp.Plain(f"\n{text}")]
            yield event.chain_result(chain)

    @filter.command("help")
    async def help_cmd(self, event: AstrMessageEvent):
        help_text = """📖 牛服插件使用帮助

查询命令
/牛服 - 查看已启用服务器的在线人数
/ip   - 查看已启用服务器的IP地址和端口
/鸽服 - 查看大唐合鸟子社区在线人数

开关命令（仅管理员可用）
/启用端口 <类型><编号>   - 启用指定服务器
/禁用端口 <类型><编号>   - 禁用指定服务器
/启用端口 所有          - 启用所有服务器
/禁用端口 所有          - 禁用所有服务器
/启用端口 所有插件       - 启用所有鸢神祈冬服务器
/禁用端口 所有插件       - 禁用所有鸢神祈冬服务器
/启用端口 所有纯净       - 启用所有原神高手服务器
/禁用端口 所有纯净       - 禁用所有原神高手服务器

鸽服开关命令（仅管理员可用）
/启用鸽服 <编号>        - 启用指定鸽服（1-5）
/禁用鸽服 <编号>        - 禁用指定鸽服（1-5）
/启用鸽服 所有          - 启用所有鸽服
/禁用鸽服 所有          - 禁用所有鸽服"""
        for chunk in self._reply_at(event, help_text):
            yield chunk

    @filter.command("fwq")
    async def fwq_cmd(self, event: AstrMessageEvent):
        msg = event.get_message_str().strip().split()
        if len(msg) > 1 and msg[1].lower() == "help":
            lines = [
                "📖 新型多组别服务器管理帮助",
                "",
                "🛠️ 动态组别配置指令（仅管理员可用）",
                "/查看所有服 - 查看所有组别、识别名与在线启用状态",
                "/列表服     - 功能同上",
                "/添加服 <组别名> <识别名> <ID> <展示名>",
                "/删除服 <组别名> <识别名>",
                "/设置组触发词 <组别名> <触发词1,触发词2...>",
                "/设置组头部文字 <组别名> <文字1|文字2|分隔符>",
                "/改服ID <组别名> <识别名> <新ID>",
                "/改服名 <组别名> <识别名> <新展示名>",
                "/改服组 <原组别名> <识别名> <新组别名>",
                "/启用端口 <识别名/所有/所有组别名>",
                "/禁用端口 <识别名/所有/所有组别名>",
                "/调整刷新 <最小秒数> [最大秒数] - 设定间隔时间"
            ]
            for chunk in self._reply_at(event, "\n".join(lines)):
                yield chunk

    @filter.on_decorating_event
    async def on_message(self, event: AstrMessageEvent):
        msg = event.get_message_str().strip()
        if not msg.startswith("/"): return
        cmd = msg[1:].split()[0]
        if cmd == "ip":
            self._trigger_active_refresh()
            if "ip" not in self.cache or not self.cache["ip"]:
                self.cache["ip"] = await self._build_ip_info()
            event.stop_event()
            for chunk in self._reply_at(event, "\n".join(self.cache["ip"])):
                yield chunk
            return
        matched_group = None
        for g, triggers in GLOBAL_DATA.get("group_triggers", {}).items():
            if cmd in triggers:
                matched_group = g
                break
        if matched_group:
            self._trigger_active_refresh()
            if matched_group not in self.cache or not self.cache[matched_group]:
                self.cache[matched_group] = await self._build_group_info(matched_group)
            event.stop_event()
            for chunk in self._reply_at(event, "\n".join(self.cache[matched_group])):
                yield chunk

    @filter.command("查看所有服")
    async def list_all_servers(self, event: AstrMessageEvent):
        admin_list = await get_admin_list()
        if not is_admin(str(event.get_sender_id()), admin_list): return
        if not GLOBAL_DATA["servers"]:
            for chunk in self._reply_at(event, "当前配置中暂无任何服务器"): yield chunk
            return
        groups_dict = {}
        for s in GLOBAL_DATA["servers"]:
            g = s["group"]
            if g not in groups_dict: groups_dict[g] = []
            groups_dict[g].append(s)
        lines = ["📊 当前所有组别及服务器列表", "================"]
        triggers_map = GLOBAL_DATA.get("group_triggers", {})
        headers_map = GLOBAL_DATA.get("group_headers", {})
        for g, s_list in groups_dict.items():
            t_list = triggers_map.get(g, [])
            t_str = ",".join([f"/{t}" for t in t_list]) if t_list else "未配置"
            h_list = headers_map.get(g, [])
            h_str = " | ".join(h_list) if h_list else "默认"
            lines.append(f"🗂️ 组别: {g}")
            lines.append(f"  🔸 触发词: {t_str}")
            lines.append(f"  🔸 头部字: {h_str}")
            for s in s_list:
                status = "启用" if self.toggle_state.get(s["default_name"], True) else "禁用"
                lines.append(f"    🔹 识别: {s['default_name']} | 名字: {s['display_name']} [ID: {s['id']}] ({status})")
            lines.append("================")
        for chunk in self._reply_at(event, "\n".join(lines)): yield chunk

    @filter.command("列表服")
    async def list_all_servers_alias(self, event: AstrMessageEvent):
        async for chunk in self.list_all_servers(event): yield chunk

    @filter.command("调整刷新")
    async def change_refresh_rate(self, event: AstrMessageEvent):
        admin_list = await get_admin_list()
        if not is_admin(str(event.get_sender_id()), admin_list): return
        msg = event.get_message_str().strip().split()
        if len(msg) < 2:
            for chunk in self._reply_at(event, "用法：/调整刷新 <最小秒数> [最大秒数]"): yield chunk
            return
        try:
            imin = int(msg[1])
            imax = int(msg[2]) if len(msg) > 2 else imin
            if imin < 2 or imax < imin: raise ValueError
            GLOBAL_DATA["refresh_interval_min"] = imin
            GLOBAL_DATA["refresh_interval_max"] = imax
            save_server_data(GLOBAL_DATA)
            self.current_interval = imin
            out = f"已设定为固定刷新：{imin}s" if imin == imax else f"已设定为动态刷新：{imin}s - {imax}s"
            for chunk in self._reply_at(event, out): yield chunk
        except ValueError:
            for chunk in self._reply_at(event, "参数错误：必须为正整数且最小不低于2秒"): yield chunk

    @filter.command("添加服")
    async def add_server(self, event: AstrMessageEvent):
        admin_list = await get_admin_list()
        if not is_admin(str(event.get_sender_id()), admin_list): return
        msg = event.get_message_str().strip().split(maxsplit=4)
        if len(msg) < 5:
            for chunk in self._reply_at(event, "用法：/添加服 <组别名> <识别名> <ID> <展示名>"): yield chunk
            return
        group_name, default_name, sid, display_name = msg[1], msg[2], msg[3], msg[4]
        if any(s["default_name"] == default_name and s["group"] == group_name for s in GLOBAL_DATA["servers"]):
            for chunk in self._reply_at(event, f"错误：该组别下识别名【{default_name}】已存在"): yield chunk
            return
        GLOBAL_DATA["servers"].append({"id": sid, "group": group_name, "default_name": default_name, "display_name": display_name})
        if group_name not in GLOBAL_DATA["group_triggers"]:
            GLOBAL_DATA["group_triggers"][group_name] = [group_name]
        if group_name not in GLOBAL_DATA["group_headers"]:
            GLOBAL_DATA["group_headers"][group_name] = ["鸢神祈冬&原神高手", "原大牛牛", "=============="]
        save_server_data(GLOBAL_DATA)
        self.toggle_state[default_name] = True
        save_toggle_state(self.toggle_state)
        await self._force_refresh_all()
        for chunk in self._reply_at(event, f"成功添加服务器到组【{group_name}】：{display_name}"): yield chunk

    @filter.command("删除服")
    async def del_server(self, event: AstrMessageEvent):
        admin_list = await get_admin_list()
        if not is_admin(str(event.get_sender_id()), admin_list): return
        msg = event.get_message_str().strip().split(maxsplit=2)
        if len(msg) < 3:
            for chunk in self._reply_at(event, "用法：/删除服 <组别名> <识别名>"): yield chunk
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
            
            if not any(s["default_name"] == target_name for s in GLOBAL_DATA["servers"]):
                if target_name in self.toggle_state:
                    self.toggle_state.pop(target_name)
                    save_toggle_state(self.toggle_state)
            await self._force_refresh_all()
            for chunk in self._reply_at(event, f"已成功删除【{group_name}】组下的服务器：{removed['display_name']}"): yield chunk
        else:
            for chunk in self._reply_at(event, f"未找到【{group_name}】组下识别名为【{target_name}】的服务器"): yield chunk

    @filter.command("设置组触发词")
    async def set_group_triggers(self, event: AstrMessageEvent):
        admin_list = await get_admin_list()
        if not is_admin(str(event.get_sender_id()), admin_list): return
        msg = event.get_message_str().strip().split(maxsplit=2)
        if len(msg) < 3:
            for chunk in self._reply_at(event, "用法：/设置组触发词 <组别名> <触发词1,触发词2...>"): yield chunk
            return
        group_name, triggers_str = msg[1], msg[2]
        triggers_list = [t.strip() for t in triggers_str.replace("，", ",").split(",") if t.strip()]
        if not triggers_list:
            for chunk in self._reply_at(event, "错误：触发词列表不能为空"): yield chunk
            return
        GLOBAL_DATA["group_triggers"][group_name] = triggers_list
        save_server_data(GLOBAL_DATA)
        for chunk in self._reply_at(event, f"组【{group_name}】的触发关键词已设定为：{', '.join(triggers_list)}"): yield chunk

    @filter.command("设置组头部文字")
    async def set_group_headers(self, event: AstrMessageEvent):
        admin_list = await get_admin_list()
        if not is_admin(str(event.get_sender_id()), admin_list): return
        msg = event.get_message_str().strip().split(maxsplit=2)
        if len(msg) < 3:
            for chunk in self._reply_at(event, "用法：/设置组头部文字 <组别名> <文字1|文字2|分隔符>"): yield chunk
            return
        group_name, headers_str = msg[1], msg[2]
        headers_list = [h.strip() for h in headers_str.split("|") if h.strip()]
        if not headers_list:
            for chunk in self._reply_at(event, "错误：头部文字格式不正确"): yield chunk
            return
        if "group_headers" not in GLOBAL_DATA:
            GLOBAL_DATA["group_headers"] = {}
        GLOBAL_DATA["group_headers"][group_name] = headers_list
        save_server_data(GLOBAL_DATA)
        await self._force_refresh_all()
        for chunk in self._reply_at(event, f"组【{group_name}】的头部文字设置成功！"): yield chunk

    @filter.command("改服ID")
    async def change_server_id(self, event: AstrMessageEvent):
        admin_list = await get_admin_list()
        if not is_admin(str(event.get_sender_id()), admin_list): return
        msg = event.get_message_str().strip().split(maxsplit=3)
        if len(msg) < 4:
            for chunk in self._reply_at(event, "用法：/改服ID <组别名> <识别名> <新ID>"): yield chunk
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
            for chunk in self._reply_at(event, f"组【{group_name}】内服务器【{target_name}】的ID已变更为：{new_id}"): yield chunk
        else:
            for chunk in self._reply_at(event, f"未找到【{group_name}】组下识别名为【{target_name}】的服务器"): yield chunk

    @filter.command("改服名")
    async def change_server_display(self, event: AstrMessageEvent):
        admin_list = await get_admin_list()
        if not is_admin(str(event.get_sender_id()), admin_list): return
        msg = event.get_message_str().strip().split(maxsplit=3)
        if len(msg) < 4:
            for chunk in self._reply_at(event, "用法：/改服名 <组别名> <识别名> <新展示名>"): yield chunk
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
            for chunk in self._reply_at(event, f"组【{group_name}】内服务器【{target_name}】的展示名称已变更为：{new_display}"): yield chunk
        else:
            for chunk in self._reply_at(event, f"未找到【{group_name}】组下识别名为【{target_name}】的服务器"): yield chunk

    @filter.command("改服组")
    async def change_server_group(self, event: AstrMessageEvent):
        admin_list = await get_admin_list()
        if not is_admin(str(event.get_sender_id()), admin_list): return
        msg = event.get_message_str().strip().split(maxsplit=3)
        if len(msg) < 4:
            for chunk in self._reply_at(event, "用法：/改服组 <原组别名> <识别名> <新组别名>"): yield chunk
            return
        old_group, target_name, new_group = msg[1], msg[2], msg[3]
        found = False
        for s in GLOBAL_DATA["servers"]:
            if s["group"] == old_group and s["default_name"] == target_name:
                s["group"] = new_group
                found = True
                break
        if found:
            if new_group not in GLOBAL_DATA["group_triggers"]:
                GLOBAL_DATA["group_triggers"][new_group] = [new_group]
            if new_group not in GLOBAL_DATA["group_headers"]:
                GLOBAL_DATA["group_headers"][new_group] = ["鸢神祈冬&原神高手", "原大牛牛", "=============="]
            save_server_data(GLOBAL_DATA)
            await self._force_refresh_all()
            for chunk in self._reply_at(event, f"服务器【{target_name}】已成功从【{old_group}】移到新组：{new_group}"): yield chunk
        else:
            for chunk in self._reply_at(event, f"未找到【{old_group}】组下识别名为【{target_name}】的服务器"): yield chunk

    @filter.command("启用端口")
    async def enable(self, event: AstrMessageEvent):
        admin_list = await get_admin_list()
        if not is_admin(str(event.get_sender_id()), admin_list): return
        msg = event.get_message_str().strip()
        parts = msg.split(maxsplit=1)
        if len(parts) < 2:
            for chunk in self._reply_at(event, "用法：/启用端口 <识别名> 或 所有 / 所有[组别名]"): yield chunk
            return
        target = parts[1].strip()
        if target == "所有":
            for s in GLOBAL_DATA["servers"]: self.toggle_state[s["default_name"]] = True
            save_toggle_state(self.toggle_state)
            await self._force_refresh_all()
            for chunk in self._reply_at(event, "已启用所有服务器"): yield chunk
        elif target.startswith("所有") and len(target) > 2:
            group_target = target[2:]
            for s in GLOBAL_DATA["servers"]:
                if s["group"] == group_target: self.toggle_state[s["default_name"]] = True
            save_toggle_state(self.toggle_state)
            await self._force_refresh_all()
            for chunk in self._reply_at(event, f"已启用所有【{group_target}】组别的服务器"): yield chunk
        else:
            if any(s["default_name"] == target for s in GLOBAL_DATA["servers"]):
                self.toggle_state[target] = True
                save_toggle_state(self.toggle_state)
                await self._force_refresh_all()
                for chunk in self._reply_at(event, f"已启用服务器识别名：{target}"): yield chunk
            else:
                for chunk in self._reply_at(event, f"未找到识别名为【{target}】的服务器"): yield chunk

    @filter.command("禁用端口")
    async def disable(self, event: AstrMessageEvent):
        admin_list = await get_admin_list()
        if not is_admin(str(event.get_sender_id()), admin_list): return
        msg = event.get_message_str().strip()
        parts = msg.split(maxsplit=1)
        if len(parts) < 2:
            for chunk in self._reply_at(event, "用法：/禁用端口 <识别名> 或 所有 / 所有[组别名]"): yield chunk
            return
        target = parts[1].strip()
        if target == "所有":
            for s in GLOBAL_DATA["servers"]: self.toggle_state[s["default_name"]] = False
            save_toggle_state(self.toggle_state)
            await self._force_refresh_all()
            for chunk in self._reply_at(event, "已禁用所有服务器"): yield chunk
        elif target.startswith("所有") and len(target) > 2:
            group_target = target[2:]
            for s in GLOBAL_DATA["servers"]:
                if s["group"] == group_target: self.toggle_state[s["default_name"]] = False
            save_toggle_state(self.toggle_state)
            await self._force_refresh_all()
            for chunk in self._reply_at(event, f"已禁用所有【{group_target}】组别的服务器"): yield chunk
        else:
            if any(s["default_name"] == target for s in GLOBAL_DATA["servers"]):
                self.toggle_state[target] = False
                save_toggle_state(self.toggle_state)
                await self._force_refresh_all()
                for chunk in self._reply_at(event, f"已禁用服务器识别名：{target}"): yield chunk
            else:
                for chunk in self._reply_at(event, f"未找到识别名为【{target}】的服务器"): yield chunk

    @filter.command("管理")
    async def admin_command(self, event: AstrMessageEvent):
        admin_list = await get_admin_list()
        sender_id = str(event.get_sender_id())
        if not is_admin(sender_id, admin_list): return
        msg = event.get_message_str().strip()
        parts = msg.split(maxsplit=2)
        if len(parts) < 2:
            for chunk in self._reply_at(event, "用法：/管理 add <QQ号> 或 /管理 remove <QQ号> 或 /管理 list"): yield chunk
            return
        subcmd = parts[1].lower()
        if subcmd == "list":
            if not admin_list:
                for chunk in self._reply_at(event, "当前没有管理员"): yield chunk
            else:
                lines = ["当前管理员列表："] + [f"{i+1}. {uid}" for i, uid in enumerate(admin_list)]
                for chunk in self._reply_at(event, "\n".join(lines)): yield chunk
            return
        if len(parts) < 3:
            for chunk in self._reply_at(event, "请提供QQ号"): yield chunk
            return
        qq = parts[2].strip()
        if not qq.isdigit():
            for chunk in self._reply_at(event, "QQ号必须为纯数字"): yield chunk
            return
        if subcmd == "add":
            if qq in admin_list:
                for chunk in self._reply_at(event, f"QQ {qq} 已经是管理员了"): yield chunk
            else:
                admin_list.append(qq)
                await save_admin_list(admin_list)
                for chunk in self._reply_at(event, f"已成功添加 {qq} 为管理员"): yield chunk
        elif subcmd in ("remove", "del"):
            if qq not in admin_list:
                for chunk in self._reply_at(event, f"QQ {qq} 本来就不是管理员"): yield chunk
            else:
                admin_list.remove(qq)
                await save_admin_list(admin_list)
                for chunk in self._reply_at(event, f"已成功移除 {qq} 的管理员权限"): yield chunk
        else:
            for chunk in self._reply_at(event, "未知子命令，可用：add, remove, list"): yield chunk

    async def __del__(self):
        if self.session and not self.session.closed:
            await self.session.close()