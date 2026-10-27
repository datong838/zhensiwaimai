#!/usr/bin/env python3
"""Session-local macOS AX/Quartz adapter. Only the authorized existing merchant tab."""
import json, os, re, sys, time, subprocess, tempfile
from pathlib import Path
import AppKit
import ApplicationServices as AX
import Quartz as Q

BUNDLE='com.google.Chrome'
PREFIX='https://melody.shop.ele.me/app/chain/95708808/'

def attr(e,k):
    err,value=AX.AXUIElementCopyAttributeValue(e,k,None)
    return value if err==0 else None

def actions(e):
    err,value=AX.AXUIElementCopyActionNames(e,None)
    return list(value or []) if err==0 else []

class Bridge:
    def __init__(self):
        apps=AppKit.NSRunningApplication.runningApplicationsWithBundleIdentifier_(BUNDLE)
        if len(apps)!=1 or not AX.AXIsProcessTrusted():raise RuntimeError('native-control-unavailable')
        self.app=apps[0];self.ax=AX.AXUIElementCreateApplication(self.app.processIdentifier())
        AX.AXUIElementSetMessagingTimeout(self.ax,1.0)
        self.refs={};self.src=Q.CGEventSourceCreate(Q.kCGEventSourceStateHIDSystemState)
    def window(self):
        matches=[w for w in attr(self.ax,'AXWindows') or [] if attr(w,'AXSubrole')=='AXStandardWindow' and str(attr(w,'AXTitle') or '').startswith('淘宝闪购商家版')]
        if len(matches)!=1:raise RuntimeError('merchant-standard-window-not-unique')
        return matches[0]
    def foreground(self):
        if AppKit.NSWorkspace.sharedWorkspace().frontmostApplication().bundleIdentifier()!=BUNDLE:raise RuntimeError('chrome-not-frontmost')
        self.window();return True
    def activate(self):
        # Prefer the single matching tab already active in its window. Never close,
        # create, or navigate tabs; ambiguous active candidates remain fail-closed.
        script='''tell application "Google Chrome"
set found to {}
set activeFound to {}
set frontActiveFound to {}
repeat with w in windows
set n to 0
repeat with t in tabs of w
set n to n + 1
if URL of t starts with "'''+PREFIX+'''" then
set end of found to {id of w, n}
if n is active tab index of w then
set end of activeFound to {id of w, n}
if index of w is 1 then set end of frontActiveFound to {id of w, n}
end if
end if
end repeat
end repeat
if count of found is 1 then
set pair to item 1 of found
else if count of activeFound is 1 then
set pair to item 1 of activeFound
else if count of frontActiveFound is 1 then
set pair to item 1 of frontActiveFound
else
error "merchant-active-tab-not-unique"
end if
set w to window id (item 1 of pair)
set active tab index of w to item 2 of pair
set index of w to 1
activate
end tell'''
        subprocess.run(['/usr/bin/osascript','-e',script],check=True,capture_output=True,timeout=5)
        end=time.monotonic()+2
        while True:
            try:return self.foreground()
            except RuntimeError:
                if time.monotonic()>end:raise
                time.sleep(.04)
    def fullscreen(self):
        self.foreground();w=self.window()
        if not attr(w,'AXFullScreen'):
            if AX.AXUIElementSetAttributeValue(w,'AXFullScreen',True)!=0:raise RuntimeError('fullscreen-set-failed')
        end=time.monotonic()+3;previous=None
        while True:
            try:
                window=self.window();geometry=self.rectangle(window)
                if attr(window,'AXFullScreen') and geometry==previous:return True
                previous=geometry
            except RuntimeError:
                previous=None
            if time.monotonic()>end:raise RuntimeError('fullscreen-not-stable')
            time.sleep(.06)
    def state(self):
        w=self.window();self.refs={};lines=[];seen=set();urls=[];end=time.monotonic()+8
        def walk(e,depth=0):
            if time.monotonic()>end:raise RuntimeError('ax-read-deadline')
            if depth>45 or len(self.refs)>4000:raise RuntimeError('ax-tree-limit')
            if e in seen:return
            seen.add(e);role=attr(e,'AXRole')
            if role=='AXColumn':return # same cells already represented in AXRows
            i=len(self.refs);self.refs[i]=e
            desc=str(attr(e,'AXRoleDescription') or role or '')
            if role=='AXRow':desc='row'
            elif role=='AXGroup':desc='container'
            elif role=='AXStaticText':desc='文本'
            elif role=='AXWebArea':desc='HTML 内容'
            title=attr(e,'AXTitle');value=attr(e,'AXValue');description=attr(e,'AXDescription')
            label=title or description or (value if isinstance(value,str) else '') or ''
            label=str(label).replace('\n',' ')
            if label.startswith('data:') or len(label)>240:label=''
            disabled=' (disabled)' if attr(e,'AXEnabled') is False else ''
            text=f'{i} {desc}{disabled}'+(' '+label if label else '')
            if role=='AXRadioButton':text+=', Value: '+str(int(value or 0))
            url=attr(e,'AXURL')
            if role=='AXWebArea' and url:
                url=str(url);text+=', URL: '+url
                if url.startswith(PREFIX):urls.append(url)
            lines.append('\t'*depth+text)
            for child in attr(e,'AXChildren') or []:walk(child,depth+1)
        walk(w)
        if len(urls)!=1:raise RuntimeError('merchant-page-url-not-unique')
        return 'Window: "淘宝闪购商家版", App: Google Chrome, URL: '+urls[0]+'\n'+'\n'.join(lines)
    def center(self,e):
        p=attr(e,'AXPosition');s=attr(e,'AXSize')
        if p is None or s is None:raise RuntimeError('element-geometry-missing')
        ok,p=AX.AXValueGetValue(p,AX.kAXValueCGPointType,None);ok2,s=AX.AXValueGetValue(s,AX.kAXValueCGSizeType,None)
        if not ok or not ok2 or s.width<=0 or s.height<=0:raise RuntimeError('invalid-element-geometry')
        x,y=p.x+s.width/2,p.y+s.height/2
        bounds=Q.CGDisplayBounds(Q.CGMainDisplayID())
        if not(0<x<bounds.size.width and 0<y<bounds.size.height):raise RuntimeError('element-outside-display')
        return (x,y)
    def click(self,i):
        self.foreground();e=self.refs[int(i)]
        role=attr(e,'AXRole')
        if role not in ('AXMenuItem','AXLink') and 'AXPress' in actions(e):
            if AX.AXUIElementPerformAction(e,'AXPress')!=0:raise RuntimeError('ax-press-failed')
        else:
            point=self.center(e)
            for kind in [Q.kCGEventMouseMoved,Q.kCGEventLeftMouseDown,Q.kCGEventLeftMouseUp]:
                Q.CGEventPost(Q.kCGHIDEventTap,Q.CGEventCreateMouseEvent(self.src,kind,point,0))
        return True
    def hover(self,i):
        self.foreground();point=self.center(self.refs[int(i)])
        Q.CGEventPost(Q.kCGHIDEventTap,Q.CGEventCreateMouseEvent(self.src,Q.kCGEventMouseMoved,point,0))
        return True
    def visual_click_text(self,text):
        fd,path=tempfile.mkstemp(prefix='zhensi-menu-',suffix='.png');os.close(fd)
        try:
            info=self.screenshot(path)
            output=subprocess.run([str(Path(__file__).with_name('ocr_vision')),path,'zh-Hans'],check=True,capture_output=True,text=True,timeout=5).stdout
            matches=[]
            for record in output.splitlines():
                parts=record.split('\t',2)
                if len(parts)!=3:continue
                try:
                    x,y,w,h=(int(v) for v in parts[0].split(','));confidence=float(parts[1])
                except ValueError:continue
                if re.sub(r'\s+','',parts[2])==re.sub(r'\s+','',text) and confidence>=.8 and x<info['width']*.35:
                    matches.append((x,y))
            if len(matches)!=1:raise RuntimeError('visual-text-not-unique')
            x,y=matches[0];point=(info['x']+x/info['scale'],info['y']+y/info['scale'])
            for kind in [Q.kCGEventMouseMoved,Q.kCGEventLeftMouseDown,Q.kCGEventLeftMouseUp]:
                Q.CGEventPost(Q.kCGHIDEventTap,Q.CGEventCreateMouseEvent(self.src,kind,point,0))
            return True
        finally:
            try:os.unlink(path)
            except FileNotFoundError:pass
    def key(self,key):
        self.foreground()
        codes={'0':29,'minus':27,'End':119,'Up':126,'Escape':53}
        parts=key.split('+');code=codes[parts[-1]]
        flags=Q.kCGEventFlagMaskCommand if 'super' in parts else 0
        for down in [True,False]:
            e=Q.CGEventCreateKeyboardEvent(self.src,code,down);Q.CGEventSetFlags(e,flags);Q.CGEventPost(Q.kCGHIDEventTap,e)
        return True
    def scroll(self,i,direction,pages):
        self.foreground();point=self.center(self.refs[int(i)])
        Q.CGEventPost(Q.kCGHIDEventTap,Q.CGEventCreateMouseEvent(self.src,Q.kCGEventMouseMoved,point,0))
        delta=int(pages*650)*(1 if direction=='up' else -1)
        e=Q.CGEventCreateScrollWheelEvent(self.src,Q.kCGScrollEventUnitPixel,1,delta)
        Q.CGEventPost(Q.kCGHIDEventTap,e);return True
    def rectangle(self,e):
        ok,p=AX.AXValueGetValue(attr(e,'AXPosition'),AX.kAXValueCGPointType,None)
        ok2,z=AX.AXValueGetValue(attr(e,'AXSize'),AX.kAXValueCGSizeType,None)
        if not(ok and ok2):raise RuntimeError('geometry-unreadable')
        return {'x':p.x,'y':p.y,'width':z.width,'height':z.height}
    def screenshot(self,path):
        from PIL import Image
        self.foreground();self.state()
        target=self.rectangle(self.window())
        candidates=[w for w in Q.CGWindowListCopyWindowInfo(Q.kCGWindowListOptionOnScreenOnly,Q.kCGNullWindowID) if w.get('kCGWindowOwnerPID')==self.app.processIdentifier() and w.get('kCGWindowLayer')==0 and all(abs(float(w['kCGWindowBounds'][key])-target[field])<.5 for key,field in [('X','x'),('Y','y'),('Width','width'),('Height','height')])]
        if len(candidates)!=1:raise RuntimeError('capture-window-not-unique')
        window=candidates[0];bounds=window['kCGWindowBounds']
        # Fullscreen Chrome has separate tab/toolbar windows; screencapture composes them.
        parts=[w['kCGWindowBounds'] for w in Q.CGWindowListCopyWindowInfo(Q.kCGWindowListOptionOnScreenOnly,Q.kCGNullWindowID) if w.get('kCGWindowOwnerPID')==self.app.processIdentifier() and w.get('kCGWindowLayer')==0 and w['kCGWindowBounds']['X']==bounds['X'] and w['kCGWindowBounds']['Width']==bounds['Width'] and w['kCGWindowBounds']['Y']<=bounds['Y'] and w['kCGWindowBounds']['Y']+w['kCGWindowBounds']['Height']<=bounds['Y']+bounds['Height']]
        top=min(b['Y'] for b in parts);bounds={'X':bounds['X'],'Y':top,'Width':bounds['Width'],'Height':bounds['Y']+bounds['Height']-top}
        subprocess.run(['/usr/sbin/screencapture','-x','-o','-l',str(window['kCGWindowNumber']),path],check=True,timeout=5)
        self.foreground();im=Image.open(path)
        self.capture_info={'x':float(bounds['X']),'y':float(bounds['Y']),'scale':im.width/float(bounds['Width']),'width':im.width,'height':im.height}
        if abs(im.height/float(bounds['Height'])-self.capture_info['scale'])>.01:raise RuntimeError('capture-scale-mismatch')
        return self.capture_info
    def crop_geometry(self):
        import math
        self.foreground();self.state()
        tables=[e for e in self.refs.values() if attr(e,'AXRole')=='AXTable']
        pagers=[e for e in self.refs.values() if attr(e,'AXRole')=='AXList' and self.rectangle(e)['height']<50]
        if len(tables)!=1 or len(pagers)!=1:raise RuntimeError('native-crop-anchors-not-unique')
        t=self.rectangle(tables[0]);p=self.rectangle(pagers[0]);c=self.capture_info;k=c['scale']
        x=math.floor((t['x']-c['x'])*k)-4;y=math.floor((t['y']-c['y'])*k)-4
        width=max(1500,math.ceil(t['width']*k)+8)
        bottom=min(c['height'],math.ceil((p['y']+p['height']-c['y'])*k)+2)
        if x<0 or y<0 or x+width>c['width'] or bottom<=y:raise RuntimeError('native-crop-outside-source')
        return {'x':x,'y':y,'width':width,'height':bottom-y}
    def command(self,q):
        op=q['op']
        if op in ['activate','foreground','fullscreen','state']:return getattr(self,op)()
        if op=='click':return self.click(q['index'])
        if op=='hover':return self.hover(q['index'])
        if op=='visual_click_text':return self.visual_click_text(q['text'])
        if op=='key':return self.key(q['key'])
        if op=='scroll':return self.scroll(q['index'],q['direction'],q['pages'])
        if op=='screenshot':return self.screenshot(q['path'])
        if op=='crop_geometry':return self.crop_geometry()
        raise RuntimeError('unsupported-native-operation')

if __name__=='__main__':
    bridge=Bridge()
    for line in sys.stdin:
        try:
            q=json.loads(line);result={'ok':True,'value':bridge.command(q)}
        except Exception as e:result={'ok':False,'error':str(e)}
        print(json.dumps(result,ensure_ascii=False),flush=True)
