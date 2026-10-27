import ast, unittest
from pathlib import Path
from types import SimpleNamespace
p=Path('/Users/ddt/work/projects/ai_agent/zhensi_waimai_back/skills/wechat-messaging/scripts/wecom_desktop_sender.py')
tree=ast.parse(p.read_text())
class Tests(unittest.TestCase):
 def run_text(self,text):
  keys=[];units=[]
  quartz=SimpleNamespace(kCGEventFlagMaskShift=2,CGEventCreateKeyboardEvent=lambda *a:object(),CGEventSetFlags=lambda *a:None,CGEventKeyboardSetUnicodeString=lambda event,n,ch:units.append((n,ch)),CGEventPost=lambda *a:None,kCGHIDEventTap=0)
  env={'Quartz':quartz,'VK_RETURN':36,'press_key':lambda *a:keys.append(a),'time':SimpleNamespace(sleep=lambda *a:None)}
  node=next(x for x in tree.body if isinstance(x,ast.FunctionDef) and x.name=='type_text')
  exec(compile(ast.Module(body=[node],type_ignores=[]),str(p),'exec'),env)
  env['type_text'](text,0)
  return keys,units
 def test_multiline_never_submits(self):
  keys,units=self.run_text('淘宝\n店铺💰\n完成')
  self.assertEqual(keys,[(36,2),(36,2)]);self.assertIn((2,'💰'),units)
 def test_crlf_and_cr(self):
  keys,units=self.run_text('a\r\nb\rc');self.assertEqual(keys,[(36,2),(36,2)]);self.assertFalse(any(c=='\r' for _,c in units))
 def test_single_line_unchanged(self):
  keys,units=self.run_text('淘宝');self.assertEqual(keys,[]);self.assertEqual(units,[(1,'淘'),(1,'宝')])
 def test_multiline_retry_bound(self):
  node=next(x for x in tree.body if isinstance(x,ast.FunctionDef) and x.name=='write_input')
  assign=next(x for x in node.body if isinstance(x,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='write_attempts' for t in x.targets))
  for text,expected in [('a\nb',(1,)),('a\rb',(1,)),('ab',(1,2))]:
   self.assertEqual(eval(compile(ast.Expression(assign.value),'test','eval'),{'text':text}),expected)
if __name__=='__main__':unittest.main()
