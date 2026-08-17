import sys, struct, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from biff12 import iter_records
import pandas as pd, numpy as np

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'xlsb_extract')

sst = []
for rid, pl, off in iter_records(open(f'{BASE}/xl/sharedStrings.bin','rb').read()):
    if rid == 19:
        cch = struct.unpack_from('<I', pl, 1)[0]
        sst.append(pl[5:5+2*cch].decode('utf-16-le', errors='replace'))

buf = open(f'{BASE}/xl/worksheets/sheet5.bin','rb').read()
cur = -1
recs = {}
for rid, pl, off in iter_records(buf):
    if rid == 0:
        cur = struct.unpack_from('<I', pl, 0)[0]
        continue
    if rid in (2,5,7,6,4,3,1):
        col = struct.unpack_from('<I', pl, 0)[0]
        if cur < 1:  # skip anything above header (header = row index 1 = sheet row 2)
            continue
        if rid == 2:
            iv = struct.unpack_from('<i', pl, 8)[0]
            v = float(iv >> 2) if iv & 2 else struct.unpack('<d', b'\0\0\0\0'+struct.pack('<I', iv & 0xFFFFFFFC))[0]
            if iv & 1: v /= 100
        elif rid == 5:
            v = struct.unpack_from('<d', pl, 8)[0]
        elif rid == 7:
            v = sst[struct.unpack_from('<I', pl, 8)[0]]
        elif rid == 6:
            cch = struct.unpack_from('<I', pl, 8)[0]
            v = pl[12:12+2*cch].decode('utf-16-le', 'replace')
        elif rid == 4:
            v = bool(pl[8])
        else:
            v = None
        recs.setdefault(cur, {})[col] = v

hdr = recs.pop(1)  # row index 1 = sheet row 2 = header
rows = [recs[r] for r in sorted(recs)]
ncols = 114
cols = [hdr.get(i, f'col{i}') for i in range(ncols)]
# dedupe header names
seen = {}
for i, c in enumerate(cols):
    c = str(c)
    if c in seen:
        seen[c] += 1
        cols[i] = f'{c}.{seen[c]}'
    else:
        seen[c] = 0
data = [[r.get(i) for i in range(ncols)] for r in rows]
df = pd.DataFrame(data, columns=cols)
print('shape:', df.shape)
df.to_pickle(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'payment.pkl'))
print('saved payment.pkl')
