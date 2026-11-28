"""Atomic versioned checkpoint ledger; no raw bars, credentials, or feature values by default."""
from pathlib import Path
import os,json,re,tempfile
from .model_e0 import digest
SCHEMA=1
def atomic(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix=".tmp-",dir=path.parent)
    try:
        with os.fdopen(fd,"w",encoding="utf8") as f:
            json.dump(data,f,ensure_ascii=False,sort_keys=True,allow_nan=False,separators=(",",":"));f.flush();os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)
class Ledger:
    def __init__(self,path,identity):
        self.path=Path(path);self.identity=identity
    def file(self,code):
        if not re.fullmatch(r"\d{6}\.(SH|SZ)",code):raise ValueError("bad code")
        return self.path/(code+".json")
    def read(self,code,source):
        f=self.file(code)
        if not f.exists():return None
        try:
            row=json.loads(f.read_text())
            if row["schema"]!=SCHEMA or row["identity"]!=self.identity or row["source"]!=source or row["code"]!=code:return None
            if digest(row["result"])!=row["digest"]:return None
            if row["result"]["counts"]["planned"]!=row["result"]["counts"]["computed"]+row["result"]["counts"].get("not_observed",0):return None
            return row["result"]
        except (ValueError,TypeError,KeyError,OSError):return None
    def write(self,code,source,result):
        atomic(self.file(code),{"schema":SCHEMA,"identity":self.identity,"code":code,"source":source,"result":result,"digest":digest(result)})
