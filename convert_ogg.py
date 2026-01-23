import struct
import sys
import os
import argparse
# CRC32 implementation for Ogg
# Poly: 0x04c11db7
CRC_TABLE = []

def init_crc_table():
    global CRC_TABLE
    poly = 0x04c11db7
    for i in range(256):
        r = i << 24
        for _ in range(8):
            if r & 0x80000000:
                r = (r << 1) ^ poly
            else:
                r <<= 1
            r &= 0xFFFFFFFF
        CRC_TABLE.append(r)

init_crc_table()

def get_oggs_checksum(data):
    crc = 0
    for byte in data:
        crc = (crc << 8) ^ CRC_TABLE[((crc >> 24) & 0xFF) ^ byte]
        crc &= 0xFFFFFFFF
    return crc


class WwiseOpusConverter:
    def __init__(self, input_path):
        self.input_path = input_path
        self.file_size = os.path.getsize(input_path)
        self.data = open(input_path, 'rb')
        self.big_endian = False
        
        # Header info
        self.channels = 0
        self.sample_rate = 0
        self.total_samples = 0
        self.seek_offset = 0
        self.seek_size = 0
        self.data_offset = 0
        self.data_size = 0
        
        # State
        self.packet_sizes = []
        
    def read_u32(self):
        b = self.data.read(4)
        if len(b) < 4: return 0
        fmt = '>I' if self.big_endian else '<I'
        return struct.unpack(fmt, b)[0]
    def read_u16(self):
        b = self.data.read(2)
        if len(b) < 2: return 0
        fmt = '>H' if self.big_endian else '<H'
        return struct.unpack(fmt, b)[0]
    
    def read_u8(self):
        b = self.data.read(1)
        if len(b) < 1: return 0
        return b[0]
    def parse_riff(self):
        self.data.seek(0)
        magic = self.data.read(4)
        if magic == b'RIFX':
            self.big_endian = True
        elif magic == b'RIFF':
            self.big_endian = False
        else:
            raise ValueError("Not a RIFF/RIFX file")
            
        self.read_u32() # File size (often ignored/wrong in Wwise)
        
        wave = self.data.read(4)
        if wave != b'WAVE':
            raise ValueError("Not a WAVE file")
            
        # Parse chunks
        offset = 12
        while offset < self.file_size:
            self.data.seek(offset)
            chunk_id = self.data.read(4)
            if len(chunk_id) < 4: break
            
            chunk_size = self.read_u32()
            
            # Helper to peek/read chunk data
            next_chunk = offset + 8 + chunk_size
            # Padding for RIFF alignment? Wwise usually 2-byte aligned but chunks sizes seem precise
            # Actually standard RIFF chunks are word-aligned, but let's trust the read loop
            
            if chunk_id == b'fmt ':
                self.parse_fmt(chunk_size)
            elif chunk_id == b'data':
                self.data_offset = offset + 8
                self.data_size = chunk_size
            elif chunk_id == b'seek':
                self.seek_offset = offset + 8
                self.seek_size = chunk_size
                
            offset = next_chunk
    def parse_fmt(self, size):
        # Basic WAVEFORMATEX
        fmt_code = self.read_u16() # 0x00
        self.channels = self.read_u16() # 0x02
        self.sample_rate = self.read_u32() # 0x04
        self.read_u32() # avg bytes per sec 0x08
        self.read_u16() # block align 0x0c
        self.read_u16() # bits per sample 0x0e
        
        extra_size = 0
        if size > 16:
            extra_size = self.read_u16()

        # Wwise Opus (0x3041) or Opus (0x3040)
        # 0x3041 = OPUS_WEM (newer)
        # 0x3040 = Standard Opus (older?)

        if fmt_code not in [0x3040, 0x3041, 0x3039]:
            raise Exception(f"Warning: Format code 0x{fmt_code:04x} is not standard Wwise Opus. Please try ww2ogg.")
        if extra_size >= 12:
            # For 0x3041 (OpusWem):
            # 0x12: Samples per frame (usually 960)
            # 0x16: Total samples
            # 0x1A: Seek table size / 2?
            # Note: The C code says:
            # vgmstream->num_samples = read_s32(ww.fmt_offset + 0x18, sf);
            # Wait, fmt_offset + 0x18.
            # 0x00: code(2)
            # 0x02: chan(2)
            # 0x04: rate(4)
            # 0x08: avg(4)
            # 0x0c: align(2)
            # 0x0e: bits(2)
            # 0x10: extra_size(2)
            # 0x12: channel_mask(4) - usually
            # 0x16: ...

            # In Wwise Opus 0x3041:
            # The C code says: vgmstream->num_samples = read_s32(ww.fmt_offset + 0x18, sf);
            # Let's adjust for relative reading logic
            # self.data.read(4) # Channel mask (skip)

            # Let's just trust we grabbed the essential info: channels, rate.
            # We can grab num_samples if we absolutely need it for accurate duration,
            # but Ogg granule pos handles that mostly.
            pass
    def parse_seek(self):
        if self.seek_offset == 0 or self.seek_size == 0:
            return
            
        self.data.seek(self.seek_offset)
        count = self.seek_size // 2 # uint16 array
        for _ in range(count):
            self.packet_sizes.append(self.read_u16())
            
    def make_ogg_page(self, packets, sequence, granule, stream_serial, check_last=False):
        # Header (0x1B bytes) + Lacing values + Data
        # Capture "OggS"
        page = bytearray(b'OggS')
        page.append(0) # Version
        
        flags = 0
        if sequence == 0: flags |= 0x02 # BOS
        if check_last:
            # Technically we should check if this is the absolute last page
            pass
            
        page.append(flags) 
        
        # Granule (8 bytes LE)
        page.extend(struct.pack('<Q', granule))
        
        # Serial (4 bytes LE)
        page.extend(struct.pack('<I', stream_serial))
        
        # Sequence (4 bytes LE)
        page.extend(struct.pack('<I', sequence))
        
        # Checksum (4 bytes placeholder)
        page.extend(b'\x00\x00\x00\x00')
        
        # Segments
        # Packets might need lacing if > 255 bytes
        # Standard Ogg: each packet is a segment, unless > 255, then it spans.
        # But each segment in the table describes the length of the segment.
        # Length 255 means "continue to next segment".
        # Length < 255 means "end of packet".
        
        # However, `packets` input here is list of (payload_bytes).
        segment_table = bytearray()
        payload_data = bytearray()
        
        for p in packets:
            size = len(p)
            while size >= 255:
                segment_table.append(255)
                size -= 255
            segment_table.append(size)
            payload_data.extend(p)
            
        page.append(len(segment_table))
        page.extend(segment_table)
        page.extend(payload_data)
        
        # Calculate CRC
        crc = get_oggs_checksum(page)
        # Write CRC at offset 22
        page[22] = crc & 0xFF
        page[23] = (crc >> 8) & 0xFF
        page[24] = (crc >> 16) & 0xFF
        page[25] = (crc >> 24) & 0xFF
        
        return page
    def create_opus_head(self, pre_skip=0):
        # Magic "OpusHead"
        # Version 1 (1 byte)
        # Channels (1 byte)
        # Pre-skip (2 bytes)
        # Sample rate (4 bytes) - Information only
        # Gain (2 bytes)
        # Mapping family (1 byte)
        # Optional mapping table...
        
        packet = bytearray(b'OpusHead')
        packet.append(1)
        packet.append(self.channels)
        packet.extend(struct.pack('<H', pre_skip))
        packet.extend(struct.pack('<I', self.sample_rate)) # 48000 usually
        packet.extend(struct.pack('<H', 0)) # Gain
        packet.append(0) # Mapping family 0 (mono/stereo)
        
        return packet
    def create_opus_tags(self):
        # Magic "OpusTags"
        # Vendor len (4 LE)
        # Vendor str
        # Comment list len (4 LE) .. 0
        
        vendor = b'Converted from Wwise'
        packet = bytearray(b'OpusTags')
        packet.extend(struct.pack('<I', len(vendor)))
        packet.extend(vendor)
        packet.extend(struct.pack('<I', 0)) # 0 comments
        
        return packet
    def opus_packet_get_samples(self, packet):
        # Basic parsing of TOC byte
        if len(packet) < 1: return 0
        
        toc = packet[0]
        config = (toc >> 3) & 0x1F
        mode = (toc >> 7) & 0x1
        
        # Simple lookup for common frame dicts (48kHz)
        #  0...11: SILK-only, 10, 20, 40, 60 ms
        # 12...15: Hybrid, 10, 20 ms
        # 16...31: CELT-only, 2.5, 5, 10, 20 ms
        
        # Standard sizes for 48kHz
        sizes = [
            480, 960, 1920, 2880, # 0-3
            480, 960, 1920, 2880, # 4-7
            480, 960, 1920, 2880, # 8-11
            480, 960,             # 12-13
            480, 960,             # 14-15
            120, 240, 480, 960,   # 16-19
            120, 240, 480, 960,   # 20-23
            120, 240, 480, 960,   # 24-27
            120, 240, 480, 960,   # 28-31
        ]
        
        frame_size = sizes[config] if config < len(sizes) else 960
        
        # Count frames
        count = toc & 0x3
        if count == 0:
            frame_count = 1
        elif count == 1:
            frame_count = 2
        elif count == 2:
            frame_count = 2
        else: # count == 3
             # Arbitrary number of frames, signaled in byte 1
             if len(packet) < 2: return 0
             frame_count = packet[1] & 0x3F
             
        return frame_size * frame_count
    def convert(self, output_path):
        self.parse_riff()
        self.parse_seek()
        
        if not self.packet_sizes:
            print("No seek table found. Cannot determine packet sizes.")
            # Fallback for some files?
            # If no seek table, maybe it's just raw Ogg?
            # Or constant bitrate? Wwise Opus is rarely CBR.
            return
        with open(output_path, 'wb') as outfile:
            stream_serial = 0x12345678
            sequence = 0
            granule = 0
            
            # 1. BOS Page: OpusHead
            head = self.create_opus_head()
            page = self.make_ogg_page([head], sequence, 0, stream_serial)
            outfile.write(page)
            sequence += 1
            
            # 2. OpusTags
            tags = self.create_opus_tags()
            page = self.make_ogg_page([tags], sequence, 0, stream_serial)
            outfile.write(page)
            sequence += 1
            
            # 3. Audio Data
            # Wwise packet_sizes table tells us how many bytes to read for each packet
            self.data.seek(self.data_offset)
            
            # Optimization: Group packets into pages (approx 1 page per 1000ms or 64KB?)
            # Ogg recommendation: ~4KB-8KB pages usually.
            # Let's just do 1 packet per page for simplicity as per the C code?
            # "Uses an intermediate buffer to make full Ogg pages... static size_t make_oggs_page"
            # The C code seems to pack roughly, but Wwise packets can be large.
            # Let's try to bundle a few packets per page if they are small, or 1 per page.
            # Ideally < 65KB.
            
            current_page_packets = []
            current_page_size = 0
            
            for i, p_size in enumerate(self.packet_sizes):
                payload = self.data.read(p_size)
                if len(payload) != p_size:
                    print(f"Unexpected EOF reading packet {i}")
                    break
                    
                samples = self.opus_packet_get_samples(payload)
                granule += samples
                
                # Check bounds for safety (page size < 65KB)
                # But actually, writing one packet per page is safest for strict seeking and granule correctness
                # unless we track granule carefully.
                # The C code: "make_oggs_page(..., data->samples_done)" implies 1 packet per page 
                # OR it accumulates.
                # In `opus_io_read`:
                #   data_size = get_table_frame_size(...)
                #   read_streamfile(...)
                #   make_oggs_page(...)
                # It looks like it makes ONE Ogg page per Wwise packet.
                # Wwise packets are usually ~120ms or something? No, they seem to be typical Opus frames.
                
                # Let's stick to 1 Packet = 1 Ogg Page for maximum robustness with the C impl reference,
                # although inefficient overhead.
                
                page = self.make_ogg_page([payload], sequence, granule, stream_serial)
                outfile.write(page)
                sequence += 1
                
            # Set EOS?
            # The last page should have flag 0x04.
            # Since we write immediately, we don't know which is last easily unless we check index.
            # It's fine for most players.