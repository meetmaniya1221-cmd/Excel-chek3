import sys, struct, json, re, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from biff12 import iter_records, FormulaDecoder, parse_cell_parsed_formula, col_letter, ERRORS

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'xlsb_extract')

# ---------- workbook globals ----------
sheet_names = []
extern_map = {}
defined_names = []
buf = open(f'{BASE}/xl/workbook.bin','rb').read()
for rid, pl, off in iter_records(buf):
    if rid == 156:  # BrtBundleSh
        state, tabid = struct.unpack_from('<II', pl, 0)
        cch = struct.unpack_from('<I', pl, 8)[0]
        relid = pl[12:12+2*cch].decode('utf-16-le')
        cch2 = struct.unpack_from('<I', pl, 12+2*cch)[0]
        name = pl[16+2*cch:16+2*cch+2*cch2].decode('utf-16-le')
        sheet_names.append(name)
    elif rid == 362:  # BrtExternSheet
        n = struct.unpack_from('<I', pl, 0)[0]
        for i in range(n):
            sup, first, last = struct.unpack_from('<III', pl, 4+12*i)
            f = struct.unpack_from('<i', pl, 4+12*i+4)[0]
            l = struct.unpack_from('<i', pl, 4+12*i+8)[0]
            extern_map[i] = (f, l)
    elif rid == 39:  # BrtName
        flags = struct.unpack_from('<I', pl, 0)[0]
        chKey = pl[4]
        itab = struct.unpack_from('<i', pl, 5)[0]
        cch = struct.unpack_from('<I', pl, 9)[0]
        name = pl[13:13+2*cch].decode('utf-16-le')
        rest_off = 13+2*cch
        defined_names.append({'name': name, 'flags': flags, 'itab': itab, '_rest': pl[rest_off:rest_off+400].hex()})

dec = FormulaDecoder(sheet_names, extern_map, [d['name'] for d in defined_names])

# decode defined-name formulas
for d in defined_names:
    raw = bytes.fromhex(d['_rest'])
    try:
        rgce, rgcb, _ = parse_cell_parsed_formula(raw, 0)
        d['refersTo'] = dec.decode(rgce, rgcb)
    except Exception as e:
        d['refersTo'] = f'ERR {e}'
    del d['_rest']

# ---------- shared strings ----------
sst = []
buf = open(f'{BASE}/xl/sharedStrings.bin','rb').read()
for rid, pl, off in iter_records(buf):
    if rid == 19:  # BrtSSTItem
        cch = struct.unpack_from('<I', pl, 1)[0]
        sst.append(pl[5:5+2*cch].decode('utf-16-le', errors='replace'))
print(f'workbook: sheets={sheet_names} externs={extern_map} sst={len(sst)}', file=sys.stderr)

# ---------- sheet parser ----------
def parse_sheet(fname, sheet_name, max_headrows=6, dump_rows=None, dump_max_col=140):
    buf = open(f'{BASE}/xl/worksheets/{fname}.bin','rb').read()
    cur_row = -1
    dims = None
    cols_hidden = []
    autofilter = None
    protection = None
    merges = []
    hlinks = []
    headers = {}           # (row, col) -> value for row < max_headrows
    dump = {}              # row -> {col: value} for rows in dump_rows
    colstats = {}          # col -> dict(nval, nfml, types Counter, formulas dict normfml -> [count, example_cell, example_raw])
    unknown_ids = {}
    shared_fmlas = {}      # (row,col) -> decoded (from BrtShrFmla)
    n_rows_with_data = 0
    max_col_seen = -1
    last_row_seen = -1

    def stat(col):
        s = colstats.get(col)
        if s is None:
            s = colstats[col] = {'nval':0,'nfml':0,'types':{}, 'formulas':{}}
        return s

    def add_val(col, typ, val):
        s = stat(col)
        s['nval'] += 1
        s['types'][typ] = s['types'].get(typ,0)+1
        if cur_row < max_headrows:
            headers[(cur_row, col)] = val
        if dump_rows and cur_row in dump_rows and col <= dump_max_col:
            dump.setdefault(cur_row, {})[col] = val

    def add_fml(col, val, rgce, rgcb):
        s = stat(col)
        s['nfml'] += 1
        try:
            f = dec.decode(rgce, rgcb)
        except Exception as e:
            f = f'!ERR {e}'
        norm = re.sub(r'(?<![A-Z$:])(\d+)', 'ROW', f)
        ent = s['formulas'].get(norm)
        cellref = f'{col_letter(col)}{cur_row+1}'
        if ent is None:
            s['formulas'][norm] = [1, cellref, f]
        else:
            ent[0] += 1
        if cur_row < max_headrows:
            headers[(cur_row, col)] = val
        if dump_rows and cur_row in dump_rows and col <= dump_max_col:
            dump.setdefault(cur_row, {})[col] = val

    for rid, pl, off in iter_records(buf):
        if rid == 0:  # row
            cur_row = struct.unpack_from('<I', pl, 0)[0]
            n_rows_with_data += 1
            last_row_seen = max(last_row_seen, cur_row)
            continue
        if 1 <= rid <= 11:
            col = struct.unpack_from('<I', pl, 0)[0]
            max_col_seen = max(max_col_seen, col)
            if rid == 1:
                add_val(col, 'blank', None)
            elif rid == 2:  # RK
                iv = struct.unpack_from('<i', pl, 8)[0]
                v = float(iv >> 2) if iv & 2 else struct.unpack('<d', b'\0\0\0\0' + struct.pack('<I', (iv & 0xFFFFFFFC)))[0]
                if iv & 1: v /= 100
                add_val(col, 'num', v)
            elif rid == 3:
                add_val(col, 'err', ERRORS.get(pl[8], pl[8]))
            elif rid == 4:
                add_val(col, 'bool', bool(pl[8]))
            elif rid == 5:
                add_val(col, 'num', struct.unpack_from('<d', pl, 8)[0])
            elif rid == 6:
                cch = struct.unpack_from('<I', pl, 8)[0]
                add_val(col, 'str', pl[12:12+2*cch].decode('utf-16-le', errors='replace'))
            elif rid == 7:
                isst = struct.unpack_from('<I', pl, 8)[0]
                add_val(col, 'str', sst[isst] if isst < len(sst) else f'SST{isst}')
            elif rid == 8:  # formula -> string
                cch = struct.unpack_from('<I', pl, 8)[0]
                v = pl[12:12+2*cch].decode('utf-16-le', errors='replace')
                o = 12+2*cch+2
                rgce, rgcb, _ = parse_cell_parsed_formula(pl, o)
                add_fml(col, v, rgce, rgcb)
            elif rid == 9:  # formula -> num
                v = struct.unpack_from('<d', pl, 8)[0]
                rgce, rgcb, _ = parse_cell_parsed_formula(pl, 18)
                add_fml(col, v, rgce, rgcb)
            elif rid == 10:
                v = bool(pl[8])
                rgce, rgcb, _ = parse_cell_parsed_formula(pl, 11)
                add_fml(col, v, rgce, rgcb)
            elif rid == 11:
                v = ERRORS.get(pl[8], pl[8])
                rgce, rgcb, _ = parse_cell_parsed_formula(pl, 11)
                add_fml(col, v, rgce, rgcb)
            continue
        if rid == 148:
            r1, r2, c1, c2 = struct.unpack_from('<IIII', pl, 0)
            dims = f'{col_letter(c1)}{r1+1}:{col_letter(c2)}{r2+1}'
        elif rid == 60:
            c1, c2, w, ixfe, flags = struct.unpack_from('<IIIIH', pl, 0)
            if flags & 0x01:
                cols_hidden.append((c1, c2))
        elif rid == 161:  # BrtBeginAFilter
            r1, r2, c1, c2 = struct.unpack_from('<IIII', pl, 0)
            autofilter = f'{col_letter(c1)}{r1+1}:{col_letter(c2)}{r2+1}'
        elif rid == 535:
            protection = pl[:12].hex()
        elif rid == 176:  # BrtMergeCell
            r1, r2, c1, c2 = struct.unpack_from('<IIII', pl, 0)
            merges.append(f'{col_letter(c1)}{r1+1}:{col_letter(c2)}{r2+1}')
        elif rid == 426:  # BrtShrFmla
            pass
        elif rid not in (37,38,35,36,129,130,133,134,137,138,145,146,147,152,390,391,476,477,478,485,550,551,643,644,645,1024,1045,3072,151,153,154,155,494,426,427,428,429,430,431,432,433,64,3073,552,553,554,555,556,16,17,18,19,20,494,495,496,497,498,573,574,575):
            unknown_ids[rid] = unknown_ids.get(rid, 0) + 1

    return {
        'sheet': sheet_name, 'file': fname, 'dims': dims, 'rows_with_data': n_rows_with_data,
        'last_row': last_row_seen+1, 'max_col': col_letter(max_col_seen) if max_col_seen>=0 else None,
        'hidden_cols': [[col_letter(a), col_letter(b)] for a,b in cols_hidden],
        'autofilter': autofilter, 'protection': protection, 'merges_n': len(merges), 'merges_sample': merges[:15],
        'headers': {f'{col_letter(c)}{r+1}': v for (r,c),v in sorted(headers.items()) if v not in (None,'')},
        'dump': {str(r+1): {col_letter(c): v for c,v in sorted(cols.items())} for r,cols in sorted(dump.items())} if dump_rows else None,
        'colstats': {col_letter(c): {'nval':s['nval'],'nfml':s['nfml'],'types':s['types'],
                                     'formulas':{k: v for k,v in sorted(s['formulas'].items(), key=lambda kv:-kv[1][0])[:6]}}
                     for c,s in sorted(colstats.items())},
        'unknown_ids': unknown_ids,
    }

out = {'sheets': sheet_names, 'extern_map': {str(k):v for k,v in extern_map.items()},
       'defined_names': defined_names, 'results': {}}

jobs = [
    ('sheet1', 'Region', 15, set(range(0,14))),
    ('sheet2', 'Analysis Report', 13, set(range(0,13))),
    ('sheet3', 'PP', 6, set(range(0,60))),
    ('sheet4', 'Temp', 6, set(range(0,8))),
    ('sheet7', 'Update Data', 6, set(range(0,30))),
    ('sheet6', 'Sales', 4, set(range(0,4))),
    ('sheet5', 'Payment', 4, set(range(0,4))),
]
for fname, sname, hr, dr in jobs:
    print(f'parsing {sname}...', file=sys.stderr)
    out['results'][sname] = parse_sheet(fname, sname, max_headrows=hr, dump_rows=dr)

with open('sheet_analysis.json','w') as f:
    json.dump(out, f, indent=1, default=str)
print('DONE', file=sys.stderr)
