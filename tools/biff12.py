"""Minimal BIFF12 (.xlsb) record-level parser + rgce formula decompiler."""
import struct, io, sys

def iter_records(buf):
    """Yield (rec_id, payload_bytes, offset) from a BIFF12 part."""
    pos, n = 0, len(buf)
    while pos < n:
        start = pos
        # record id: 1 or 2 bytes (7 bits each, high bit of first byte = continuation)
        b0 = buf[pos]; pos += 1
        if b0 & 0x80:
            b1 = buf[pos]; pos += 1
            rid = (b0 & 0x7F) | ((b1 & 0x7F) << 7)
        else:
            rid = b0
        # record length: 1-4 bytes varint, 7 bits each
        size, shift = 0, 0
        while True:
            b = buf[pos]; pos += 1
            size |= (b & 0x7F) << shift
            if not (b & 0x80):
                break
            shift += 7
        payload = buf[pos:pos+size]
        pos += size
        yield rid, payload, start

def read_xlwidestring(payload, off):
    """XLWideString: 4-byte char count + utf-16le chars. Returns (str, newoff)."""
    n = struct.unpack_from('<I', payload, off)[0]
    off += 4
    if n == 0xFFFFFFFF:  # null string
        return None, off
    s = payload[off:off+2*n].decode('utf-16-le', errors='replace')
    return s, off + 2*n

def col_letter(c):
    s = ''
    c += 1
    while c:
        c, r = divmod(c-1, 26)
        s = chr(65+r) + s
    return s

# ---------------- rgce (parsed formula) decompiler ----------------

FUNC_TAB = {}  # fid -> (name, min_args_for_fixed)
def _load_functab():
    try:
        from xlrd.formula import func_defs
        for fid, (name, minargs, maxargs) in func_defs.items():
            FUNC_TAB[fid] = name
    except Exception:
        pass
    # ensure critical ones + post-BIFF8 future functions come through _xlfn names
    FUNC_TAB.setdefault(255, 'USERDEFINED')
    FUNC_TAB.update({
        336:'TEXTJOIN?',344:'SUBTOTAL',345:'SUMIF',346:'COUNTIF',347:'COUNTBLANK',
        350:'ISPMT',354:'ROMAN',358:'GETPIVOTDATA',359:'HYPERLINK',360:'PHONETIC',
        361:'AVERAGEA',362:'MAXA',363:'MINA',366:'STDEVPA',367:'VARPA',368:'BAHTTEXT',
        369:'THAIDAYOFWEEK',374:'THAIYEAR',375:'RTD',380:'CUBEVALUE',381:'CUBEMEMBER',
        382:'CUBEMEMBERPROPERTY',383:'CUBERANKEDMEMBER',384:'HEX2BIN',385:'HEX2DEC',
        480:'IFERROR',481:'COUNTIFS',482:'SUMIFS',483:'AVERAGEIF',484:'AVERAGEIFS',
        485:'AGGREGATE',486:'BINOM.DIST',
    })
_load_functab()

ERRORS = {0x00:'#NULL!',0x07:'#DIV/0!',0x0F:'#VALUE!',0x17:'#REF!',0x1D:'#NAME?',0x24:'#NUM!',0x2A:'#N/A',0x2B:'#GETTING_DATA'}

BINOPS = {0x03:'+',0x04:'-',0x05:'*',0x06:'/',0x07:'^',0x08:'&',0x09:'<',0x0A:'<=',0x0B:'=',0x0C:'>=',0x0D:'>',0x0E:'<>',0x0F:' ',0x10:',',0x11:':'}

def fmt_num(d):
    if d == int(d) and abs(d) < 1e15:
        return str(int(d))
    return repr(d)

class FormulaDecoder:
    def __init__(self, sheet_names=None, extern_map=None, defined_names=None):
        self.sheet_names = sheet_names or []
        self.extern_map = extern_map or {}    # ixti -> (first_sheet_idx, last_sheet_idx) or ('EXT', label)
        self.defined_names = defined_names or []  # list of names in order

    def sheet_prefix(self, ixti):
        m = self.extern_map.get(ixti)
        if m is None:
            return f'[ixti{ixti}]!'
        if isinstance(m, tuple) and m[0] == 'EXT':
            return f'[{m[1]}]!'
        a, b = m
        def nm(i):
            if 0 <= i < len(self.sheet_names):
                n = self.sheet_names[i]
                return f"'{n}'" if (' ' in n or any(ch in n for ch in "-!,()")) else n
            return f'#REF{i}'
        if a == b:
            return nm(a) + '!'
        if a == -1:
            return '#REF!'
        return nm(a) + ':' + nm(b) + '!'

    def ref(self, row, colflags, ixti=None):
        col = colflags & 0x3FFF
        crel = bool(colflags & 0x4000)
        rrel = bool(colflags & 0x8000)
        s = ('' if crel else '$') + col_letter(col) + ('' if rrel else '$') + str(row+1)
        return (self.sheet_prefix(ixti) if ixti is not None else '') + s

    def area(self, r1, r2, c1f, c2f, ixti=None):
        p = self.sheet_prefix(ixti) if ixti is not None else ''
        c1, c2 = c1f & 0x3FFF, c2f & 0x3FFF
        # whole-column style A:A -> rows 0..1048575
        if r1 == 0 and r2 == 1048575:
            a = ('' if c1f & 0x4000 else '$') + col_letter(c1)
            b = ('' if c2f & 0x4000 else '$') + col_letter(c2)
            return p + a + ':' + b
        a = ('' if c1f & 0x4000 else '$') + col_letter(c1) + ('' if c1f & 0x8000 else '$') + str(r1+1)
        b = ('' if c2f & 0x4000 else '$') + col_letter(c2) + ('' if c2f & 0x8000 else '$') + str(r2+1)
        return p + a + ':' + b

    def decode(self, rgce, rgcb=b'', anchor=None):
        """anchor=(row, col) resolves PtgRefN/PtgAreaN relative tokens (shared formulas)."""
        stack = []
        pos, n = 0, len(rgce)
        try:
          while pos < n:
            ptg = rgce[pos]; pos += 1
            base = ((ptg & 0x1F) | 0x20) if ptg >= 0x20 else ptg
            if ptg in BINOPS:
                b = stack.pop(); a = stack.pop()
                op = BINOPS[ptg]
                stack.append(f'{a}{op}{b}')
            elif ptg == 0x12: stack.append('+' + stack.pop())
            elif ptg == 0x13: stack.append('-' + stack.pop())
            elif ptg == 0x14: stack.append(stack.pop() + '%')
            elif ptg == 0x15: stack.append('(' + stack.pop() + ')')
            elif ptg == 0x16: stack.append('')
            elif ptg == 0x17:  # PtgStr
                ln = struct.unpack_from('<H', rgce, pos)[0]; pos += 2
                s = rgce[pos:pos+2*ln].decode('utf-16-le', errors='replace'); pos += 2*ln
                stack.append('"' + s.replace('"','""') + '"')
            elif ptg == 0x18:  # PtgList (structured table ref)
                # MS-XLSB PtgList: 12 bytes
                data = rgce[pos:pos+12]; pos += 12
                stack.append('[TABLEREF]')
            elif ptg == 0x19:  # PtgAttr
                sub = rgce[pos]; pos += 1
                if sub & 0x04:  # AttrChoose: skip table
                    ccases = struct.unpack_from('<H', rgce, pos)[0]
                    pos += 2 + 2*(ccases+1)
                elif sub & 0x10:  # AttrSum
                    pos += 2
                    stack.append(f'SUM({stack.pop()})')
                else:
                    pos += 2
            elif ptg == 0x1C:
                stack.append(ERRORS.get(rgce[pos], f'#ERR{rgce[pos]}')); pos += 1
            elif ptg == 0x1D:
                stack.append('TRUE' if rgce[pos] else 'FALSE'); pos += 1
            elif ptg == 0x1E:
                v = struct.unpack_from('<H', rgce, pos)[0]; pos += 2
                stack.append(str(v))
            elif ptg == 0x1F:
                v = struct.unpack_from('<d', rgce, pos)[0]; pos += 8
                stack.append(fmt_num(v))
            elif base == 0x20:  # PtgArray
                pos += 14
                stack.append('{ARRAY}')
            elif base == 0x21 or base == 0x22:  # PtgFunc / PtgFuncVar
                if base == 0x21:
                    fid = struct.unpack_from('<H', rgce, pos)[0]; pos += 2
                    name = FUNC_TAB.get(fid, f'FUNC{fid}')
                    argc = {480: 2, 481: 3, 358: 2}.get(fid)
                    if argc is None:
                        import xlrd.formula as xf
                        try:
                            argc = xf.func_defs[fid][1]
                        except Exception:
                            argc = 1
                    args = [stack.pop() for _ in range(argc)][::-1] if argc else []
                    stack.append(f'{name}({",".join(args)})')
                else:
                    cargs = rgce[pos]; pos += 1
                    fid = struct.unpack_from('<H', rgce, pos)[0]; pos += 2
                    fid &= 0x7FFF
                    name = FUNC_TAB.get(fid, f'FUNC{fid}')
                    args = [stack.pop() for _ in range(cargs)][::-1]
                    if fid == 255 and args:  # user defined: first arg is the name
                        stack.append(f'{args[0]}({",".join(args[1:])})')
                    else:
                        stack.append(f'{name}({",".join(args)})')
            elif base == 0x23:  # PtgName
                idx = struct.unpack_from('<I', rgce, pos)[0]; pos += 4
                nm = self.defined_names[idx-1] if 0 < idx <= len(self.defined_names) else f'NAME{idx}'
                stack.append(nm)
            elif base == 0x24:  # PtgRef
                r, cf = struct.unpack_from('<IH', rgce, pos); pos += 6
                stack.append(self.ref(r, cf))
            elif base == 0x25:  # PtgArea
                r1, r2, c1, c2 = struct.unpack_from('<IIHH', rgce, pos); pos += 12
                stack.append(self.area(r1, r2, c1, c2))
            elif base == 0x26:  # PtgMemArea
                pos += 6
            elif base == 0x27:  # PtgMemErr
                pos += 6
            elif base == 0x29:  # PtgMemFunc
                pos += 2
            elif base == 0x2A:  # PtgRefErr
                pos += 6; stack.append('#REF!')
            elif base == 0x2B:  # PtgAreaErr
                pos += 12; stack.append('#REF!')
            elif base == 0x2C:  # PtgRefN (relative to anchor cell)
                r, cf = struct.unpack_from('<iH', rgce, pos); pos += 6
                co = cf & 0x3FFF
                if co >= 0x2000: co -= 0x4000
                if anchor:
                    ar = anchor[0] + (r if cf & 0x8000 else 0) if cf & 0x8000 else r
                    ac = anchor[1] + co if cf & 0x4000 else co
                    crel = bool(cf & 0x4000); rrel = bool(cf & 0x8000)
                    stack.append(('' if crel else '$') + col_letter(ac) + ('' if rrel else '$') + str(ar+1))
                else:
                    stack.append(f'R[{r}]C[{co}]')
            elif base == 0x2D:  # PtgAreaN
                r1, r2, c1f, c2f = struct.unpack_from('<iiHH', rgce, pos); pos += 12
                def _off(cf):
                    co = cf & 0x3FFF
                    return co - 0x4000 if co >= 0x2000 else co
                if anchor:
                    a1r = anchor[0] + r1 if c1f & 0x8000 else r1
                    a2r = anchor[0] + r2 if c2f & 0x8000 else r2
                    a1c = anchor[1] + _off(c1f) if c1f & 0x4000 else _off(c1f)
                    a2c = anchor[1] + _off(c2f) if c2f & 0x4000 else _off(c2f)
                    p1 = ('' if c1f & 0x4000 else '$') + col_letter(a1c) + ('' if c1f & 0x8000 else '$') + str(a1r+1)
                    p2 = ('' if c2f & 0x4000 else '$') + col_letter(a2c) + ('' if c2f & 0x8000 else '$') + str(a2r+1)
                    stack.append(p1 + ':' + p2)
                else:
                    stack.append(f'AREA_N[{r1}:{r2}]')
            elif base == 0x39:  # PtgNameX
                ixti, idx = struct.unpack_from('<HI', rgce, pos); pos += 6
                stack.append(f'{self.sheet_prefix(ixti)}NAMEX{idx}')
            elif base == 0x3A:  # PtgRef3d
                ixti, r, cf = struct.unpack_from('<HIH', rgce, pos); pos += 8
                stack.append(self.ref(r, cf, ixti))
            elif base == 0x3B:  # PtgArea3d
                ixti, r1, r2, c1, c2 = struct.unpack_from('<HIIHH', rgce, pos); pos += 14
                stack.append(self.area(r1, r2, c1, c2, ixti))
            elif base == 0x3C:  # PtgRefErr3d
                pos += 8; stack.append('#REF!')
            elif base == 0x3D:  # PtgAreaErr3d
                pos += 14; stack.append('#REF!')
            elif ptg == 0x01:  # PtgExp: BIFF12 payload = master row (4 bytes)
                r = struct.unpack_from('<I', rgce, pos)[0]
                pos += 4
                stack.append(f'@SHARED(master_row={r+1})')
            elif ptg == 0x02:  # PtgTbl
                pos += 6; stack.append('TBL')
            elif ptg == 0x00:
                break
            else:
                stack.append(f'?PTG{ptg:02X}?')
                break
          return stack[-1] if stack else ''
        except Exception as e:
            return f'!DECODE_ERR({e})!'

def parse_cell_parsed_formula(payload, off):
    """CellParsedFormula: cce(4) rgce cb(4) rgcb -> (rgce, rgcb, newoff)"""
    cce = struct.unpack_from('<I', payload, off)[0]; off += 4
    rgce = payload[off:off+cce]; off += cce
    if off + 4 <= len(payload):
        cb = struct.unpack_from('<I', payload, off)[0]; off += 4
        rgcb = payload[off:off+cb]; off += cb
    else:
        rgcb = b''
    return rgce, rgcb, off
