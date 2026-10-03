"""Wire format and independent PC arithmetic; uses only the Python standard library."""
import struct
import zlib

MAGIC = b'RVEC'
MAX_N = 1024

def frame(command, sequence, payload=b'', *, version=1, flags=0):
    header = struct.pack('<BBHHH', version, command, sequence, len(payload), flags)
    content = header + payload
    return MAGIC + content + struct.pack('<I', zlib.crc32(content))

def parse_frame(raw):
    if len(raw) < 16 or raw[:4] != MAGIC:
        raise ValueError('Missing response frame or incorrect magic')
    version, command, sequence, length, flags = struct.unpack_from('<BBHHH', raw, 4)
    if version != 1 or flags or len(raw) != length + 16:
        raise ValueError('Response version, flags or length is invalid')
    if zlib.crc32(raw[4:-4]) != struct.unpack_from('<I', raw, len(raw)-4)[0]:
        raise ValueError('Response CRC32 mismatch')
    return command, sequence, raw[12:-4]

def dot_payload(a, b):
    if not 1 <= len(a) == len(b) <= MAX_N:
        raise ValueError('Vectors must have the same length, between 1 and 1024')
    return struct.pack('<HH', len(a), 0) + b''.join(struct.pack('<hh', x, y) for x, y in zip(a, b))

def reference_dot(a, b):
    # Python integers have arbitrary precision. No reuse of FPGA/firmware arithmetic.
    return sum(int(x) * int(y) for x, y in zip(a, b))

def parse_dot(payload):
    if len(payload) != 40:
        raise ValueError('Incorrect DOT response length')
    names = ('n','flags','software','hardware','software_cycles','hardware_total_cycles',
             'hardware_core_cycles','accelerator_status','completed')
    return dict(zip(names, struct.unpack('<HHqqIIIII', payload)))
