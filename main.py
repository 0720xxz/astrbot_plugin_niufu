import json
import asyncio
import re
from pathlib import Path
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Star, Context, register
from astrbot.api import logger
import aiohttp
import astrbot.api.message_components as Comp

PLUGIN_DIR = Path(__file__).parent
TOGGLE_FILE = PLUGIN_DIR / "toggle_state.json"
SERVER_DATA_FILE = PLUGIN_DIR / "server_data.json"
BLACKLIST_FILE = PLUGIN_DIR / "blacklist.json"

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


@register("astrbot_plugin_niufu", "内战狂热爱好者", "Dynamic Server Framework", "3.4")
class UniversalServerPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.toggle_state = load_toggle_state()
        self.blacklist = load_blacklist()
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
        """从 display_name 中提取数字，支持阿拉伯数字和中文数字"""
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
        return 0

    async def _build_group_info(self, target_group):
        headers_map = GLOBAL_DATA.get("group_headers", {})
        if target_group in headers_map:
            lines = list(headers_map[target_group])
        else:
            lines = [f"--- {target_group} 状态 ---", "=============="]
            
        servers = [s for s in GLOBAL_DATA["servers"] if s["group"] == target_group and self.toggle_state.get(_get_toggle_key(s["group"], s["default_name"]), True)]
        servers.sort(key=lambda x: self._extract_number(x["display_name"]))
        
        if not servers:
            lines.insert(1, "该组别暂无启用的服务器")
            return lines
            
        urls = [f"https://api.scplist.kr/api/servers/{s['id']}" for s in servers]
        results = await asyncio.gather(*(self._fetch(url) for url in urls))
        
        insert_idx = len(lines) - 1 if len(lines) > 0 else 0
        for s, data in zip(servers, results):
            if data:
                players = data.get("players", 0)
                max_players = data.get("max_players")
                status_str = f"{s['display_name']} {players}/{max_players}" if max_players is not None else f"{s['display_name']} {players}"
                lines.insert(insert_idx, status_str)
            else:
                lines.insert(insert_idx, f"{s['display_name']} 获取失败")
            insert_idx += 1
            
        return lines

    async def _build_ip_info(self, target_group=None):
        lines = ["🌐 服务器端口与IP映射", "=============="]
        servers = GLOBAL_DATA["servers"]
        if target_group:
            servers = [s for s in servers if s["group"] == target_group]
            
        active_servers = [s for s in servers if self.toggle_state.get(_get_toggle_key(s["group"], s["default_name"]), True)]
        active_servers.sort(key=lambda x: self._extract_number(x["display_name"]))
        
        if not active_servers:
            lines.insert(1, "暂无启用的服务器")
            return lines
            
        urls = [f"https://api.scplist.kr/api/servers/{s['id']}" for s in active_servers]
        results = await asyncio.gather(*(self._fetch(url) for url in active_servers))
        
        insert_idx = len(lines) - 1
        for s, data in zip(active_servers, results):
            if data:
                ip, port = data.get("ip", ""), data.get("port", "")
                if ip and port:
                    lines.insert(insert_idx, f"[{s['group']}] {s['display_name']} ➔ {ip}:{port}")
                else:
                    lines.insert(insert_idx, f"[{s['group']}] {s['display_name']} ➔ 无法提取连接地址")
            else:
                lines.insert(insert_idx, f"[{s['group']}] {s['display_name']} ➔ 查询超时")
            insert_idx += 1
            
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

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_message(self, event: AstrMessageEvent):
        if self._is_blacklisted(event):
            return
            
        msg_str = event.get_message_str().strip()
        
        registered_commands = [
            "/查服", "/ip", "/help", "/查看所有服", "/添加服", "/删除服",
            "/启用端口", "/禁用端口", "/黑名单", "/设置组头部文字", "/改服ID",
            "/改服名", "/改服组", "/调整刷新"
        ]
        
        for cmd in registered_commands:
            if cmd in msg_str:
                return
        
        if msg_str.startswith("/") or msg_str.startswith("!"):
            return

        matched_server = None
        matched_group = None

        for s in GLOBAL_DATA.get("servers", []):
            if s["default_name"] in msg_str or s["display_name"] in msg_str:
                matched_server = s
                break
            if s["group"] in msg_str:
                matched_group = s["group"]
                break

        if matched_server or matched_group:
            target_name = matched_server['display_name'] if matched_server else matched_group
            suggest_group = matched_server['group'] if matched_server else matched_group
            hint_msg = (
                f"💡 发现您提到了服务器【{target_name}】。\n"
                f"如果您想要了解它当前的运行状态，可以直接使用以下命令进行互动哦：\n"
                f"👉 查询人数状态：/查服 {suggest_group}\n"
                f"👉 获取连接地址：/ip {suggest_group}\n"
                f"💡 遇到问题不用猜，不懂就要问！输入 /help 可了解更多控制命令。"
            )
            for chunk in self._reply_at(event, hint_msg):
                yield chunk

    @filter.command("查服")
    async def query_generic_group(self, event: AstrMessageEvent):
        if self._is_blacklisted(event): return
        self._trigger_active_refresh()
        msg = event.get_message_str().strip().split(maxsplit=1)
        if len(msg) < 2:
            groups = list(set(s["group"] for s in GLOBAL_DATA["servers"]))
            groups_str = ", ".join(groups) if groups else "暂无任何配置"
            for chunk in self._reply_at(event, f"💡 请提供要查询的组别名称。\n当前已有组别: {groups_str}\n用法: /查服 <组别名>"):
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
        help_text = """📖 通用服务器框架使用帮助

基础查询
/查服 <组别名> - 实时查询指定服务器组的在线人数
/ip [组别名]   - 查询服务器的公网连接地址与开放端口

🛠 动态配置指令（仅管理员可用）
/查看所有服 - 查看所有组别、唯一识别名与启停状态
/添加服 <组别名> <识别名> <API_ID> <展示名>
/删除服 <组别名> <识别名>
/启用端口 <所有/组别名> 或 /启用端口 <组别名> <识别名>
/禁用端口 <所有/组别名> 或 /禁用端口 <组别名> <识别名>
/黑名单 <添加群/删除群/添加人/删除人> <号码>
/设置组头部文字 <组别名> <第一行|第二行|分隔符>
/改服ID <组别名> <识别名> <新ID>
/改服名 <组别名> <识别名> <新展示名>
/改服组 <原组别名> <识别名> <新组别名>
/调整刷新 <最小秒数> [最大秒数]"""
        for chunk in self._reply_at(event, help_text):
            yield chunk

    @filter.command("黑名单")
    async def handle_blacklist_cmd(self, event: AstrMessageEvent):
        if not await self._is_admin(event): return
        msg = event.get_message_str().strip().split()
        if len(msg) < 3:
            for chunk in self._reply_at(event, "用法：/黑名单 <添加群/删除群/添加人/删除人> <号码>"): yield chunk
            return
        subcmd, target_id = msg[1], msg[2]
        if subcmd == "添加群":
            if target_id not in self.blacklist["groups"]:
                self.blacklist["groups"].append(target_id)
                save_blacklist(self.blacklist)
            for chunk in self._reply_at(event, f"🚫 已将群聊【{target_id}】加入黑名单"): yield chunk
        elif subcmd == "删除群":
            if target_id in self.blacklist["groups"]:
                self.blacklist["groups"].remove(target_id)
                save_blacklist(self.blacklist)
            for chunk in self._reply_at(event, f"✅ 已将群聊【{target_id}】移出黑名单"): yield chunk
        elif subcmd == "添加人":
            if target_id not in self.blacklist["users"]:
                self.blacklist["users"].append(target_id)
                save_blacklist(self.blacklist)
            for chunk in self._reply_at(event, f"🚫 已将用户【{target_id}】加入全局黑名单"): yield chunk
        elif subcmd == "删除人":
            if target_id in self.blacklist["users"]:
                self.blacklist["users"].remove(target_id)
                save_blacklist(self.blacklist)
            for chunk in self._reply_at(event, f"✅ 已将用户【{target_id}】移出黑名单"): yield chunk
        else:
            for chunk in self._reply_at(event, "未知黑名单子命令。"): yield chunk

    @filter.command("查看所有服")
    async def list_all_servers(self, event: AstrMessageEvent):
        if not await self._is_admin(event): return
        if not GLOBAL_DATA["servers"]:
            for chunk in self._reply_at(event, "当前配置中暂无任何服务器"): yield chunk
            return
        groups_dict = {}
        for s in GLOBAL_DATA["servers"]:
            g = s["group"]
            if g not in groups_dict: groups_dict[g] = []
            groups_dict[g].append(s)
        lines = ["📊 核心架构全组别清单", "================"]
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
        for chunk in self._reply_at(event, "\n".join(lines)): yield chunk

    @filter.command("调整刷新")
    async def change_refresh_rate(self, event: AstrMessageEvent):
        if not await self._is_admin(event): return
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
            out = f"已设定固定轮询速率：{imin}s" if imin == imax else f"已设定动态轮询区间：{imin}s - {imax}s"
            for chunk in self._reply_at(event, out): yield chunk
        except ValueError:
            for chunk in self._reply_at(event, "参数错误：刷新速率最低不可低于2秒"): yield chunk

    @filter.command("添加服")
    async def add_server(self, event: AstrMessageEvent):
        if not await self._is_admin(event): return
        msg = event.get_message_str().strip().split(maxsplit=4)
        if len(msg) < 5:
            for chunk in self._reply_at(event, "用法：/添加服 <组别名> <识别名> <API_ID> <展示名>"): yield chunk
            return
        group_name, default_name, sid, display_name = msg[1], msg[2], msg[3], msg[4]
        if any(s["default_name"] == default_name and s["group"] == group_name for s in GLOBAL_DATA["servers"]):
            for chunk in self._reply_at(event, f"❌ 冲突：组别【{group_name}】下识别名【{default_name}】已存在"): yield chunk
            return
        GLOBAL_DATA["servers"].append({"id": sid, "group": group_name, "default_name": default_name, "display_name": display_name})
        if group_name not in GLOBAL_DATA["group_headers"]:
            GLOBAL_DATA["group_headers"][group_name] = [f"--- {group_name} 状态 ---", "=============="]
        save_server_data(GLOBAL_DATA)
        self.toggle_state[_get_toggle_key(group_name, default_name)] = True
        save_toggle_state(self.toggle_state)
        await self._force_refresh_all()
        for chunk in self._reply_at(event, f"✅ 成功将【{display_name}】挂载 to 动态组【{group_name}】"): yield chunk

    @filter.command("删除服")
    async def del_server(self, event: AstrMessageEvent):
        if not await self._is_admin(event): return
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
            t_key = _get_toggle_key(group_name, target_name)
            if t_key in self.toggle_state:
                self.toggle_state.pop(t_key)
                save_toggle_state(self.toggle_state)
            await self._force_refresh_all()
            for chunk in self._reply_at(event, f"🗑️ 已从系统卸载【{group_name}】组下的服务器：{removed['display_name']}"): yield chunk
        else:
            for chunk in self._reply_at(event, f"❌ 未找到组【{group_name}】下识别名为【{target_name}】的资产"): yield chunk

    @filter.command("设置组头部文字")
    async def set_group_headers(self, event: AstrMessageEvent):
        if not await self._is_admin(event): return
        msg = event.get_message_str().strip().split(maxsplit=2)
        if len(msg) < 3:
            for chunk in self._reply_at(event, "用法：/设置组头部文字 <组别名> <第一行|第二行|分隔符>"): yield chunk
            return
        group_name, headers_str = msg[1], msg[2]
        headers_list = [h.strip() for h in headers_str.split("|") if h.strip()]
        if not headers_list:
            for chunk in self._reply_at(event, "错误：格式不规范，请用 | 符号分隔"): yield chunk
            return
        if "group_headers" not in GLOBAL_DATA:
            GLOBAL_DATA["group_headers"] = {}
        GLOBAL_DATA["group_headers"][group_name] = headers_list
        save_server_data(GLOBAL_DATA)
        await self._force_refresh_all()
        for chunk in self._reply_at(event, f"📝 组【{group_name}】的报头渲染模板更新完毕！"): yield chunk

    @filter.command("改服ID")
    async def change_server_id(self, event: AstrMessageEvent):
        if not await self._is_admin(event): return
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
            for chunk in self._reply_at(event, f"🔧 组【{group_name}】内服务器【{target_name}】的API_ID已变更为：{new_id}"): yield chunk
        else:
            for chunk in self._reply_at(event, f"❌ 找不到该指定服务器"): yield chunk

    @filter.command("改服名")
    async def change_server_display(self, event: AstrMessageEvent):
        if not await self._is_admin(event): return
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
            for chunk in self._reply_at(event, f"🔧 组【{group_name}】内服务器【{target_name}】的展现别名已变更为：{new_display}"): yield chunk
        else:
            for chunk in self._reply_at(event, f"❌ 找不到该指定服务器"): yield chunk

    @filter.command("改服组")
    async def change_server_group(self, event: AstrMessageEvent):
        if not await self._is_admin(event): return
        msg = event.get_message_str().strip().split(maxsplit=3)
        if len(msg) < 4:
            for chunk in self._reply_at(event, "用法：/改服组 <原组别名> <识别名> <新组别名>"): yield chunk
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
            for chunk in self._reply_at(event, f"📦 成功跨组迁移：服务器【{target_name}】已移入【{new_group}】"): yield chunk
        else:
            for chunk in self._reply_at(event, f"❌ 找不到该服务器"): yield chunk

    @filter.command("启用端口")
    async def enable(self, event: AstrMessageEvent):
        if not await self._is_admin(event): return
        msg = event.get_message_str().strip().split()
        if len(msg) < 2:
            for chunk in self._reply_at(event, "用法：/启用端口 所有/组别名 或 /启用端口 <组别名> <识别名>"): yield chunk
            return
        if len(msg) == 2:
            target = msg[1].strip()
            if target == "所有":
                for s in GLOBAL_DATA["servers"]:
                    self.toggle_state[_get_toggle_key(s["group"], s["default_name"])] = True
                save_toggle_state(self.toggle_state)
                await self._force_refresh_all()
                for chunk in self._reply_at(event, "🔓 已恢复全局所有服务器的数据轮询"): yield chunk
            elif any(s["group"] == target for s in GLOBAL_DATA["servers"]):
                for s in GLOBAL_DATA["servers"]:
                    if s["group"] == target:
                        self.toggle_state[_get_toggle_key(s["group"], s["default_name"])] = True
                save_toggle_state(self.toggle_state)
                await self._force_refresh_all()
                for chunk in self._reply_at(event, f"🔓 已恢复组【{target}】下的所有服务器数据轮询"): yield chunk
            else:
                for chunk in self._reply_at(event, f"❌ 未找到匹配的组别名【{target}】"): yield chunk
        elif len(msg) >= 3:
            g_name, d_name = msg[1].strip(), msg[2].strip()
            if any(s["group"] == g_name and s["default_name"] == d_name for s in GLOBAL_DATA["servers"]):
                self.toggle_state[_get_toggle_key(g_name, d_name)] = True
                save_toggle_state(self.toggle_state)
                await self._force_refresh_all()
                for chunk in self._reply_at(event, f"🔓 已恢复组【{g_name}】下的服务器【{d_name}】数据轮询"): yield chunk
            else:
                for chunk in self._reply_at(event, f"❌ 在组【{g_name}】下未找到识别名为【{d_name}】的服务器"): yield chunk

    @filter.command("禁用端口")
    async def disable(self, event: AstrMessageEvent):
        if not await self._is_admin(event): return
        msg = event.get_message_str().strip().split()
        if len(msg) < 2:
            for chunk in self._reply_at(event, "用法：/禁用端口 所有/组别名 或 /禁用端口 <组别名> <识别名>"): yield chunk
            return
        if len(msg) == 2:
            target = msg[1].strip()
            if target == "所有":
                for s in GLOBAL_DATA["servers"]:
                    self.toggle_state[_get_toggle_key(s["group"], s["default_name"])] = False
                save_toggle_state(self.toggle_state)
                await self._force_refresh_all()
                for chunk in self._reply_at(event, "🔒 全局阻断：所有服务器已停止数据轮询"): yield chunk
            elif any(s["group"] == target for s in GLOBAL_DATA["servers"]):
                for s in GLOBAL_DATA["servers"]:
                    if s["group"] == target:
                        self.toggle_state[_get_toggle_key(s["group"], s["default_name"])] = False
                save_toggle_state(self.toggle_state)
                await self._force_refresh_all()
                for chunk in self._reply_at(event, f"🔒 已批量隔离组【{target}】下的所有服务器数据轮询"): yield chunk
            else:
                for chunk in self._reply_at(event, f"❌ 未找到匹配的组别名【{target}】"): yield chunk
        elif len(msg) >= 3:
            g_name, d_name = msg[1].strip(), msg[2].strip()
            if any(s["group"] == g_name and s["default_name"] == d_name for s in GLOBAL_DATA["servers"]):
                self.toggle_state[_get_toggle_key(g_name, d_name)] = False
                save_toggle_state(self.toggle_state)
                await self._force_refresh_all()
                for chunk in self._reply_at(event, f"🔒 已隔离组【{g_name}】下的服务器【{d_name}】数据轮询"): yield chunk
            else:
                for chunk in self._reply_at(event, f"❌ 在组【{g_name}】下未找到识别名为【{d_name}】的服务器"): yield chunk

    async def __del__(self):
        if self.session and not self.session.closed:
            await self.session.close()