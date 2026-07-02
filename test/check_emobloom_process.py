# check_emobloom_process.py
import subprocess
import psutil
import time

print("=" * 80)
print("检查 Emobloom 进程状态")
print("=" * 80)

# 1. 查找所有 Python 进程
print("\n【步骤 1】查找所有运行中的 Python 进程:")
print("-" * 80)
for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
    try:
        if 'python' in proc.name().lower():
            print(f"PID: {proc.pid}")
            print(f"Name: {proc.name()}")
            print(f"Command: {' '.join(proc.cmdline())[:150]}")
            print()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass

# 2. 查找 Emobloom 相关进程
print("\n【步骤 2】查找 Emobloom 相关进程:")
print("-" * 80)
emobloom_found = False
for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
    try:
        cmdline = ' '.join(proc.cmdline())
        if 'emobloom' in cmdline.lower() or 'emotion' in cmdline.lower():
            emobloom_found = True
            print(f"✓ 找到 Emobloom 进程:")
            print(f"  PID: {proc.pid}")
            print(f"  Name: {proc.name()}")
            print(f"  Command: {cmdline[:200]}")
            print(f"  Status: {proc.status()}")
            
            # 获取内存使用
            try:
                mem = proc.memory_info()
                print(f"  Memory: {mem.rss / (1024**2):.1f} MB")
            except:
                pass
            print()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass

if not emobloom_found:
    print("✗ 未找到 Emobloom 进程运行")

# 3. 检查端口 65413
print("\n【步骤 3】检查端口 65413 监听状态:")
print("-" * 80)
import socket
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
result = sock.connect_ex(('127.0.0.1', 65413))
sock.close()

if result == 0:
    print("✓ 端口 65413 正在监听")
else:
    print("✗ 端口 65413 未监听 (WinError 10061)")

# 4. 查找 GPU 进程
print("\n【步骤 4】检查 GPU 使用情况:")
print("-" * 80)
try:
    gpu_result = subprocess.run(['nvidia-smi', '--query-processes=pid,process_name,used_memory'],
                               capture_output=True, text=True, timeout=5)
    print(gpu_result.stdout)
except Exception as e:
    print(f"无法运行 nvidia-smi: {e}")

print("=" * 80)