# find_emobloom_port.py
import socket
import requests

print("扫描所有开放端口...")
for port in range(65400, 65430):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    result = sock.connect_ex(('127.0.0.1', port))
    sock.close()
    
    if result == 0:
        print(f"\n✓ 端口 {port} 开放")
        try:
            r = requests.get(f"http://127.0.0.1:{port}/v1/models", timeout=1)
            print(f"  响应: {r.status_code}")
            print(f"  内容: {r.text[:100]}")
        except Exception as e:
            print(f"  错误: {e}")