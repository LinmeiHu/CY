"""Seal delivered small files and external artifacts, excluding transient scratch."""
from .build import HERE,EXT,sha,js

def main():
 rows=[];total=0
 for p in sorted(EXT.rglob('*')):
  if not p.is_file() or 'tmp' in p.relative_to(EXT).parts:continue
  rows.append(f'{sha(p)}  {p}\n');total+=p.stat().st_size
 (HERE/'output/large_artifact_manifest.sha256').write_text(''.join(rows));js(HERE/'output/storage_summary.json',dict(large_artifact_root=str(EXT),files=len(rows),bytes=total,transient_tmp_excluded=True))
 files=[p for p in HERE.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.name!='output_manifest.sha256']
 (HERE/'output/output_manifest.sha256').write_text(''.join(f'{sha(p)}  {p.relative_to(HERE)}\n' for p in sorted(files)))
 print('Sealed external files',len(rows),'bytes',total,'small files',len(files))
if __name__=='__main__':main()
