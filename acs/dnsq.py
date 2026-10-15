import socket, struct, sys
def q(name, server="192.168.3.250"):
    pkt=b'\xab\xcd\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00'
    pkt+=b''.join(bytes([len(p)])+p.encode() for p in name.split('.'))+b'\x00'+b'\x00\x01\x00\x01'
    s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); s.settimeout(5)
    try:
        s.sendto(pkt,(server,53)); d,_=s.recvfrom(1024)
    except Exception as e:
        return f"✗ {e}"
    finally: s.close()
    rcode=d[3]&0x0f; n=struct.unpack('!H',d[6:8])[0]
    i=12
    while d[i]!=0: i+=d[i]+1
    i+=5; ips=[]
    for _ in range(n):
        while d[i]!=0: i+= 2 if (d[i]&0xc0)==0xc0 else d[i]+1
        i+=1; typ=struct.unpack('!H',d[i:i+2])[0]; i+=8
        ln=struct.unpack('!H',d[i:i+2])[0]; i+=2
        if typ==1 and ln==4: ips.append('.'.join(str(b) for b in d[i:i+4]))
        i+=ln
    return f"rcode={rcode} {ips if ips else '无A记录'}"
for h in sys.argv[1:]:
    print(f"  {h:34} -> {q(h)}")
