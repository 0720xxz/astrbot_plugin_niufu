import json
import asyncio
from pathlib import Path
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Star, Context, register
from astrbot.api import logger
import aiohttp
import astrbot.api.message_components as Comp
from astrbot.api.message_components import SenderRole

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
        {"id": "99987", "group": "牛服插件", "default_name": "内测", "display_name": "内测"},
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
        try:
            with open(TOGGLE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {s["default_name"]: True for s in GLOBAL_DATA["servers"]}

def save_toggle_state(state):
    with open(TOGGLE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def is_authorized(event: AstrMessageEvent) -> bool:
    return event.message_obj.sender.role in [SenderRole.ADMIN, SenderRole.OWNER]

@register("astrbot_plugin_niufu", "niufu", "query", "2.6.4")
class NiufuPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.toggle_state = load_toggle_state()
        self.cache = {}
        self.refresh_task = None
        self.current_interval = int(GLOBAL_DATA.get("refresh_interval_min", 30))
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
        self.current_interval = int(GLOBAL_DATA.get("refresh_interval_min", 30))
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
            imax = int(GLOBAL_DATA.get("refresh_interval_max", 120))
            istep = int(GLOBAL_DATA.get("refresh_decay_step", 15))
            self.current_interval = min(imax, self.current_interval + istep)

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

    def _parse_args(self, event: AstrMessageEvent, cmd_keyword: str, maxsplit: int = -1) -> list:
        msg = event.get_message_str().strip()
        parts = msg.split(maxsplit=maxsplit)
        if parts and cmd_keyword in parts[0]:
            return parts[1:]
        return parts

    @filter.command("牛服")
    async def niufu_cmd(self, event: AstrMessageEvent):
        try:
            self._trigger_active_refresh()
            data1 = await self._build_group_info("牛服插件")
            data2 = await self._build_group_info("牛服纯净")
            
            if data1 and data1[-1] == "==============":
                data1 = data1[:-1]
            if data2 and data2[-1] == "==============":
                data2 = data2[:-1]
            
            result = data1 + ["==============", "--- 纯净服分割线 ---", "=============="] + data2
            
            for chunk in self._reply_at(event, "\n".join(result)):
                yield chunk
        except Exception as e:
            for chunk in self._reply_at(event, f"请求异常: {e}"): yield chunk

    @filter.command("鸽服")
    async def pigeon_cmd(self, event: AstrMessageEvent):
        self._trigger_active_refresh()
        data = await self._build_group_info("鸽")
        for chunk in self._reply_at(event, "\n".join(data)): yield chunk
            
    @filter.command("ip")
    async def ip_cmd(self, event: AstrMessageEvent):
        try:
            self._trigger_active_refresh()
            data = await self._build_ip_info()
            for chunk in self._reply_at(event, "\n".join(data)):
                yield chunk
        except Exception as e:
            for chunk in self._reply_at(event, f"IP查询异常: {e}"): yield chunk

    @filter.command("查看所有服", alias=["列表服"])
    async def list_all_servers(self, event: AstrMessageEvent):
        if not is_authorized(event): 
            for chunk in self._reply_at(event, "❌ 权限不足！您不是管理员，无法使用该指令。"): yield chunk
            return
            
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

    @filter.command("调整刷新")
    async def change_refresh_rate(self, event: AstrMessageEvent):
        if not is_authorized(event):
            for chunk in self._reply_at(event, "❌ 权限不足！"): yield chunk
            return
            
        args = self._parse_args(event, "调整刷新")
        if len(args) < 1:
            for chunk in self._reply_at(event, "用法：/调整刷新 <最小秒数> [最大秒数]"): yield chunk
            return
        try:
            imin = int(args[0])
            imax = int(args[1]) if len(args) > 1 else imin
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
        if not is_authorized(event):
            for chunk in self._reply_at(event, "❌ 权限不足！"): yield chunk
            return
            
        args = self._parse_args(event, "添加服", maxsplit=3)
        if len(args) < 4:
            for chunk in self._reply_at(event, "用法：/添加服 <组别名> <识别名> <ID> <展示名>"): yield chunk
            return
        group_name, default_name, sid, display_name = args[0], args[1], args[2], args[3]
        
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
        if not is_authorized(event):
            for chunk in self._reply_at(event, "❌ 权限不足！"): yield chunk
            return
            
        args = self._parse_args(event, "删除服", maxsplit=1)
        if len(args) < 2:
            for chunk in self._reply_at(event, "用法：/删除服 <组别名> <识别名>"): yield chunk
            return
        group_name, target_name = args[0], args[1]
        
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
        if not is_authorized(event):
            for chunk in self._reply_at(event, "❌ 权限不足！"): yield chunk
            return
            
        args = self._parse_args(event, "设置组触发词", maxsplit=1)
        if len(args) < 2:
            for chunk in self._reply_at(event, "用法：/设置组触发词 <组别名> <触发词1,触发词2...>"): yield chunk
            return
        group_name, triggers_str = args[0], args[1]
        triggers_list = [t.strip() for t in triggers_str.replace("，", ",").split(",") if t.strip()]
        if not triggers_list:
            for chunk in self._reply_at(event, "错误：触发词列表不能为空"): yield chunk
            return
        GLOBAL_DATA["group_triggers"][group_name] = triggers_list
        save_server_data(GLOBAL_DATA)
        for chunk in self._reply_at(event, f"组【{group_name}】的触发关键词已设定为：{', '.join(triggers_list)}"): yield chunk

    @filter.command("设置组头部文字")
    async def set_group_headers(self, event: AstrMessageEvent):
        if not is_authorized(event):
            for chunk in self._reply_at(event, "❌ 权限不足！"): yield chunk
            return
            
        args = self._parse_args(event, "设置组头部文字", maxsplit=1)
        if len(args) < 2:
            for chunk in self._reply_at(event, "用法：/设置组头部文字 <组别名> <文字1|文字2|分隔符>"): yield chunk
            return
        group_name, headers_str = args[0], args[1]
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
        if not is_authorized(event):
            for chunk in self._reply_at(event, "❌ 权限不足！"): yield chunk
            return
            
        args = self._parse_args(event, "改服ID", maxsplit=2)
        if len(args) < 3:
            for chunk in self._reply_at(event, "用法：/改服ID <组别名> <识别名> <新ID>"): yield chunk
            return
        group_name, target_name, new_id = args[0], args[1], args[2]
        
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
        if not is_authorized(event):
            for chunk in self._reply_at(event, "❌ 权限不足！"): yield chunk
            return
            
        args = self._parse_args(event, "改服名", maxsplit=2)
        if len(args) < 3:
            for chunk in self._reply_at(event, "用法：/改服名 <组别名> <识别名> <新展示名>"): yield chunk
            return
        group_name, target_name, new_display = args[0], args[1], args[2]
        
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
        if not is_authorized(event):
            for chunk in self._reply_at(event, "❌ 权限不足！"): yield chunk
            return
            
        args = self._parse_args(event, "改服组", maxsplit=2)
        if len(args) < 3:
            for chunk in self._reply_at(event, "用法：/改服组 <原组别名> <识别名> <新组别名>"): yield chunk
            return
        old_group, target_name, new_group = args[0], args[1], args[2]
        
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
        if not is_authorized(event):
            for chunk in self._reply_at(event, "❌ 权限不足！"): yield chunk
            return
            
        args = self._parse_args(event, "启用端口", maxsplit=0)
        if len(args) < 1:
            for chunk in self._reply_at(event, "用法：/启用端口 <识别名> 或 所有 / 所有[组别名]"): yield chunk
            return
            
        target = args[0].strip()
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
        if not is_authorized(event):
            for chunk in self._reply_at(event, "❌ 权限不足！"): yield chunk
            return
            
        args = self._parse_args(event, "禁用端口", maxsplit=0)
        if len(args) < 1:
            for chunk in self._reply_at(event, "用法：/禁用端口 <识别名> 或 所有 / 所有[组别名]"): yield chunk
            return
            
        target = args[0].strip()
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
        for chunk in self._reply_at(event, "💡 该插件已全面接入 AstrBot 官方内置权限管理。请直接在机器人网页后台面板添加/移除‘管理员’或‘主人’账号，插件将实时同步官方权限。"): yield chunk

    async def __del__(self):
        if self.session and not self.session.closed:
            await self.session.close()
