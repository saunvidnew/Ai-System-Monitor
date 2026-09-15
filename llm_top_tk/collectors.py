from __future__ import annotations
import platform, subprocess, time
from dataclasses import dataclass, field
from typing import Any
import psutil

def human_bytes(n):
    n=float(n)
    for u in ('B','KiB','MiB','GiB','TiB'):
        if abs(n)<1024 or u=='TiB': return f'{n:.1f} {u}'
        n/=1024

@dataclass
class Snapshot:
    timestamp: float; cpu: float=0; per_cpu:list[float]=field(default_factory=list); cpu_freq:float|None=None
    memory:float=0; memory_used:int=0; memory_total:int=0; memory_available:int=0; swap:float=0; disk:float=0
    disks:list[dict[str,Any]]=field(default_factory=list); rx_rate:float=0; tx_rate:float=0
    processes:list[dict[str,Any]]=field(default_factory=list); gpus:list[dict[str,Any]]=field(default_factory=list)
    alerts:list[dict[str,str]]=field(default_factory=list); error:str=''

class SystemCollector:
    def __init__(self):
        self.net=psutil.net_io_counters(); self.when=time.monotonic(); psutil.cpu_percent(None,percpu=True)
    def collect(self):
        s=Snapshot(time.time()); s.per_cpu=psutil.cpu_percent(.15,percpu=True); s.cpu=sum(s.per_cpu)/len(s.per_cpu) if s.per_cpu else 0
        f=psutil.cpu_freq(); s.cpu_freq=f.current if f else None
        m=psutil.virtual_memory(); s.memory=m.percent; s.memory_used=m.used; s.memory_total=m.total; s.memory_available=m.available
        try: s.swap=psutil.swap_memory().percent
        except OSError: s.swap=0
        for p in psutil.disk_partitions(False):
            try: u=psutil.disk_usage(p.mountpoint)
            except (OSError,PermissionError): continue
            if u.total: s.disks.append({'device':p.device,'mount':p.mountpoint,'used':u.used,'free':u.free,'total':u.total,'percent':u.percent})
        root=next((d for d in s.disks if d['mount']=='/'),s.disks[0] if s.disks else None); s.disk=root['percent'] if root else 0
        now=time.monotonic(); net=psutil.net_io_counters(); dt=max(now-self.when,.001); s.rx_rate=max(0,net.bytes_recv-self.net.bytes_recv)/dt; s.tx_rate=max(0,net.bytes_sent-self.net.bytes_sent)/dt; self.net,self.when=net,now
        try:
            for p in psutil.process_iter(('pid','name','username','cpu_percent','memory_percent','status')):
                try:
                    i=p.info; s.processes.append({'pid':i['pid'],'name':i['name'] or '?','user':i['username'] or '?','cpu':i['cpu_percent'] or 0,'memory':i['memory_percent'] or 0,'status':i['status'] or '?'})
                except (psutil.NoSuchProcess,psutil.AccessDenied,psutil.ZombieProcess): pass
        except (PermissionError, OSError):
            pass
        s.processes=sorted(s.processes,key=lambda x:(x['cpu'],x['memory']),reverse=True)[:15]; s.gpus=self._gpus(); s.alerts=AlertManager.check(s); return s
    @staticmethod
    def _gpus():
        if platform.system()=='Darwin' and platform.machine()=='arm64':
            name='Apple Silicon GPU'
            try:
                out=subprocess.run(['system_profiler','SPDisplaysDataType'],capture_output=True,text=True,timeout=4).stdout
                name=next((x.split(':',1)[1].strip() for x in out.splitlines() if 'Chipset Model:' in x),name)
            except Exception: pass
            return [{'id':0,'name':name,'load':None,'memory':'Unified','temperature':None,'type':'Apple'}]
        try:
            out=subprocess.run(['nvidia-smi','--query-gpu=index,name,utilization.gpu,memory.used,memory.total,temperature.gpu','--format=csv,noheader,nounits'],capture_output=True,text=True,timeout=3,check=True).stdout
            rows=[]
            for line in out.splitlines():
                i,n,l,u,t,temp=[x.strip() for x in line.split(',')]; rows.append({'id':i,'name':n,'load':float(l),'memory':f'{u} / {t} MiB','temperature':float(temp),'type':'NVIDIA'})
            return rows
        except Exception:return []

class AlertManager:
    @staticmethod
    def check(s):
        a=[]
        def add(c,m,critical=False):a.append({'component':c,'message':m,'level':'critical' if critical else 'warning'})
        if s.cpu>85:add('CPU',f'Average usage is {s.cpu:.0f}%',s.cpu>95)
        if s.per_cpu and max(s.per_cpu)>95:add('CPU',f'Core {s.per_cpu.index(max(s.per_cpu))} spiked to {max(s.per_cpu):.0f}%')
        if s.memory>90:add('Memory',f'Usage is {s.memory:.0f}%',s.memory>95)
        if s.swap>70:add('Swap',f'Usage is {s.swap:.0f}%')
        for d in s.disks:
            if d['percent']>90:add('Disk',f"{d['mount']} is {d['percent']:.0f}% full")
        return a

def system_info():
    u=platform.uname(); up=int(time.time()-psutil.boot_time()); return {'System':u.system,'Host':u.node,'Release':u.release,'Machine':u.machine,'Python':platform.python_version(),'Uptime':f'{up//86400}d {(up%86400)//3600}h'}
