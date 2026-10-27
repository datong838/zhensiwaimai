#!/usr/bin/env python3
"""Identity-bound AX navigation in an existing signed-in service-provider tab."""
import json
import subprocess
import time
from dataclasses import dataclass
from urllib.parse import urlsplit
import AppKit
import ApplicationServices as AX

PREFIX = 'https://open.shop.ele.me/'
BUNDLE = 'com.google.Chrome'

class UIError(RuntimeError):
    pass

@dataclass(frozen=True)
class Tab:
    window: int
    tab: int
    index: int
    url: str
    active: int

def unique_service_tab(tabs):
    found = [t for t in tabs if t.url.startswith(PREFIX)]
    if len(found) != 1:
        raise UIError(f'service-tab-count:{len(found)}')
    return found[0]

def verify_identity(expected, current):
    if (expected.window, expected.tab) != (current.window, current.tab) or current.active != expected.tab:
        raise UIError('service-active-tab-changed')
    if not current.url.startswith(PREFIX):
        raise UIError('service-origin-changed')

def attr(element, key):
    code, value = AX.AXUIElementCopyAttributeValue(element, key, None)
    return value if code == 0 else None

def script(source):
    p = subprocess.run(['/usr/bin/osascript', '-e', source], capture_output=True, text=True, timeout=5)
    if p.returncode:
        raise UIError('chrome-ui-script-failed:'+p.stderr.strip()[-300:])
    return p.stdout.strip()

def open_service_home_tab():
    script('''tell application "Google Chrome"
if (count of windows) is 0 then error "chrome-window-missing"
tell front window to make new tab with properties {URL:"https://open.shop.ele.me/manager/base/home"}
end tell''')

def reload_service_home_tab():
    script('''tell application "Google Chrome"
repeat with w in windows
set n to 0
repeat with t in tabs of w
set n to n + 1
if (URL of t as text) starts with "https://open.shop.ele.me/" then
set active tab index of w to n
set URL of t to "https://open.shop.ele.me/manager/base/home"
return "reloaded"
end if
end repeat
end repeat
error "service-tab-missing"
end tell''')

def tabs():
    result = script('''tell application "Google Chrome"
set rows to ""
repeat with w in windows
set n to 0
set activeId to id of active tab of w
repeat with t in tabs of w
set n to n + 1
set u to URL of t as text
if u starts with "https://open.shop.ele.me/" then
set rows to rows & (id of w as text) & (ASCII character 9) & (id of t as text) & (ASCII character 9) & (n as text) & (ASCII character 9) & u & (ASCII character 9) & (activeId as text) & linefeed
end if
end repeat
end repeat
return rows
end tell''')
    items=[]
    for row in result.splitlines():
        w,t,i,u,a = row.split('\t')
        items.append(Tab(int(w),int(t),int(i),u,int(a)))
    return items

def safe_url(url):
    p=urlsplit(url)
    return p.scheme+'://'+p.netloc+p.path

class ServiceUI:
    def __init__(self, budget=45):
        self.started=time.monotonic();self.deadline=self.started+budget
        if not AX.AXIsProcessTrusted():raise UIError('chrome-ax-not-ready')
        stable_pid=None;self.root=None;opened=False;empty_samples=0;end=min(self.deadline,time.monotonic()+6)
        while time.monotonic()<end:
            matches=[]
            for app in AppKit.NSRunningApplication.runningApplicationsWithBundleIdentifier_(BUNDLE):
                root=AX.AXUIElementCreateApplication(app.processIdentifier())
                AX.AXUIElementSetMessagingTimeout(root,.8)
                windows=attr(root,'AXWindows') or []
                if any(attr(w,'AXSubrole')=='AXStandardWindow' and '淘宝闪购服务商' in str(attr(w,'AXTitle') or '') for w in windows):
                    matches.append((app.processIdentifier(),root))
            if len(matches)==1 and stable_pid==matches[0][0]:
                self.root=matches[0][1];break
            if not matches:
                empty_samples+=1
                if empty_samples>=2 and not opened:
                    open_service_home_tab();opened=True
            stable_pid=matches[0][0] if len(matches)==1 else None
            time.sleep(.15)
        if self.root is None:raise UIError('service-chrome-process-not-stable')
        AX.AXUIElementSetMessagingTimeout(self.root, .8)
        self.target=None;self.nodes=[];self.events=[];self.stage_ms={}
        self.frontmost_before=self.frontmost()
    def frontmost(self):
        return str(AppKit.NSWorkspace.sharedWorkspace().frontmostApplication().bundleIdentifier())
    def check_time(self):
        if time.monotonic()>=self.deadline:raise UIError('navigation-deadline-exceeded')
    def attach(self):
        self.check_time();self.target=self.service_url();self.guard()
    def service_url(self):
        def urls_in(window):
            urls=[];seen=set()
            def walk(e):
                self.check_time()
                if e in seen:return
                seen.add(e)
                if len(seen)>4000:raise UIError('ax-tree-limit')
                if attr(e,'AXRole')=='AXWebArea':
                    url=str(attr(e,'AXURL') or '')
                    if url.startswith(PREFIX):urls.append(url)
                    return
                for child in attr(e,'AXChildren') or []:walk(child)
            walk(window);return urls
        windows=[w for w in attr(self.root,'AXWindows') or [] if attr(w,'AXSubrole')=='AXStandardWindow']
        candidates=[]
        for window in windows:
            urls=urls_in(window)
            if len(urls)==1:candidates.append((window,urls[0]))
        if not candidates:raise UIError('service-tab-count:0')
        self.service_window=candidates[0][0]
        return candidates[0][1]
    def guard(self):
        self.check_time()
        current=self.service_url()
        if not current.startswith(PREFIX):raise UIError('service-origin-changed')
        return Tab(0,0,0,current,0)
    def snapshot(self):
        current=self.guard()
        windows=[self.service_window]
        seen=set();areas=[]
        def areas_walk(e):
            self.check_time()
            if e in seen:return
            seen.add(e)
            if len(seen)>4000:raise UIError('ax-tree-limit')
            if attr(e,'AXRole')=='AXWebArea' and str(attr(e,'AXURL') or '').startswith(PREFIX):areas.append(e);return
            for child in attr(e,'AXChildren') or []:areas_walk(child)
        areas_walk(windows[0])
        if len(areas)!=1:raise UIError('service-webarea-not-unique')
        self.nodes=[];seen=set()
        def walk(e, parent=None):
            self.check_time()
            if e in seen:return
            seen.add(e)
            if len(seen)>4000:raise UIError('ax-tree-limit')
            role=str(attr(e,'AXRole') or '')
            title=attr(e,'AXTitle');desc=attr(e,'AXDescription');value=attr(e,'AXValue')
            label=str(title or desc or (value if isinstance(value,str) else '') or '')
            _,actions=AX.AXUIElementCopyActionNames(e,None)
            i=len(self.nodes);self.nodes.append({'element':e,'role':role,'label':label,'actions':list(actions or []),'parent':parent})
            for c in attr(e,'AXChildren') or []:walk(c,i)
        walk(areas[0]);self.guard()
        return {'url':safe_url(current.url),'labels':[n['label'] for n in self.nodes],
                'tableCount':sum(n['role']=='AXTable' for n in self.nodes)}
    def visible_actions(self):
        return [{'role':n['role'],'label':n['label']} for n in self.nodes if 'AXPress' in n['actions'] and n['label']]
    def descendants(self, index):
        result=[]
        for i,n in enumerate(self.nodes):
            p=n['parent']
            while p is not None:
                if p==index:result.append(i);break
                p=self.nodes[p]['parent']
        return result
    def press_index(self, index):
        self.guard();node=self.nodes[index]
        if 'AXPress' not in node['actions']:raise UIError('node-not-pressable')
        code=AX.AXUIElementPerformAction(node['element'],'AXPress')
        if code:raise UIError(f'ax-press-failed:{code}')
        self.guard()
    def field(self, placeholder):
        found=[n for n in self.nodes if n['role']=='AXTextField' and attr(n['element'],'AXPlaceholderValue')==placeholder]
        if len(found)!=1:raise UIError('field-not-unique:'+placeholder)
        return found[0]
    def set_field(self, placeholder, value):
        self.snapshot();node=self.field(placeholder);self.guard()
        code=AX.AXUIElementSetAttributeValue(node['element'],'AXValue',value)
        if code:raise UIError(f'field-set-failed:{placeholder}:{code}')
        self.snapshot()
        if attr(self.field(placeholder)['element'],'AXValue')!=value:raise UIError('field-value-mismatch:'+placeholder)
    def set_today_range(self, today):
        self.snapshot()
        if all(attr(self.field(p)['element'],'AXValue')==today for p in ['开始日期','结束日期']):return
        node=self.field('开始日期');self.press_index(self.nodes.index(node))
        for _ in range(2):
            self.snapshot()
            found=[i for i,n in enumerate(self.nodes) if n['role']=='AXCell'
                   and attr(n['element'],'AXHelp')==today
                   and 'ant-picker-cell-in-view' in list(attr(n['element'],'AXDOMClassList') or [])]
            if len(found)!=1:raise UIError('calendar-day-not-unique')
            self.press_index(found[0])
        self.snapshot()
        if not all(attr(self.field(p)['element'],'AXValue')==today for p in ['开始日期','结束日期']):
            raise UIError('date-range-readback-failed')
    def press(self,label):
        self.snapshot();matches=[]
        for node in self.nodes:
            if node['label']!=label:continue
            while 'AXPress' not in node['actions'] and node['parent'] is not None:node=self.nodes[node['parent']]
            if 'AXPress' in node['actions'] and not any(node['element']==m['element'] for m in matches):matches.append(node)
        if len(matches)!=1:raise UIError(f'unique-press-target-missing:{label}:{len(matches)}')
        self.guard();node=matches[0]
        self.events.append({'event':'press','label':label,'role':node['role']})
        code=AX.AXUIElementPerformAction(node['element'],'AXPress')
        if code:raise UIError(f'ax-press-failed:{label}:{code}')
        self.guard()
    def wait(self,predicate,timeout=6):
        end=min(self.deadline,time.monotonic()+timeout)
        while time.monotonic()<end:
            try:state=self.snapshot()
            except UIError as error:
                if str(error) not in ('service-tab-count:0','service-ax-window-missing'):raise
                time.sleep(.15);continue
            if predicate(state):return state
            time.sleep(.15)
        raise UIError('page-postcondition-timeout')
    def stage(self,label,operation):
        start=time.monotonic()
        try:return operation()
        finally:self.stage_ms[label]=round((time.monotonic()-start)*1000)

def intention_page(state):
    return state['url']==PREFIX+'manager/agent/home' and '意向商户管理' in state['labels'] and '商家意向列表' in state['labels'] and state.get('tableCount',0)>0

def run_route(ui):
    ui.stage('attach_existing_tab',ui.attach)
    state=ui.stage('read_page_structure',ui.snapshot)
    route_labels=('appstore 控制台','代运营','客户管理','意向商户管理')
    public_entry=state['url'] in (PREFIX+'home',PREFIX.rstrip('/'))
    if not public_entry and not intention_page(state) and not any(label in state['labels'] for label in route_labels):
        def reload_shell():
            reload_service_home_tab()
            return ui.wait(lambda s:intention_page(s) or any(label in s['labels'] for label in route_labels))
        state=ui.stage('reload_service_shell',reload_shell)
    already=intention_page(state)
    if already:return state,True
    if state['url'] in (PREFIX+'home',PREFIX.rstrip('/')):
        def console():
            ui.press('appstore 控制台')
            return ui.wait(lambda s:s['url'].startswith(PREFIX+'manager/'))
        state=ui.stage('enter_console',console)
    if not state['url'].startswith(PREFIX+'manager/'):
        raise UIError('unsupported-service-page')
    if '客户管理' not in state['labels'] and '意向商户管理' not in state['labels']:
        def agent():
            ui.press('代运营')
            return ui.wait(lambda s:'客户管理' in s['labels'])
        state=ui.stage('open_agent_menu',agent)
    if '意向商户管理' not in state['labels']:
        def customer():
            ui.press('客户管理')
            return ui.wait(lambda s:'意向商户管理' in s['labels'])
        state=ui.stage('open_customer_menu',customer)
    def intention():
        ui.press('意向商户管理')
        return ui.wait(intention_page)
    state=ui.stage('open_intention_list',intention)
    return state,already

def navigate():
    ui=ServiceUI();result={'ok':False,'mode':'structured-ui-navigation','events':ui.events,'stageMs':ui.stage_ms,'runtimeModelDecisions':0}
    try:
        state,already=run_route(ui)
        result.update(ok=True,intentionListVisible=True,alreadyOpen=already,url=state['url'],tableCount=state['tableCount'])
    except Exception as error:result['error']=str(error)
    result.update(elapsedMs=round((time.monotonic()-ui.started)*1000),frontmostBefore=ui.frontmost_before,frontmostAfter=ui.frontmost())
    return result

if __name__=='__main__':
    print(json.dumps(navigate(),ensure_ascii=False))
