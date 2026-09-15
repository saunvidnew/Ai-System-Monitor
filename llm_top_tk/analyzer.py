import json, os, urllib.request
from .collectors import Snapshot

def summary(s):
    p=s.processes[0] if s.processes else None
    return f"CPU avg={s.cpu:.0f}%, max core={max(s.per_cpu) if s.per_cpu else 0:.0f}%; RAM={s.memory:.0f}%, swap={s.swap:.0f}%; disk={s.disk:.0f}%; net down={s.rx_rate:.0f}B/s up={s.tx_rate:.0f}B/s; top={p['name'] if p else 'none'} cpu={p['cpu'] if p else 0:.0f}%"
def local_analysis(s):
    p=s.processes[0]['name'] if s.processes else 'Workload'
    if s.memory>90:return f'{p} contributing to memory pressure; swap may increase.'
    if s.cpu>85:return f'{p} is driving sustained CPU pressure.'
    if s.per_cpu and max(s.per_cpu)>90 and s.cpu<60:return 'Single-core spike suggests a heavily single-threaded workload.'
    if s.disk>90:return 'Primary disk is nearly full; reclaim storage soon.'
    if s.swap>30:return 'Active swap suggests recent or ongoing memory pressure.'
    return 'System idle, all resources normal.'
class Analyzer:
    def __init__(self,provider='Local',model='llama3.2:3b'):self.provider,self.model=provider,model
    def analyze(self,s):
        if self.provider=='Local':return local_analysis(s)
        prompt="Give ONE system insight under 18 words. Explain root cause; don't repeat numbers. Metrics: "+summary(s)
        if self.provider=='Ollama':url='http://127.0.0.1:11434/api/chat'; payload={'model':self.model,'stream':False,'messages':[{'role':'user','content':prompt}]}; headers={}
        else:
            key=os.getenv('OPENAI_API_KEY')
            if not key:return 'OpenAI unavailable: set OPENAI_API_KEY. '+local_analysis(s)
            url='https://api.openai.com/v1/chat/completions'; payload={'model':self.model or 'gpt-4o-mini','max_tokens':40,'messages':[{'role':'user','content':prompt}]}; headers={'Authorization':f'Bearer {key}'}
        try:
            req=urllib.request.Request(url,json.dumps(payload).encode(),{'Content-Type':'application/json',**headers})
            with urllib.request.urlopen(req,timeout=12) as r:d=json.loads(r.read())
            return (d['message']['content'] if self.provider=='Ollama' else d['choices'][0]['message']['content']).replace('\n',' ').strip()
        except Exception as e:return f'AI unavailable ({type(e).__name__}); '+local_analysis(s)
    @staticmethod
    def ollama_models():
        try:
            with urllib.request.urlopen('http://127.0.0.1:11434/api/tags',timeout=2) as r:return [m['name'] for m in json.loads(r.read()).get('models',[])]
        except Exception:return []
