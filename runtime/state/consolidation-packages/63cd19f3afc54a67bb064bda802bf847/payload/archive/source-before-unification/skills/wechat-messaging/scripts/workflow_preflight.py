"""Compatibility preflight API for registered desktop business workflows."""
import sys
import time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from executor import verify_dependencies, deadline
from contract import Rejected

def run_exact_group_preflight(group, output_dir=None, **kwargs):
    from workflow_bridge import REGISTRY
    if group not in {p[0] for p in REGISTRY.values()}:
        return {'ok':False,'reason':'workflow-group-not-registered','hardGate':True,'sendAttempts':0}
    verify_dependencies()
    from desktop_adapter import DesktopAdapter
    adapter=DesktopAdapter()
    context={'deadlineAt':time.time()+60}
    resume_text=kwargs.get('resume_prepared_text')
    if resume_text is not None:
        import hashlib
        if group != '电销+直播攻坚组' or not isinstance(resume_text,str) or not resume_text:
            return {'ok':False,'reason':'resume-prepared-text-scope-mismatch','sendAttempts':0,'hardGate':True}
        context.update(resumePreparedText=resume_text,
                       resumePreparedTextSha256=hashlib.sha256(resume_text.encode('utf-8')).hexdigest())
    request={'groupName':group,'context':context}
    output=Path(output_dir) if output_dir else Path(__file__).resolve().parents[1]/'.runtime/preflight'/str(time.time_ns())
    with deadline(request['context']['deadlineAt']),adapter.session(request):
        return adapter.preflight(request,output) | {'sendAttempts':0}
